from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from aromanexus.excel_io import (
    read_table,
    require_columns,
    sanitize_excel_cell,
    write_table,
)


def test_sanitizes_formula_prefixes_without_touching_numbers():
    assert sanitize_excel_cell("=2+2") == "'=2+2"
    assert sanitize_excel_cell("@SUM(A1:A2)") == "'@SUM(A1:A2)"
    assert sanitize_excel_cell(42) == 42
    assert sanitize_excel_cell("benzaldehyde") == "benzaldehyde"


def test_xlsx_round_trip_is_formula_safe_and_atomic(tmp_path: Path):
    output = tmp_path / "safe.xlsx"
    frame = pd.DataFrame({"CAS Number": ["100-52-7"], "Remote Text": ["=2+2"]})
    write_table(frame, output)

    workbook = openpyxl.load_workbook(output, data_only=False)
    assert workbook.active["B2"].value == "'=2+2"
    loaded = read_table(output)
    assert loaded.loc[0, "CAS Number"] == "100-52-7"


def test_refuses_overwrite_and_reports_missing_columns(tmp_path: Path):
    output = tmp_path / "data.csv"
    frame = pd.DataFrame({"Name": ["Nonanal"]})
    write_table(frame, output)
    with pytest.raises(FileExistsError):
        write_table(frame, output)
    with pytest.raises(ValueError, match="CAS Number"):
        require_columns(frame, "Name", "CAS Number")
