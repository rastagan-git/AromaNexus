"""Polite, retrying HTTP access with a small transparent disk cache."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import requests

from flavor_data_crawler.models import utc_now_iso

DEFAULT_CACHE_DIR = Path(
    os.environ.get(
        "FLAVOR_DATA_CACHE_DIR",
        Path.home() / ".cache" / "flavor-data-crawler" / "http",
    )
)
DEFAULT_USER_AGENT = (
    "Flavor-Data-Crawler/0.2 "
    "(+https://github.com/rastagan-git/Flavor-Data-Crawler; research client)"
)
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
CACHE_FORMAT_VERSION = 1

Params = Mapping[str, object] | Sequence[tuple[str, object]] | None
Timeout = float | tuple[float, float]


@dataclass(frozen=True, slots=True)
class RetrievalMetadata:
    """Metadata describing how and when an HTTP representation was retrieved."""

    requested_url: str
    url: str
    retrieved_at: str
    status_code: int
    cache_hit: bool
    attempts: int


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Serializable subset of :class:`requests.Response` used by adapters."""

    status_code: int
    text: str
    headers: Mapping[str, str]
    metadata: RetrievalMetadata

    @property
    def url(self) -> str:
        return self.metadata.url

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> Any:
        """Decode the response body as JSON."""

        return json.loads(self.text)

    def raise_for_status(self) -> None:
        """Raise a requests-compatible error for non-success responses."""

        if not self.ok:
            raise requests.HTTPError(
                f"{self.status_code} response for {self.url}",
                response=self,
            )


class HttpClientError(RuntimeError):
    """Raised when every request attempt fails before receiving a response."""

    def __init__(self, url: str, attempts: int, cause: BaseException) -> None:
        super().__init__(f"Request failed after {attempts} attempt(s): {url}: {cause}")
        self.url = url
        self.attempts = attempts
        self.__cause__ = cause


class CachedHttpClient:
    """A requests-based client with caching, throttling, and bounded retries.

    Only successful GET responses are cached. Cache files contain plain JSON and
    are written atomically, so an interrupted run cannot leave a half-written
    response behind. ``session``, ``sleep``, and clocks are injectable to keep
    provider tests fully offline and deterministic.
    """

    def __init__(
        self,
        *,
        cache_dir: str | Path | None = DEFAULT_CACHE_DIR,
        cache_ttl: float | None = 7 * 24 * 60 * 60,
        timeout: Timeout = (5.0, 30.0),
        min_interval: float = 0.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        session: requests.Session | Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        if cache_ttl is not None and cache_ttl < 0:
            raise ValueError("cache_ttl must be non-negative or None")
        if min_interval < 0:
            raise ValueError("min_interval must be non-negative")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if backoff_factor < 0:
            raise ValueError("backoff_factor must be non-negative")

        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.min_interval = float(min_interval)
        self.max_retries = max_retries
        self.backoff_factor = float(backoff_factor)
        self.session = session if session is not None else requests.Session()
        self.sleep = sleep
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._default_headers = {"User-Agent": user_agent}
        self._last_request_at: float | None = None
        self._throttle_lock = threading.Lock()

    def get(
        self,
        url: str,
        *,
        params: Params = None,
        headers: Mapping[str, str] | None = None,
        timeout: Timeout | None = None,
        use_cache: bool = True,
        force_refresh: bool = False,
    ) -> HttpResponse:
        """Retrieve a URL, using a cached successful representation when valid."""

        return self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            use_cache=use_cache,
            force_refresh=force_refresh,
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Params = None,
        headers: Mapping[str, str] | None = None,
        timeout: Timeout | None = None,
        use_cache: bool = True,
        force_refresh: bool = False,
        **kwargs: Any,
    ) -> HttpResponse:
        """Issue an HTTP request and return its body with retrieval metadata."""

        normalized_method = method.upper()
        requested_url = self._prepare_url(normalized_method, url, params)
        cacheable = normalized_method == "GET" and use_cache and self.cache_dir is not None
        cache_path = self._cache_path(normalized_method, requested_url) if cacheable else None

        if cache_path is not None and not force_refresh:
            cached = self._read_cache(cache_path, requested_url)
            if cached is not None:
                return cached

        request_headers = {**self._default_headers, **dict(headers or {})}
        request_timeout = self.timeout if timeout is None else timeout
        last_exception: BaseException | None = None

        for attempt in range(1, self.max_retries + 2):
            self._throttle()
            try:
                raw_response = self.session.request(
                    normalized_method,
                    url,
                    params=params,
                    headers=request_headers,
                    timeout=request_timeout,
                    **kwargs,
                )
            except requests.RequestException as exc:
                last_exception = exc
                if attempt > self.max_retries:
                    raise HttpClientError(requested_url, attempt, exc) from exc
                self.sleep(self._backoff_delay(attempt))
                continue

            status_code = int(raw_response.status_code)
            final_url = str(getattr(raw_response, "url", "") or requested_url)
            metadata = RetrievalMetadata(
                requested_url=requested_url,
                url=final_url,
                retrieved_at=utc_now_iso(),
                status_code=status_code,
                cache_hit=False,
                attempts=attempt,
            )
            response = HttpResponse(
                status_code=status_code,
                text=str(raw_response.text),
                headers={str(key): str(value) for key, value in raw_response.headers.items()},
                metadata=metadata,
            )

            if status_code in RETRYABLE_STATUS_CODES and attempt <= self.max_retries:
                retry_after = self._retry_after_seconds(response.headers)
                self.sleep(max(self._backoff_delay(attempt), retry_after))
                continue

            if cache_path is not None and response.ok:
                self._write_cache(cache_path, response)
            return response

        # The loop always returns or raises. This guard makes that invariant explicit.
        assert last_exception is not None  # pragma: no cover
        raise HttpClientError(  # pragma: no cover
            requested_url,
            self.max_retries + 1,
            last_exception,
        )

    @staticmethod
    def _prepare_url(method: str, url: str, params: Params) -> str:
        stable_params: Params
        if isinstance(params, Mapping):
            stable_params = sorted(params.items(), key=lambda item: item[0])
        else:
            stable_params = params
        prepared = requests.Request(method=method, url=url, params=stable_params).prepare()
        return str(prepared.url or url)

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        with self._throttle_lock:
            now = self._monotonic()
            if self._last_request_at is None:
                self._last_request_at = now
                return
            earliest = self._last_request_at + self.min_interval
            if now < earliest:
                self.sleep(earliest - now)
                # Deterministic fake sleepers may not advance their paired clock.
                now = max(self._monotonic(), earliest)
            self._last_request_at = now

    def _backoff_delay(self, attempt: int) -> float:
        return self.backoff_factor * (2 ** (attempt - 1))

    @staticmethod
    def _retry_after_seconds(headers: Mapping[str, str]) -> float:
        raw = next(
            (value for key, value in headers.items() if key.casefold() == "retry-after"),
            "",
        ).strip()
        if not raw:
            return 0.0
        try:
            return max(0.0, float(raw))
        except ValueError:
            try:
                when = parsedate_to_datetime(raw)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
                return max(0.0, (when - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return 0.0

    def _cache_path(self, method: str, requested_url: str) -> Path:
        assert self.cache_dir is not None
        digest = hashlib.sha256(f"{method}\n{requested_url}".encode()).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, path: Path, requested_url: str) -> HttpResponse | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload["format_version"] != CACHE_FORMAT_VERSION:
                return None
            age = self._wall_clock() - float(payload["stored_at"])
            if self.cache_ttl is not None and age > self.cache_ttl:
                return None
            status_code = int(payload["status_code"])
            final_url = str(payload["url"])
            return HttpResponse(
                status_code=status_code,
                text=str(payload["text"]),
                headers={str(key): str(value) for key, value in payload["headers"].items()},
                metadata=RetrievalMetadata(
                    requested_url=requested_url,
                    url=final_url,
                    retrieved_at=str(payload["retrieved_at"]),
                    status_code=status_code,
                    cache_hit=True,
                    attempts=0,
                ),
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _write_cache(self, path: Path, response: HttpResponse) -> None:
        payload = {
            "format_version": CACHE_FORMAT_VERSION,
            "stored_at": self._wall_clock(),
            "status_code": response.status_code,
            "url": response.url,
            "retrieved_at": response.metadata.retrieved_at,
            "headers": dict(response.headers),
            "text": response.text,
        }
        temporary: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=f".{path.stem}-",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                temporary = Path(handle.name)
            os.replace(temporary, path)
            temporary = None
        except OSError:
            # A read-only or full cache directory must not break data retrieval.
            return
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


# A shorter alias is convenient for callers that do not care about implementation details.
PoliteHttpClient = CachedHttpClient

__all__ = [
    "CachedHttpClient",
    "HttpClientError",
    "HttpResponse",
    "PoliteHttpClient",
    "RetrievalMetadata",
]
