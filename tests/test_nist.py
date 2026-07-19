from __future__ import annotations

from typing import Any

from aromanexus.http import HttpResponse, RetrievalMetadata
from aromanexus.sources.nist import (
    NistWebBookClient,
    is_nist_search_results,
    parse_nist_cas,
    parse_retention_indices,
)

RI_HTML = """
<html><head><title>Benzaldehyde</title></head><body>
  <table aria-label="Different table">
    <tr><th>I</th></tr><tr><td>9999</td></tr>
  </table>
  <table aria-label="Normal alkane RI, non-polar column, custom temperature program">
    <tr><th>Column</th><th>I</th><th>Reference</th></tr>
    <tr><td>DB-1</td><td>1,100</td><td>A</td></tr>
    <tr><td>DB-5</td><td>1200.5 &plusmn; 2</td><td>B</td></tr>
    <tr><td>DB-5</td><td>not reported</td><td>C</td></tr>
  </table>
</body></html>
"""

NAME_HTML = """
<html><head><title>Benzaldehyde</title></head><body>
  <ul><li><strong>CAS Registry Number:</strong> 100-52-7</li></ul>
</body></html>
"""


def response(
    text: str,
    *,
    status: int = 200,
    cache_hit: bool = False,
    url: str = "https://webbook.nist.gov/cgi/cbook.cgi?example=1",
) -> HttpResponse:
    return HttpResponse(
        status_code=status,
        text=text,
        headers={},
        metadata=RetrievalMetadata(
            requested_url=url,
            url=url,
            retrieved_at="2026-07-19T00:00:00+00:00",
            status_code=status,
            cache_hit=cache_hit,
            attempts=0 if cache_hit else 1,
        ),
    )


class FakeHttp:
    def __init__(self, *responses: HttpResponse) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> HttpResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def test_parse_retention_indices_only_uses_original_target_table() -> None:
    assert parse_retention_indices(RI_HTML) == [1100.0, 1200.5]


def test_parse_retention_indices_falls_back_from_heading_to_next_table() -> None:
    html = """
    <h3>Normal alkane RI, non-polar column, custom temperature program</h3>
    <table><tr><th>Temperature</th><th>I</th></tr><tr><td>ramp</td><td>876</td></tr></table>
    """
    assert parse_retention_indices(html) == [876.0]


def test_name_page_helpers_distinguish_detail_and_search_results() -> None:
    assert parse_nist_cas(NAME_HTML) == "100-52-7"
    assert is_nist_search_results(NAME_HTML) is False
    assert is_nist_search_results("<title>Search Results</title>") is True


def test_lookup_ri_selects_nearest_value_and_returns_provenance() -> None:
    fake_http = FakeHttp(response(RI_HTML, cache_hit=True))
    client = NistWebBookClient(http_client=fake_http)

    result = client.lookup_ri("100527", 1180)

    assert result.status == "ok"
    assert result.values["cas"] == "100-52-7"
    assert result.values["retention_index"] == 1200.5
    assert result.values["retention_indices"] == [1100, 1200.5]
    assert result.cache_hit is True
    assert result.version == "SRD 69"
    assert result.source_url.startswith("https://webbook.nist.gov/")
    params = fake_http.calls[0]["params"]
    assert params == {"ID": "C100527", "Units": "SI", "Mask": "2000"}


def test_lookup_ri_rejects_bad_inputs_without_http() -> None:
    fake_http = FakeHttp()
    client = NistWebBookClient(http_client=fake_http)

    bad_cas = client.lookup_ri("123-45-6", 1000)
    bad_ri = client.lookup_ri("100-52-7", "not a number")

    assert bad_cas.status == "invalid_input"
    assert bad_ri.status == "invalid_input"
    assert fake_http.calls == []


def test_resolve_name_returns_cas_and_query() -> None:
    fake_http = FakeHttp(response(NAME_HTML))
    client = NistWebBookClient(http_client=fake_http)

    result = client.resolve_name("  Benzaldehyde  ")

    assert result.status == "ok"
    assert result.values == {"query_name": "Benzaldehyde", "cas": "100-52-7"}
    assert fake_http.calls[0]["params"] == {"Name": "Benzaldehyde", "Units": "SI"}


def test_resolve_name_reports_ambiguous_and_missing_pages() -> None:
    fake_http = FakeHttp(
        response("<html><title>Search Results</title><body>matches</body></html>"),
        response("<html><title>Name Not Found</title><body>Name Not Found</body></html>"),
    )
    client = NistWebBookClient(http_client=fake_http)

    ambiguous = client.resolve_name("oil")
    missing = client.resolve_name("definitely-not-a-compound")

    assert ambiguous.status == "ambiguous"
    assert missing.status == "not_found"


def test_nist_default_request_interval_is_at_least_five_seconds(tmp_path: Any) -> None:
    client = NistWebBookClient(cache_dir=tmp_path)
    assert client.http.min_interval >= 5.0
