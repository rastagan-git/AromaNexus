"""Workbook-oriented enrichment workflows shared by the CLI and legacy launchers."""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from aromanexus.excel_io import (
    derive_output_path,
    read_table,
    require_columns,
    write_table,
)
from aromanexus.models import LookupResult
from aromanexus.sources.chemicalbook import ManualVerificationRequired

ProgressCallback = Callable[[int, int, str], None]


@dataclass(slots=True)
class RunSummary:
    output_path: Path
    rows: int
    status_counts: dict[str, int]


def console_progress(current: int, total: int, label: str) -> None:
    print(f"[{current}/{total}] {label}", flush=True)


def _flatten(value: Any) -> Any:
    if isinstance(value, dict) or (
        isinstance(value, (list, tuple)) and any(isinstance(item, dict) for item in value)
    ):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, (list, tuple, set)):
        return "; ".join(str(item) for item in value if str(item).strip())
    return value


def _set_cell(frame: pd.DataFrame, index: Any, column: str, value: Any) -> None:
    """Create enrichment columns as object dtype so mixed values remain valid."""

    if column not in frame.columns:
        frame[column] = pd.Series([None] * len(frame), index=frame.index, dtype=object)
    elif frame[column].dtype != object:
        frame[column] = frame[column].astype(object)
    frame.at[index, column] = _flatten(value)


def _apply_result(
    frame: pd.DataFrame,
    index: Any,
    result: LookupResult,
    *,
    include_provenance: bool,
    prefix: str | None = None,
    key_map: dict[str, str] | None = None,
) -> None:
    mapping = key_map or {}
    for key, value in result.values.items():
        _set_cell(frame, index, mapping.get(key, key), value)
    if include_provenance:
        _apply_provenance(frame, index, result, prefix=prefix)


def _apply_provenance(
    frame: pd.DataFrame,
    index: Any,
    result: LookupResult,
    *,
    prefix: str | None = None,
) -> None:
    for key, value in result.provenance_columns(prefix).items():
        _set_cell(frame, index, key, value)


def _prepare_run(
    input_path: str | Path,
    output_path: str | Path | None,
    *,
    suffix: str,
    force: bool,
) -> tuple[pd.DataFrame, Path]:
    frame = read_table(input_path)
    destination = Path(output_path) if output_path else derive_output_path(input_path, suffix)
    if destination.exists() and not force:
        raise FileExistsError(f"Output already exists: {destination}. Pass --force to replace it.")
    return frame, destination


def _checkpoint(
    frame: pd.DataFrame,
    destination: Path,
    current: int,
    checkpoint_every: int,
) -> None:
    if checkpoint_every <= 0 or current % checkpoint_every:
        return
    partial = destination.with_name(f"{destination.stem}.partial{destination.suffix}")
    write_table(frame, partial, force=True)


def _finish(
    frame: pd.DataFrame,
    destination: Path,
    statuses: Counter[str],
    *,
    force: bool,
) -> RunSummary:
    write_table(frame, destination, force=force)
    partial = destination.with_name(f"{destination.stem}.partial{destination.suffix}")
    partial.unlink(missing_ok=True)
    return RunSummary(destination, len(frame), dict(sorted(statuses.items())))


def _indices(frame: pd.DataFrame) -> Iterable[tuple[int, Any, pd.Series]]:
    for position, (index, row) in enumerate(frame.iterrows(), 1):
        yield position, index, row


def run_nist_ri(
    input_path: str | Path,
    client: Any,
    *,
    output_path: str | Path | None = None,
    cas_column: str = "CAS Number",
    calculated_ri_column: str = "Calculated RI",
    result_column: str = "NIST RI",
    include_provenance: bool = True,
    checkpoint_every: int = 25,
    force: bool = False,
    progress: ProgressCallback = console_progress,
) -> RunSummary:
    frame, destination = _prepare_run(input_path, output_path, suffix="_nist_result", force=force)
    require_columns(frame, cas_column, calculated_ri_column)
    statuses: Counter[str] = Counter()
    total = len(frame)
    for current, index, row in _indices(frame):
        result = client.lookup_ri(row[cas_column], row[calculated_ri_column])
        _set_cell(frame, index, result_column, result.values.get("retention_index", "\\"))
        if include_provenance:
            candidates = result.values.get("retention_indices")
            if candidates:
                _set_cell(frame, index, "NIST RI Candidates", candidates)
            _apply_provenance(frame, index, result, prefix="NIST")
        statuses[result.status] += 1
        progress(current, total, f"NIST RI: {row[cas_column]} -> {frame.at[index, result_column]}")
        _checkpoint(frame, destination, current, checkpoint_every)
    return _finish(frame, destination, statuses, force=force)


def _legacy_name_status(result: LookupResult) -> str:
    if result.status == "ok" and result.values.get("cas"):
        return str(result.values["cas"])
    return {
        "ambiguous": "Ambiguous/List Found",
        "not_found": "Not Found",
        "network_error": "Connection Error",
        "invalid_input": "\\",
    }.get(result.status, "Error")


def run_resolve_cas(
    input_path: str | Path,
    client: Any,
    *,
    output_path: str | Path | None = None,
    name_column: str = "Name",
    result_column: str = "Found CAS",
    include_provenance: bool = True,
    checkpoint_every: int = 25,
    force: bool = False,
    progress: ProgressCallback = console_progress,
) -> RunSummary:
    frame, destination = _prepare_run(input_path, output_path, suffix="_with_cas", force=force)
    require_columns(frame, name_column)
    statuses: Counter[str] = Counter()
    total = len(frame)
    for current, index, row in _indices(frame):
        result = client.resolve_name(row[name_column])
        _set_cell(frame, index, result_column, _legacy_name_status(result))
        if include_provenance:
            _apply_provenance(frame, index, result, prefix="NIST")
        statuses[result.status] += 1
        label = f"Resolve name: {row[name_column]} -> {frame.at[index, result_column]}"
        progress(current, total, label)
        _checkpoint(frame, destination, current, checkpoint_every)
    return _finish(frame, destination, statuses, force=force)


PUBCHEM_COLUMN_MAP = {
    "cid": "PubChem CID",
    "title": "PubChem Title",
    "iupac_name": "IUPAC Name",
    "molecular_formula": "Molecular Formula",
    "molecular_weight": "Molecular Weight",
    "canonical_smiles": "Canonical SMILES",
    "isomeric_smiles": "Isomeric SMILES",
    "inchi": "InChI",
    "inchikey": "InChIKey",
    "xlogp": "XLogP",
    "synonyms": "PubChem Synonyms",
    "cas_numbers": "PubChem CAS Numbers",
    "odor": "PubChem Odor",
    "odor_annotations": "PubChem Odor Annotations",
    "odor_sources": "PubChem Odor Sources",
    "odor_source_urls": "PubChem Odor Source URLs",
    "odor_license_urls": "PubChem Odor License URLs",
}


def run_pubchem(
    input_path: str | Path,
    client: Any,
    *,
    output_path: str | Path | None = None,
    identifier_column: str = "CAS Number",
    include_odor: bool = True,
    include_provenance: bool = True,
    checkpoint_every: int = 25,
    force: bool = False,
    progress: ProgressCallback = console_progress,
) -> RunSummary:
    frame, destination = _prepare_run(input_path, output_path, suffix="_pubchem", force=force)
    require_columns(frame, identifier_column)
    statuses: Counter[str] = Counter()
    total = len(frame)
    for current, index, row in _indices(frame):
        identifier = row[identifier_column]
        result = client.lookup(identifier, include_odor=include_odor)
        _apply_result(
            frame,
            index,
            result,
            include_provenance=include_provenance,
            prefix="PubChem",
            key_map=PUBCHEM_COLUMN_MAP,
        )
        statuses[result.status] += 1
        progress(current, total, f"PubChem: {identifier} -> {result.status}")
        _checkpoint(frame, destination, current, checkpoint_every)
    return _finish(frame, destination, statuses, force=force)


def run_pyrfume(
    input_path: str | Path,
    archive_client: Any,
    *,
    pubchem_client: Any | None = None,
    output_path: str | Path | None = None,
    cid_column: str = "PubChem CID",
    identifier_column: str = "CAS Number",
    archives: list[str] | None = None,
    include_provenance: bool = True,
    checkpoint_every: int = 25,
    force: bool = False,
    progress: ProgressCallback = console_progress,
) -> RunSummary:
    frame, destination = _prepare_run(input_path, output_path, suffix="_pyrfume", force=force)
    if cid_column not in frame.columns:
        require_columns(frame, identifier_column)
        if pubchem_client is None:
            message = f"{cid_column!r} is absent; a PubChem client is required to resolve CIDs"
            raise ValueError(message)
    statuses: Counter[str] = Counter()
    total = len(frame)
    for current, index, row in _indices(frame):
        cid = row.get(cid_column)
        if (cid is None or str(cid).strip() in {"", "nan"}) and pubchem_client is not None:
            identity = pubchem_client.lookup(row[identifier_column], include_odor=False)
            cid = identity.values.get("cid")
            _apply_result(
                frame,
                index,
                identity,
                include_provenance=include_provenance,
                prefix="PubChem",
                key_map=PUBCHEM_COLUMN_MAP,
            )
        if cid is None or str(cid).strip() in {"", "nan"}:
            result = LookupResult.failure(
                "Pyrfume", status="invalid_input", message="No PubChem CID available"
            )
        else:
            result = archive_client.lookup(cid, archives=archives)
        _apply_result(
            frame,
            index,
            result,
            include_provenance=include_provenance,
            prefix="Pyrfume",
        )
        statuses[result.status] += 1
        progress(current, total, f"Pyrfume CID {cid}: {result.status}")
        _checkpoint(frame, destination, current, checkpoint_every)
    return _finish(frame, destination, statuses, force=force)


def run_m2or(
    input_path: str | Path,
    client: Any,
    *,
    output_path: str | Path | None = None,
    cas_column: str = "CAS Number",
    include_provenance: bool = True,
    checkpoint_every: int = 25,
    force: bool = False,
    progress: ProgressCallback = console_progress,
) -> RunSummary:
    frame, destination = _prepare_run(input_path, output_path, suffix="_m2or", force=force)
    require_columns(frame, cas_column)
    statuses: Counter[str] = Counter()
    total = len(frame)
    for current, index, row in _indices(frame):
        result = client.lookup_cas(row[cas_column])
        _apply_result(
            frame,
            index,
            result,
            include_provenance=include_provenance,
            prefix="M2OR",
        )
        statuses[result.status] += 1
        progress(current, total, f"M2OR: {row[cas_column]} -> {result.status}")
        _checkpoint(frame, destination, current, checkpoint_every)
    return _finish(frame, destination, statuses, force=force)


def run_mffi(
    input_path: str | Path,
    client: Any,
    *,
    output_path: str | Path | None = None,
    cas_column: str = "CAS Number",
    include_provenance: bool = True,
    checkpoint_every: int = 10,
    delay: float = 2.0,
    force: bool = False,
    progress: ProgressCallback = console_progress,
    sleep: Callable[[float], None] = time.sleep,
) -> RunSummary:
    frame, destination = _prepare_run(input_path, output_path, suffix="_mffi_result", force=force)
    require_columns(frame, cas_column)
    statuses: Counter[str] = Counter()
    total = len(frame)
    for current, index, row in _indices(frame):
        result = client.lookup_cas(row[cas_column])
        if not result.values:
            result.values = {
                "Chinese Name": "\\",
                "English Name": "\\",
                "Sensory Characteristics": "\\",
                "In Water": "\\",
            }
        _apply_result(
            frame,
            index,
            result,
            include_provenance=include_provenance,
            prefix="MFFI",
        )
        statuses[result.status] += 1
        progress(current, total, f"MFFI: {row[cas_column]} -> {result.status}")
        _checkpoint(frame, destination, current, checkpoint_every)
        if delay > 0 and current < total:
            sleep(delay)
    return _finish(frame, destination, statuses, force=force)


def run_chemicalbook_legacy(
    input_path: str | Path,
    client: Any,
    *,
    output_path: str | Path | None = None,
    cas_column: str = "CAS Number",
    include_provenance: bool = True,
    checkpoint_every: int = 5,
    delay: float = 2.0,
    force: bool = False,
    progress: ProgressCallback = console_progress,
    prompt: Callable[[str], str] = input,
    sleep: Callable[[float], None] = time.sleep,
) -> RunSummary:
    frame, destination = _prepare_run(input_path, output_path, suffix="_cb_result", force=force)
    require_columns(frame, cas_column)
    statuses: Counter[str] = Counter()
    total = len(frame)
    for current, index, row in _indices(frame):
        while True:
            try:
                result = client.lookup_cas(row[cas_column])
                break
            except ManualVerificationRequired as exc:
                question = f"{exc}\nPress Enter to retry, n to skip, or q to stop: "
                answer = prompt(question).strip().lower()
                if answer == "q":
                    raise KeyboardInterrupt("ChemicalBook run stopped by user") from exc
                if answer == "n":
                    result = LookupResult.failure(
                        "ChemicalBook",
                        status="skipped",
                        message="Skipped after manual browser inspection",
                    )
                    break
        if not result.values:
            result.values = {
                "CB_Odor_Desc": "\\",
                "CB_Odor_Threshold": "\\",
                "CB_Odor_Type": "\\",
            }
        _apply_result(
            frame,
            index,
            result,
            include_provenance=include_provenance,
            prefix="ChemicalBook",
        )
        statuses[result.status] += 1
        progress(current, total, f"ChemicalBook: {row[cas_column]} -> {result.status}")
        _checkpoint(frame, destination, current, checkpoint_every)
        if delay > 0 and current < total:
            sleep(delay)
    return _finish(frame, destination, statuses, force=force)
