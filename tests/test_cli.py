import pandas as pd

from aromanexus.cli import main


def test_sources_command_lists_access_modes(capsys):
    assert main(["sources"]) == 0
    output = capsys.readouterr().out
    assert "PubChem" in output
    assert "ChemicalBook" in output
    assert "disabled" in output


def test_missing_input_returns_user_error(capsys, tmp_path):
    code = main(["pubchem", str(tmp_path / "missing.xlsx")])
    assert code == 2
    assert "does not exist" in capsys.readouterr().err


def test_pubchem_cli_forwards_resolution_skip_and_odor_options(monkeypatch, tmp_path):
    input_path = tmp_path / "input.csv"
    input_path.write_text("Name\nC6\n", encoding="utf-8")
    captured = {}

    monkeypatch.setattr("aromanexus.sources.pubchem.PubChemClient", lambda **_kwargs: object())

    def fake_run_pubchem(input_file, client, **kwargs):
        captured["input"] = input_file
        captured["client"] = client
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr("aromanexus.cli.run_pubchem", fake_run_pubchem)

    code = main(
        [
            "pubchem",
            str(input_path),
            "--identifier-column",
            "Name",
            "--skip-pattern",
            r"^C\d+$",
            "--skip-pattern",
            "^Total$",
            "--resolved-cas-column",
            "Curated CAS",
            "--existing-cas-column",
            "Existing CAS",
            "--no-odor",
            "--sheet",
            "Data",
        ]
    )

    assert code == 0
    assert captured["input"] == input_path
    assert captured["kwargs"]["skip_patterns"] == [r"^C\d+$", "^Total$"]
    assert captured["kwargs"]["resolved_cas_column"] == "Curated CAS"
    assert captured["kwargs"]["existing_cas_column"] == "Existing CAS"
    assert captured["kwargs"]["include_odor"] is False
    assert captured["kwargs"]["sheet_name"] == "Data"


def test_mffi_preflight_runs_before_browser_construction(monkeypatch, tmp_path):
    input_path = tmp_path / "input.xlsx"
    pd.DataFrame({"CAS Number": ["100-52-7"]}).to_excel(input_path, index=False)
    state = {"constructed": 0}

    class BrowserMustNotStart:
        def __init__(self, **_kwargs):
            state["constructed"] += 1
            raise AssertionError("MFFI browser started before workbook preflight")

    monkeypatch.setattr("aromanexus.cli.MffiClient", BrowserMustNotStart)

    code = main(["mffi", str(input_path), "--sheet", "Missing"])

    assert code == 2
    assert state["constructed"] == 0


def test_chemicalbook_preflight_runs_before_permission_prompt(monkeypatch, tmp_path):
    input_path = tmp_path / "input.xlsx"
    pd.DataFrame({"CAS Number": ["100-52-7"]}).to_excel(input_path, index=False)
    state = {"prompted": 0}

    def permission_must_not_be_requested(_args):
        state["prompted"] += 1
        raise AssertionError("Permission prompt ran before workbook preflight")

    monkeypatch.setattr(
        "aromanexus.cli._confirm_chemicalbook_permission",
        permission_must_not_be_requested,
    )

    code = main(["chemicalbook-legacy", str(input_path), "--sheet", "Missing"])

    assert code == 2
    assert state["prompted"] == 0
