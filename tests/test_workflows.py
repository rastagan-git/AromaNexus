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


def test_existing_output_is_rejected_before_provider_calls(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    destination = tmp_path / "output.xlsx"
    pd.DataFrame({"CAS Number": ["100-52-7"], "Calculated RI": [955]}).to_excel(source, index=False)
    destination.write_bytes(b"occupied")
    client = FakeNist()
    with pytest.raises(FileExistsError):
        run_nist_ri(source, client, output_path=destination, progress=_silent)
    assert client.calls == 0
