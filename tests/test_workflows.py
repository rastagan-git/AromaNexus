from pathlib import Path

import pandas as pd
import pytest

from aromanexus.excel_io import read_table
from aromanexus.models import LookupResult
from aromanexus.workflows import _apply_pubchem_resolution, run_nist_ri, run_pubchem


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


def test_local_lookup_failure_has_no_retrieval_timestamp():
    result = LookupResult.failure("PubChem", status="skipped", message="local rule")

    assert result.retrieved_at == ""


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
    assert pd.isna(output.loc[0, "PubChem Retrieved At"])
    assert output.loc[0, "PubChem CAS Resolution"] == "skipped"
    assert output.loc[0, "PubChem CAS Candidate Count"] == 0
    assert pd.isna(output.loc[0, "Resolved CAS"])
    assert output.loc[1, "Resolved CAS"] == "110-54-3"
    assert pd.notna(output.loc[1, "PubChem Retrieved At"])


def test_pubchem_no_odor_omits_optional_output_columns(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    destination = tmp_path / "pubchem.xlsx"
    pd.DataFrame({"Name": ["benzaldehyde"]}).to_excel(source, index=False)
    client = ScriptedPubChem(
        {
            "benzaldehyde": LookupResult(
                provider="PubChem",
                values={
                    "cid": 240,
                    "odor": ["almond"],
                    "odor_annotations": [{"text": "almond"}],
                    "odor_sources": ["Example"],
                    "odor_source_urls": ["https://example.test/source"],
                    "odor_license_urls": ["https://example.test/license"],
                },
            )
        }
    )

    run_pubchem(
        source,
        client,
        output_path=destination,
        identifier_column="Name",
        include_odor=False,
        checkpoint_every=0,
        progress=_silent,
    )

    output = read_table(destination)
    assert client.calls == [("benzaldehyde", False)]
    assert output.loc[0, "PubChem CID"] == 240
    assert not {
        "PubChem Odor",
        "PubChem Odor Annotations",
        "PubChem Odor Sources",
        "PubChem Odor Source URLs",
        "PubChem Odor License URLs",
    }.intersection(output.columns)


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


def test_pubchem_existing_cas_is_a_conservative_confirmation_signal(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    destination = tmp_path / "pubchem.xlsx"
    identifiers = [
        "Confirmed",
        "Conflict",
        "Invalid",
        "Blank unique",
        "Blank multiple",
        "100-52-7",
    ]
    pd.DataFrame(
        {
            "Name": identifiers,
            "Existing CAS": ["100527", "110-54-3", "100-52-8", None, "   ", "64-17-5"],
        }
    ).to_excel(source, index=False)
    client = ScriptedPubChem(
        {
            "Confirmed": LookupResult(
                provider="PubChem",
                values={"cas_numbers": ["64-17-5", "100-52-7"]},
            ),
            "Conflict": LookupResult(
                provider="PubChem",
                values={"cas_numbers": ["66-25-1"]},
            ),
            "Invalid": LookupResult(
                provider="PubChem",
                values={"cas_numbers": ["67-64-1"]},
            ),
            "Blank unique": LookupResult(
                provider="PubChem",
                values={"cas_numbers": ["64-17-5"]},
            ),
            "Blank multiple": LookupResult(
                provider="PubChem",
                values={"cas_numbers": ["64-17-5", "67-64-1"]},
            ),
            "100-52-7": LookupResult(
                provider="PubChem",
                values={"cas_numbers": ["100-52-7", "64-17-5"]},
            ),
        }
    )

    run_pubchem(
        source,
        client,
        output_path=destination,
        identifier_column="Name",
        existing_cas_column="Existing CAS",
        checkpoint_every=0,
        progress=_silent,
    )

    output = read_table(destination)
    assert output["PubChem CAS Resolution"].tolist() == [
        "input_cas_confirmed",
        "input_cas_conflict",
        "input_cas_invalid",
        "unique",
        "multiple",
        "query_confirmed",
    ]
    assert output["PubChem CAS Candidate Count"].tolist() == [2, 1, 1, 1, 2, 2]
    assert output.loc[0, "Resolved CAS"] == "100-52-7"
    assert pd.isna(output.loc[1, "Resolved CAS"])
    assert pd.isna(output.loc[2, "Resolved CAS"])
    assert output.loc[3, "Resolved CAS"] == "64-17-5"
    assert pd.isna(output.loc[4, "Resolved CAS"])
    assert output.loc[5, "Resolved CAS"] == "100-52-7"
    assert output.loc[0, "PubChem CAS Numbers"] == "64-17-5; 100-52-7"


def test_pubchem_partial_results_only_use_positive_cas_confirmation(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    destination = tmp_path / "pubchem.xlsx"
    pd.DataFrame(
        {
            "Name": ["Confirmed", "Incomplete candidates"],
            "Existing CAS": ["100-52-7", "110-54-3"],
        }
    ).to_excel(source, index=False)
    client = ScriptedPubChem(
        {
            "Confirmed": LookupResult(
                provider="PubChem",
                values={"cas_numbers": ["64-17-5", "100-52-7"]},
                status="partial",
                message="Odor annotations unavailable",
            ),
            "Incomplete candidates": LookupResult(
                provider="PubChem",
                values={"cas_numbers": ["64-17-5"]},
                status="partial",
                message="CAS identifiers unavailable",
            ),
        }
    )

    run_pubchem(
        source,
        client,
        output_path=destination,
        identifier_column="Name",
        existing_cas_column="Existing CAS",
        checkpoint_every=0,
        progress=_silent,
    )

    output = read_table(destination)
    assert output["PubChem CAS Resolution"].tolist() == [
        "input_cas_confirmed",
        "not_evaluated",
    ]
    assert output.loc[0, "Resolved CAS"] == "100-52-7"
    assert pd.isna(output.loc[1, "Resolved CAS"])


def test_pubchem_resolution_treats_pd_na_existing_cas_as_blank():
    frame = pd.DataFrame({"Name": ["benzaldehyde"]})
    result = LookupResult(
        provider="PubChem",
        values={"cas_numbers": ["100-52-7"]},
    )

    _apply_pubchem_resolution(
        frame,
        0,
        "benzaldehyde",
        result,
        resolved_cas_column="Resolved CAS",
        existing_cas=pd.NA,
    )

    assert frame.loc[0, "PubChem CAS Resolution"] == "unique"
    assert frame.loc[0, "Resolved CAS"] == "100-52-7"


def test_missing_existing_cas_column_fails_before_provider_calls(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    destination = tmp_path / "pubchem.xlsx"
    pd.DataFrame({"Name": ["benzaldehyde"]}).to_excel(source, index=False)
    client = ScriptedPubChem({})

    with pytest.raises(ValueError, match="Existing CAS"):
        run_pubchem(
            source,
            client,
            output_path=destination,
            identifier_column="Name",
            existing_cas_column="Existing CAS",
            checkpoint_every=0,
            progress=_silent,
        )

    assert client.calls == []
    assert not destination.exists()


def test_existing_cas_column_cannot_overlap_active_output(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    destination = tmp_path / "pubchem.xlsx"
    pd.DataFrame({"Name": ["benzaldehyde"], "Existing CAS": ["100-52-7"]}).to_excel(
        source, index=False
    )
    client = ScriptedPubChem({})

    with pytest.raises(ValueError, match="conflicts with an active PubChem output column"):
        run_pubchem(
            source,
            client,
            output_path=destination,
            identifier_column="Name",
            existing_cas_column="Existing CAS",
            resolved_cas_column="Existing CAS",
            checkpoint_every=0,
            progress=_silent,
        )

    assert client.calls == []
    assert not destination.exists()
    assert read_table(source).loc[0, "Existing CAS"] == "100-52-7"


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
