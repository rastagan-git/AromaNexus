"""Safe tabular input and output helpers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

SUPPORTED_INPUTS = {".csv", ".tsv", ".xlsx"}
FORMULA_PREFIXES = ("=", "+", "-", "@")


def read_table(path: str | Path) -> pd.DataFrame:
    """Read a supported workbook or delimited text file."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Input file does not exist: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_INPUTS:
        supported = ", ".join(sorted(SUPPORTED_INPUTS))
        raise ValueError(f"Unsupported input type {suffix!r}; expected one of: {supported}")
    if suffix == ".xlsx":
        return pd.read_excel(source, dtype=object)
    separator = "\t" if suffix == ".tsv" else ","
    return pd.read_csv(source, sep=separator, dtype=object, keep_default_na=False)


def require_columns(frame: pd.DataFrame, *columns: str) -> None:
    """Raise once with every missing column name."""

    missing = [column for column in columns if column not in frame.columns]
    if missing:
        available = ", ".join(map(str, frame.columns))
        message = f"Missing required column(s): {', '.join(missing)}. Available: {available}"
        raise ValueError(message)


def derive_output_path(input_path: str | Path, suffix: str) -> Path:
    """Create a sibling output path without touching the source file."""

    source = Path(input_path)
    return source.with_name(f"{source.stem}{suffix}{source.suffix}")


def sanitize_excel_cell(value: Any) -> Any:
    """Prevent untrusted text from becoming an Excel formula."""

    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return f"'{value}"
    return value


def sanitize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy whose string cells are safe to open in spreadsheet software."""

    safe = frame.copy()
    for column in safe.columns:
        safe[column] = safe[column].map(sanitize_excel_cell)
    return safe


def write_table(frame: pd.DataFrame, path: str | Path, *, force: bool = False) -> Path:
    """Atomically write a table, refusing accidental overwrite by default."""

    destination = Path(path)
    suffix = destination.suffix.lower()
    if suffix not in SUPPORTED_INPUTS:
        supported = ", ".join(sorted(SUPPORTED_INPUTS))
        raise ValueError(f"Unsupported output type {suffix!r}; expected one of: {supported}")
    if destination.exists() and not force:
        raise FileExistsError(f"Output already exists: {destination}. Pass --force to replace it.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    safe = sanitize_frame(frame)
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{destination.stem}-",
        suffix=destination.suffix,
        dir=destination.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    handle.close()
    try:
        if suffix == ".xlsx":
            safe.to_excel(temporary, index=False)
        else:
            separator = "\t" if suffix == ".tsv" else ","
            safe.to_csv(temporary, sep=separator, index=False, encoding="utf-8-sig")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination
