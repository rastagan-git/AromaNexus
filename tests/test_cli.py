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
