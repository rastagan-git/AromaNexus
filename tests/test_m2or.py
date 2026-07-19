from __future__ import annotations

from pathlib import Path

from aromanexus.sources.m2or import (
    M2OR_FILENAME,
    M2OR_LICENSE_URL,
    M2OR_VERSION,
    M2ORClient,
)

FIXTURE = Path(__file__).parent / "fixtures" / "M2OR.synthetic.csv"


def test_lookup_cas_aggregates_distinct_pairs_from_semicolon_csv() -> None:
    client = M2ORClient(data_path=FIXTURE, allow_download=False)

    result = client.lookup_cas("64175")

    assert result.status == "ok"
    assert result.cache_hit is True
    assert result.version == M2OR_VERSION
    assert result.license_url == M2OR_LICENSE_URL
    assert result.values == {
        "M2OR Pair Count": 4,
        "M2OR Responsive Count": 3,
        "M2OR Species": "homo sapiens; Mus musculus",
        "M2OR Human Responsive Receptors": "OR1A1; OR2W1",
        "M2OR DOIs": "10.1000/a; 10.1000/b; 10.1000/c; 10.1000/d",
    }


def test_lookup_cas_downloads_to_versioned_cache_then_runs_offline(tmp_path: Path) -> None:
    payload = FIXTURE.read_bytes()
    downloads: list[str] = []

    def downloader(url: str, _destination: Path) -> bytes:
        downloads.append(url)
        return payload

    first = M2ORClient(cache_dir=tmp_path, downloader=downloader).lookup_cas("64-17-5")
    assert first.status == "ok"
    assert first.cache_hit is False
    assert len(downloads) == 1
    cached_file = tmp_path / "m2or" / M2OR_VERSION / M2OR_FILENAME
    assert cached_file.read_bytes() == payload

    second = M2ORClient(cache_dir=tmp_path, allow_download=False).lookup_cas("64-17-5")
    assert second.status == "ok"
    assert second.cache_hit is True
    assert len(downloads) == 1


def test_lookup_cas_supports_injected_rows_and_exact_matching() -> None:
    rows = [
        {
            "id": "a",
            "CAS": "64-17-5",
            "species": "homo sapiens",
            "Gene ID": "OR1A1",
            "Responsive": "1",
            "DOI": "https://doi.org/10.1000/example",
        },
        {
            "id": "b",
            "CAS": "164-17-5",
            "species": "homo sapiens",
            "Gene ID": "SHOULD_NOT_MATCH",
            "Responsive": "1",
        },
    ]

    result = M2ORClient(rows=rows, allow_download=False).lookup_cas("64-17-5")

    assert result.status == "ok"
    assert result.values["M2OR Pair Count"] == 1
    assert result.values["M2OR Human Responsive Receptors"] == "OR1A1"


def test_lookup_cas_reports_invalid_missing_and_not_found(tmp_path: Path) -> None:
    missing = M2ORClient(cache_dir=tmp_path, allow_download=False)
    assert missing.lookup_cas("64-17-5").status == "missing_data"

    client = M2ORClient(data_path=FIXTURE, allow_download=False)
    assert client.lookup_cas("not-cas").status == "invalid_input"
    not_found = client.lookup_cas("50-00-0")
    assert not_found.status == "not_found"
    assert not_found.values["M2OR Pair Count"] == 0
