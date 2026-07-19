from pathlib import Path

import pandas as pd
import pytest

from aromanexus.excel_io import read_table
from aromanexus.models import LookupResult
from aromanexus.workflows import run_nist_ri, run_pubchem


class FakeNist:
    def __init__(self):
        self.calls = 0

    def lookup_ri(self, cas, calculated_ri):
        self.calls += 1
        if cas == "100-52-7":
            return LookupResult(
                provider="NIST",
                values={"retention_index": 955},
                source_url="https://example.test/nist/100-52-7",
            )
        return LookupResult.failure("NIST", status="not_found", message="missing")


class FakePubChem:
    def lookup(self, identifier, include_odor=True):
        return LookupResult(
            provider="PubChem",
            values={
                "cid": 240,
                "title": "Benzaldehyde",
                "inchikey": "HUMNYLRZRPPJDN-UHFFFAOYSA-N",
                "odor": ["=formula-like", "almond"],
                "odor_sources": ["Example contributor"],
            },
            source_url="https://pubchem.ncbi.nlm.nih.gov/compound/240",
            license_url="https://example.test/license",
        )


class ScriptedPubChem:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def lookup(self, identifier, include_odor=True):
        self.calls.append((identifier, include_odor))
        return self.results[identifier]


def _silent(*_):
    return None


def test_legacy_nist_contract_preserves_rows_and_columns(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    destination = tmp_path / "output.xlsx"
    pd.DataFrame(
        {"CAS Number": ["100-52-7", "62016-37-9"], "Calculated RI": [955.2, 962.3]}
    ).to_excel(source, index=False)

    summary = run_nist_ri(
        source,
        FakeNist(),
        output_path=destination,
        include_provenance=False,
        checkpoint_every=0,
        progress=_silent,
    )
    output = read_table(destination)
    assert summary.rows == 2
    assert list(output.columns) == ["CAS Number", "Calculated RI", "NIST RI"]
    assert output.loc[0, "NIST RI"] == 955
    assert output.loc[1, "NIST RI"] == "\\"


def test_pubchem_maps_fields_and_sanitizes_remote_text(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    destination = tmp_path / "pubchem.xlsx"
    pd.DataFrame({"CAS Number": ["100-52-7"]}).to_excel(source, index=False)
    summary = run_pubchem(
        source,
        FakePubChem(),
        output_path=destination,
        checkpoint_every=0,
        progress=_silent,
    )
    output = read_table(destination)
    assert summary.status_counts == {"ok": 1}
    assert output.loc[0, "PubChem CID"] == 240
    assert output.loc[0, "PubChem Odor"].startswith("'")
    assert output.loc[0, "PubChem Source URL"].endswith("/240")


def test_pubchem_skip_pattern_excludes_structural_rows_before_lookup(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    destination = tmp_path / "pubchem.xlsx"
    pd.DataFrame({"Name": ["C6", "n-Hexane"]}).to_excel(source, index=False)
    client = ScriptedPubChem(
        {
            "n-Hexane": LookupResult(
                provider="PubChem",
                values={"cid": 8058, "cas_numbers": ["110-54-3"]},
            )
        }
    )

    run_pubchem(
        source,
        client,
        output_path=destination,
        identifier_column="Name",
        skip_patterns=[r"^C\d+$"],
        resolved_cas_column="Resolved CAS",
        checkpoint_every=0,
        progress=_silent,
    )

    output = read_table(destination)
    assert client.calls == [("n-Hexane", True)]
    assert output.loc[0, "PubChem Status"] == "skipped"
    assert output.loc[0, "PubChem CAS Resolution"] == "skipped"
    assert output.loc[0, "PubChem CAS Candidate Count"] == 0
    assert pd.isna(output.loc[0, "Resolved CAS"])
    assert output.loc[1, "Resolved CAS"] == "110-54-3"


def test_pubchem_separates_lookup_status_from_cas_resolution(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    destination = tmp_path / "pubchem.xlsx"
    identifiers = [
        "100-52-7",
        "benzaldehyde",
        "n-Hexane",
        "Matched without CAS",
        "Unavailable",
    ]
    pd.DataFrame({"Name": identifiers}).to_excel(source, index=False)
    client = ScriptedPubChem(
        {
            "100-52-7": LookupResult(
                provider="PubChem",
                values={"cas_numbers": ["64-17-5", "100-52-7"]},
            ),
            "benzaldehyde": LookupResult(
                provider="PubChem",
                values={"cas_numbers": ["100-52-7"]},
            ),
            "n-Hexane": LookupResult(
                provider="PubChem",
                values={"cas_numbers": ["110-54-3", "64-17-5"]},
            ),
            "Matched without CAS": LookupResult(provider="PubChem", values={"cid": 999}),
            "Unavailable": LookupResult.failure(
                "PubChem", status="not_found", message="No matching record"
            ),
        }
    )

    run_pubchem(
        source,
        client,
        output_path=destination,
        identifier_column="Name",
        resolved_cas_column="Resolved CAS",
        checkpoint_every=0,
        progress=_silent,
    )

    output = read_table(destination)
    assert output["PubChem CAS Resolution"].tolist() == [
        "query_confirmed",
        "unique",
        "multiple",
        "missing",
        "not_evaluated",
    ]
    assert output["PubChem CAS Candidate Count"].tolist() == [2, 1, 2, 0, 0]
    assert output.loc[0, "Resolved CAS"] == "100-52-7"
    assert output.loc[1, "Resolved CAS"] == "100-52-7"
    assert pd.isna(output.loc[2, "Resolved CAS"])
    assert pd.isna(output.loc[3, "Resolved CAS"])
    assert pd.isna(output.loc[4, "Resolved CAS"])
    assert output.loc[2, "PubChem CAS Numbers"] == "110-54-3; 64-17-5"
    assert output.loc[4, "PubChem Status"] == "not_found"


def test_invalid_pubchem_skip_pattern_fails_before_provider_calls(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    destination = tmp_path / "pubchem.xlsx"
    pd.DataFrame({"Name": ["benzaldehyde"]}).to_excel(source, index=False)
    client = ScriptedPubChem({})

    with pytest.raises(ValueError):
        run_pubchem(
            source,
            client,
            output_path=destination,
            identifier_column="Name",
            skip_patterns=["["],
            checkpoint_every=0,
            progress=_silent,
        )

    assert client.calls == []
    assert not destination.exists()


def test_existing_output_is_rejected_before_provider_calls(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    destination = tmp_path / "output.xlsx"
    pd.DataFrame({"CAS Number": ["100-52-7"], "Calculated RI": [955]}).to_excel(source, index=False)
    destination.write_bytes(b"occupied")
    client = FakeNist()
    with pytest.raises(FileExistsError):
        run_nist_ri(source, client, output_path=destination, progress=_silent)
    assert client.calls == 0
