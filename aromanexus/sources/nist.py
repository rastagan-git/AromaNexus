"""NIST Chemistry WebBook retention-index and identifier adapter."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from aromanexus.http import (
    DEFAULT_CACHE_DIR,
    CachedHttpClient,
    HttpClientError,
    HttpResponse,
)
from aromanexus.identifiers import clean_text, is_valid_cas, normalize_cas
from aromanexus.models import LookupResult

NIST_CBOOK_URL = "https://webbook.nist.gov/cgi/cbook.cgi"
NIST_LICENSE_URL = "https://www.nist.gov/srd/public-law"
NIST_VERSION = "SRD 69"
TARGET_RI_TABLE_TITLE = "Normal alkane RI, non-polar column, custom temperature program"
CAS_TEXT_PATTERN = re.compile(r"CAS\s+Registry\s+Number\s*:\s*(\d{2,7}-\d{2}-\d)", re.I)
NUMBER_PATTERN = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _target_ri_table(soup: BeautifulSoup, target_title: str) -> Tag | None:
    normalized_title = _normalized_text(target_title).casefold()
    for table in soup.find_all("table"):
        aria_label = _normalized_text(str(table.get("aria-label", ""))).casefold()
        if aria_label == normalized_title:
            return table

    for text_node in soup.find_all(string=True):
        if normalized_title in _normalized_text(str(text_node)).casefold():
            table = text_node.find_next("table")
            if isinstance(table, Tag):
                return table
    return None


def _first_number(text: str) -> float | None:
    match = NUMBER_PATTERN.search(text.replace("\u2212", "-"))
    if match is None:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_retention_indices(
    html: str,
    *,
    target_title: str = TARGET_RI_TABLE_TITLE,
) -> list[float]:
    """Extract the ``I`` column from the original crawler's target RI table."""

    soup = BeautifulSoup(html, "html.parser")
    table = _target_ri_table(soup, target_title)
    if table is None:
        return []

    rows = table.find_all("tr")
    header_index: int | None = None
    ri_column: int | None = None
    for row_index, row in enumerate(rows):
        labels = [
            _normalized_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])
        ]
        for column_index, label in enumerate(labels):
            if label == "I":
                header_index = row_index
                ri_column = column_index
                break
        if ri_column is not None:
            break

    if header_index is None or ri_column is None:
        return []

    values: list[float] = []
    for row in rows[header_index + 1 :]:
        cells = row.find_all(["td", "th"])
        if len(cells) <= ri_column:
            continue
        value = _first_number(cells[ri_column].get_text(" ", strip=True))
        if value is not None:
            values.append(value)
    return values


def parse_nist_cas(html: str) -> str | None:
    """Extract a hyphenated CAS Registry Number from a NIST detail page."""

    soup = BeautifulSoup(html, "html.parser")
    for label in soup.find_all("strong"):
        if "cas registry number" not in label.get_text(" ", strip=True).casefold():
            continue
        parent_text = label.parent.get_text(" ", strip=True) if label.parent else ""
        match = CAS_TEXT_PATTERN.search(parent_text)
        if match:
            return match.group(1)
        sibling_text = " ".join(str(sibling) for sibling in label.next_siblings)
        match = re.search(r"\d{2,7}-\d{2}-\d", sibling_text)
        if match:
            return match.group(0)

    match = CAS_TEXT_PATTERN.search(soup.get_text(" ", strip=True))
    return match.group(1) if match else None


def is_nist_search_results(html: str) -> bool:
    """Return whether NIST responded with an ambiguous search-results page."""

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return "search results" in title.casefold()


class NistWebBookClient:
    """Polite client for the NIST Chemistry WebBook SRD 69."""

    provider = "NIST WebBook"

    def __init__(
        self,
        http_client: CachedHttpClient | Any | None = None,
        *,
        cache_dir: str | Path | None = DEFAULT_CACHE_DIR / "nist",
        min_interval: float = 5.0,
        timeout: float | tuple[float, float] = (5.0, 30.0),
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.http = http_client or CachedHttpClient(
            cache_dir=cache_dir,
            min_interval=min_interval,
            timeout=timeout,
            session=session,
            sleep=sleep,
        )

    def lookup_ri(self, cas: object, calculated_ri: object) -> LookupResult:
        """Find the NIST RI nearest to a caller-supplied calculated RI."""

        normalized_cas = normalize_cas(cas)
        if not normalized_cas or not is_valid_cas(normalized_cas):
            return self._failure(
                status="invalid_input",
                message=f"Invalid CAS Registry Number: {clean_text(cas) or '<empty>'}",
            )
        try:
            target = float(calculated_ri)
            if not math.isfinite(target):
                raise ValueError
        except (TypeError, ValueError):
            return self._failure(
                status="invalid_input",
                message=f"Calculated RI must be a finite number: {calculated_ri!r}",
            )

        try:
            response = self.http.get(
                NIST_CBOOK_URL,
                params={
                    "ID": f"C{normalized_cas.replace('-', '')}",
                    "Units": "SI",
                    "Mask": "2000",
                },
            )
        except HttpClientError as exc:
            return self._failure(status="network_error", message=str(exc), source_url=exc.url)

        if response.status_code == 404:
            return self._response_failure(
                response,
                status="not_found",
                message=f"NIST has no retention-index page for {normalized_cas}.",
            )
        if not response.ok:
            return self._response_failure(
                response,
                status="http_error",
                message=f"NIST returned HTTP {response.status_code}.",
            )

        values = parse_retention_indices(response.text)
        if not values:
            return self._response_failure(
                response,
                status="not_found",
                message=(
                    f"Target NIST retention-index table was not available for {normalized_cas}."
                ),
            )

        closest = min(values, key=lambda value: abs(value - target))
        selected: int | float = int(closest) if closest.is_integer() else closest
        return LookupResult(
            provider=self.provider,
            values={
                "cas": normalized_cas,
                "calculated_ri": target,
                "retention_index": selected,
                "retention_indices": [
                    int(value) if value.is_integer() else value for value in values
                ],
            },
            source_url=response.url,
            retrieved_at=response.metadata.retrieved_at,
            cache_hit=response.metadata.cache_hit,
            version=NIST_VERSION,
            license_url=NIST_LICENSE_URL,
        )

    def resolve_name(self, name: object) -> LookupResult:
        """Resolve an unambiguous NIST compound-name page to its CAS number."""

        query = clean_text(name)
        if not query:
            return self._failure(status="invalid_input", message="Compound name is empty.")

        try:
            response = self.http.get(
                NIST_CBOOK_URL,
                params={"Name": query, "Units": "SI"},
            )
        except HttpClientError as exc:
            return self._failure(status="network_error", message=str(exc), source_url=exc.url)

        if response.status_code == 404 or "name not found" in response.text.casefold():
            return self._response_failure(
                response,
                status="not_found",
                message=f"NIST did not find a compound named {query!r}.",
            )
        if not response.ok:
            return self._response_failure(
                response,
                status="http_error",
                message=f"NIST returned HTTP {response.status_code}.",
            )
        if is_nist_search_results(response.text):
            return self._response_failure(
                response,
                status="ambiguous",
                message=f"NIST returned multiple search results for {query!r}.",
            )

        cas = parse_nist_cas(response.text)
        if cas is None:
            return self._response_failure(
                response,
                status="parse_error",
                message="NIST detail page did not contain a CAS Registry Number.",
            )
        return LookupResult(
            provider=self.provider,
            values={"query_name": query, "cas": cas},
            source_url=response.url,
            retrieved_at=response.metadata.retrieved_at,
            cache_hit=response.metadata.cache_hit,
            version=NIST_VERSION,
            license_url=NIST_LICENSE_URL,
        )

    def _response_failure(
        self,
        response: HttpResponse,
        *,
        status: str,
        message: str,
    ) -> LookupResult:
        return LookupResult(
            provider=self.provider,
            status=status,
            message=message,
            source_url=response.url,
            retrieved_at=response.metadata.retrieved_at,
            cache_hit=response.metadata.cache_hit,
            version=NIST_VERSION,
            license_url=NIST_LICENSE_URL,
        )

    def _failure(self, *, status: str, message: str, source_url: str = "") -> LookupResult:
        return LookupResult(
            provider=self.provider,
            status=status,
            message=message,
            source_url=source_url,
            version=NIST_VERSION,
            license_url=NIST_LICENSE_URL,
        )


NISTSource = NistWebBookClient

__all__ = [
    "NISTSource",
    "NistWebBookClient",
    "TARGET_RI_TABLE_TITLE",
    "is_nist_search_results",
    "parse_nist_cas",
    "parse_retention_indices",
]
