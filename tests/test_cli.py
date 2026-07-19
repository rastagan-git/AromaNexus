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


def test_pubchem_cli_forwards_repeatable_skip_patterns_and_resolved_column(monkeypatch, tmp_path):
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
        ]
    )

    assert code == 0
    assert captured["input"] == input_path
    assert captured["kwargs"]["skip_patterns"] == [r"^C\d+$", "^Total$"]
    assert captured["kwargs"]["resolved_cas_column"] == "Curated CAS"
