from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from aromanexus import excel_io


def _create_small_workbook(path: Path) -> None:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Data"
    worksheet.append(["Name", "Original value"])
    worksheet.append(["alpha", 1])
    worksheet.append(["beta", 2])
    workbook.save(path)
    workbook.close()


def test_preserved_writer_uses_one_array_snapshot_without_dataframe_iat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.xlsx"
    destination = tmp_path / "output.xlsx"
    _create_small_workbook(source)
    frame, context = excel_io.read_table_with_context(source, sheet_name="Data")
    frame["Enriched value"] = pd.Series(
        ["first result", "second result"],
        index=frame.index,
        dtype=object,
    )
    for index in frame.index:
        excel_io.record_touched_cell(frame, index, "Enriched value")

    original_to_numpy = pd.DataFrame.to_numpy
    array_snapshots = 0

    def tracking_to_numpy(self, *args, **kwargs):
        nonlocal array_snapshots
        array_snapshots += 1
        return original_to_numpy(self, *args, **kwargs)

    def reject_iat(_frame):
        raise AssertionError("Preserved XLSX writes must not perform per-cell DataFrame.iat access")

    monkeypatch.setattr(pd.DataFrame, "to_numpy", tracking_to_numpy)
    monkeypatch.setattr(pd.DataFrame, "iat", property(reject_iat))

    excel_io.write_table(frame, destination, context=context)

    assert array_snapshots == 1
    workbook = openpyxl.load_workbook(destination, data_only=False)
    try:
        worksheet = workbook["Data"]
        assert worksheet["C2"].value == "first result"
        assert worksheet["C3"].value == "second result"
    finally:
        workbook.close()


def _cached_layout_context(tmp_path: Path) -> excel_io.TableContext:
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"layout validator is monkeypatched in this test")
    return excel_io.TableContext(
        source_path=source,
        sheet_name="Data",
        original_columns=("Name",),
        row_count=1,
        template_bytes=b"not parsed because preservation is prevalidated",
        preservation_validated=True,
    )


def test_layout_validation_cache_is_monotonic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _cached_layout_context(tmp_path)
    calls: list[int] = []

    def record_validation(_context, *, minimum_new_columns: int) -> None:
        calls.append(minimum_new_columns)

    monkeypatch.setattr(excel_io, "_validate_target_sheet_layout", record_validation)
    destination = tmp_path / "output.xlsx"

    for minimum_new_columns in (5, 0, 5, 3, 8, 7, 8):
        excel_io.validate_table_output(
            context,
            destination,
            minimum_new_columns=minimum_new_columns,
        )

    assert calls == [5, 8]
    assert context.layout_validated_new_columns == 8


def test_failed_layout_validation_is_not_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _cached_layout_context(tmp_path)
    calls: list[int] = []

    def fail_validation(_context, *, minimum_new_columns: int) -> None:
        calls.append(minimum_new_columns)
        raise ValueError("simulated layout failure")

    monkeypatch.setattr(excel_io, "_validate_target_sheet_layout", fail_validation)

    for destination in (tmp_path / "first.xlsx", tmp_path / "second.xlsx"):
        with pytest.raises(ValueError, match="simulated layout failure"):
            excel_io.validate_table_output(
                context,
                destination,
                minimum_new_columns=4,
            )

    assert calls == [4, 4]
    assert context.layout_validated_new_columns == -1
