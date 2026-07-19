from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import requests

from aromanexus.http import CachedHttpClient, HttpClientError


@dataclass
class FakeRawResponse:
    status_code: int = 200
    text: str = "{}"
    headers: dict[str, str] = field(default_factory=dict)
    url: str = "https://example.test/data"


class QueueSession:
    def __init__(self, *outcomes: FakeRawResponse | BaseException) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeRawResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return 1_000 + self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_successful_get_is_reused_from_disk_cache(tmp_path: Any) -> None:
    first_session = QueueSession(
        FakeRawResponse(text='{"answer": 42}', headers={"Content-Type": "application/json"})
    )
    clock = FakeClock()
    first_client = CachedHttpClient(
        cache_dir=tmp_path,
        session=first_session,
        wall_clock=clock.time,
    )

    first = first_client.get(
        "https://example.test/data",
        params={"z": "last", "a": "first"},
    )
    assert first.json() == {"answer": 42}
    assert first.metadata.cache_hit is False
    assert first.metadata.attempts == 1
    assert len(first_session.calls) == 1

    second_session = QueueSession()
    second_client = CachedHttpClient(
        cache_dir=tmp_path,
        session=second_session,
        wall_clock=clock.time,
    )
    second = second_client.get(
        "https://example.test/data",
        params={"a": "first", "z": "last"},
    )

    assert second.json() == {"answer": 42}
    assert second.metadata.cache_hit is True
    assert second.metadata.attempts == 0
    assert second.metadata.retrieved_at == first.metadata.retrieved_at
    assert second_session.calls == []


def test_stale_cache_is_refreshed(tmp_path: Any) -> None:
    clock = FakeClock()
    first_session = QueueSession(FakeRawResponse(text="old"))
    first_client = CachedHttpClient(
        cache_dir=tmp_path,
        cache_ttl=10,
        session=first_session,
        wall_clock=clock.time,
    )
    first_client.get("https://example.test/data")
    clock.now = 11

    second_session = QueueSession(FakeRawResponse(text="new"))
    second_client = CachedHttpClient(
        cache_dir=tmp_path,
        cache_ttl=10,
        session=second_session,
        wall_clock=clock.time,
    )
    refreshed = second_client.get("https://example.test/data")

    assert refreshed.text == "new"
    assert refreshed.metadata.cache_hit is False
    assert len(second_session.calls) == 1


def test_rate_limit_and_retry_after_are_applied_without_network(tmp_path: Any) -> None:
    clock = FakeClock()
    session = QueueSession(
        FakeRawResponse(status_code=429, headers={"Retry-After": "1.5"}),
        FakeRawResponse(status_code=200, text="ok"),
        FakeRawResponse(status_code=200, text="second", url="https://example.test/other"),
    )
    client = CachedHttpClient(
        cache_dir=tmp_path,
        min_interval=0.25,
        max_retries=1,
        backoff_factor=0.1,
        session=session,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        wall_clock=clock.time,
    )

    response = client.get("https://example.test/data")
    client.get("https://example.test/other")

    assert response.text == "ok"
    assert response.metadata.attempts == 2
    assert clock.sleeps == pytest.approx([1.5, 0.25])
    assert len(session.calls) == 3


def test_timeout_and_headers_are_forwarded(tmp_path: Any) -> None:
    session = QueueSession(FakeRawResponse())
    client = CachedHttpClient(cache_dir=tmp_path, timeout=(2.0, 7.0), session=session)

    client.get("https://example.test/data", headers={"Accept": "application/json"})

    call = session.calls[0]
    assert call["timeout"] == (2.0, 7.0)
    assert call["headers"]["Accept"] == "application/json"
    assert call["headers"]["User-Agent"].startswith("AromaNexus/")


def test_request_exception_retries_then_raises_descriptive_error(tmp_path: Any) -> None:
    clock = FakeClock()
    session = QueueSession(
        requests.ConnectionError("offline"),
        requests.Timeout("still offline"),
    )
    client = CachedHttpClient(
        cache_dir=tmp_path,
        max_retries=1,
        backoff_factor=0.5,
        session=session,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    with pytest.raises(HttpClientError, match="2 attempt") as exc_info:
        client.get("https://example.test/data")

    assert exc_info.value.attempts == 2
    assert clock.sleeps == [0.5]
    assert len(session.calls) == 2


def test_non_retryable_http_error_is_returned_once(tmp_path: Any) -> None:
    session = QueueSession(FakeRawResponse(status_code=404, text="missing"))
    client = CachedHttpClient(cache_dir=tmp_path, max_retries=3, session=session)

    response = client.get("https://example.test/data")

    assert response.status_code == 404
    assert response.ok is False
    assert len(session.calls) == 1
    assert not list(tmp_path.glob("*.json"))
