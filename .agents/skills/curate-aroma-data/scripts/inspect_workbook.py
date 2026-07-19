"""Inspect an AromaNexus workbook without modifying it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aromanexus.excel_io import FORMULA_PREFIXES, read_table  # noqa: E402
from aromanexus.identifiers import is_valid_cas, normalize_cas  # noqa: E402


def inspect(path: Path, cas_column: str | None = None) -> dict[str, object]:
    frame = read_table(path)
    detected_cas = cas_column or next(
        (name for name in ("CAS Number", "CAS", "cas", "cas_number") if name in frame.columns),
        None,
    )
    formula_like = 0
    for column in frame.columns:
        formula_like += int(
            frame[column]
            .map(lambda value: isinstance(value, str) and value.startswith(FORMULA_PREFIXES))
            .sum()
        )
    report: dict[str, object] = {
        "path": str(path.resolve()),
        "rows": len(frame),
        "columns": [str(column) for column in frame.columns],
        "duplicate_rows": int(frame.duplicated().sum()),
        "formula_like_cells": formula_like,
        "missing_by_column": {
            str(column): int(frame[column].isna().sum() + frame[column].eq("").sum())
            for column in frame.columns
        },
    }
    if detected_cas:
        normalized = frame[detected_cas].map(normalize_cas)
        valid_mask = normalized.map(is_valid_cas)
        nonempty_mask = normalized.ne("")
        invalid = normalized[nonempty_mask & ~valid_mask]
        report["cas"] = {
            "column": detected_cas,
            "nonempty": int(nonempty_mask.sum()),
            "valid": int(valid_mask.sum()),
            "invalid": int((nonempty_mask & ~valid_mask).sum()),
            "invalid_examples": list(dict.fromkeys(invalid.astype(str)))[:10],
            "duplicates": int(normalized[nonempty_mask].duplicated().sum()),
        }
    else:
        report["cas"] = {"column": None, "note": "No common CAS column name detected"}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--cas-column")
    args = parser.parse_args()
    print(json.dumps(inspect(args.input, args.cas_column), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
