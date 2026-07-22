"""Workbook-oriented enrichment workflows shared by the CLI and legacy launchers."""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from aromanexus.excel_io import (
    TableContext,
    derive_output_path,
    read_table_with_context,
    record_touched_cell,
    require_columns,
    validate_table_output,
    write_table,
)
from aromanexus.identifiers import clean_text, is_valid_cas, normalize_cas
from aromanexus.models import LookupResult
from aromanexus.sources.chemicalbook import ManualVerificationRequired

ProgressCallback = Callable[[int, int, str], None]
PROVENANCE_COLUMN_SUFFIXES = (
    "Status",
    "Source URL",
    "Retrieved At",
    "Cache Hit",
    "Version",
    "License URL",
    "Message",
)
M2OR_VALUE_COLUMNS = (
    "M2OR Pair Count",
    "M2OR Responsive Count",
    "M2OR Species",
    "M2OR Human Responsive Receptors",
    "M2OR DOIs",
)
MFFI_VALUE_COLUMNS = (
    "Chinese Name",
    "English Name",
    "Sensory Characteristics",
    "In Water",
)
CHEMICALBOOK_VALUE_COLUMNS = (
    "CB_Odor_Desc",
    "CB_Odor_Threshold",
    "CB_Odor_Type",
)


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


def provenance_column_names(prefix: str) -> tuple[str, ...]:
    """Return the stable flattened provenance schema for one provider."""

    return tuple(f"{prefix} {suffix}" for suffix in PROVENANCE_COLUMN_SUFFIXES)


def _set_cell(frame: pd.DataFrame, index: Any, column: str, value: Any) -> None:
    """Create enrichment columns as object dtype so mixed values remain valid."""

    if column not in frame.columns:
        frame[column] = pd.Series([None] * len(frame), index=frame.index, dtype=object)
    elif frame[column].dtype != object:
        frame[column] = frame[column].astype(object)
    record_touched_cell(frame, index, column)
    frame.at[index, column] = _flatten(value)


def _apply_result(
    frame: pd.DataFrame,
    index: Any,
    result: LookupResult,
    *,
    include_provenance: bool,
    prefix: str | None = None,
    key_map: dict[str, str] | None = None,
    excluded_keys: Collection[str] = (),
) -> None:
    mapping = key_map or {}
    for key, value in result.values.items():
        if key in excluded_keys:
            continue
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
    sheet_name: str | None,
    checkpoint_every: int,
    force: bool,
    planned_columns: Iterable[str] = (),
) -> tuple[pd.DataFrame, Path, TableContext]:
    frame, context = read_table_with_context(input_path, sheet_name=sheet_name)
    destination = Path(output_path) if output_path else derive_output_path(input_path, suffix)
    minimum_new_columns = (
        sum(column not in frame.columns for column in dict.fromkeys(planned_columns))
        if len(frame)
        else 0
    )
    validate_table_output(
        context,
        destination,
        force=force,
        minimum_new_columns=minimum_new_columns,
    )
    if checkpoint_every > 0 and len(frame) >= checkpoint_every:
        partial = destination.with_name(f"{destination.stem}.partial{destination.suffix}")
        validate_table_output(
            context,
            partial,
            force=force,
            minimum_new_columns=minimum_new_columns,
        )
        context.planned_checkpoint_path = partial
        context.checkpoint_replace_existing = force
    return frame, destination, context


def preflight_table_run(
    input_path: str | Path,
    *,
    output_path: str | Path | None,
    suffix: str,
    sheet_name: str | None,
    checkpoint_every: int,
    force: bool,
    required_columns: tuple[str, ...] = (),
    planned_columns: tuple[str, ...] = (),
) -> Path:
    """Validate a CLI table run before launching an interactive provider."""

    frame, destination, _ = _prepare_run(
        input_path,
        output_path,
        suffix=suffix,
        sheet_name=sheet_name,
        checkpoint_every=checkpoint_every,
        force=force,
        planned_columns=planned_columns,
    )
    require_columns(frame, *required_columns)
    return destination


def _path_identity(path: Path) -> tuple[int, int] | None:
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return None
    return metadata.st_dev, metadata.st_ino


def _checkpoint(
    frame: pd.DataFrame,
    destination: Path,
    context: TableContext,
    current: int,
    checkpoint_every: int,
) -> None:
    if checkpoint_every <= 0 or current % checkpoint_every:
        return
    partial = context.planned_checkpoint_path
    if partial is None:
        raise RuntimeError("Checkpoint path was not validated before provider processing.")
    still_owned = (
        context.owned_checkpoint_path == partial
        and context.owned_checkpoint_identity is not None
        and _path_identity(partial) == context.owned_checkpoint_identity
    )
    replace_existing = True if still_owned else context.checkpoint_replace_existing
    write_table(frame, partial, force=replace_existing, context=context)
    context.owned_checkpoint_path = partial
    context.owned_checkpoint_identity = _path_identity(partial)


def _finish(
    frame: pd.DataFrame,
    destination: Path,
    context: TableContext,
    statuses: Counter[str],
    *,
    force: bool,
) -> RunSummary:
    write_table(frame, destination, force=force, context=context)
    partial = context.owned_checkpoint_path
    if (
        partial is not None
        and context.owned_checkpoint_identity is not None
        and _path_identity(partial) == context.owned_checkpoint_identity
    ):
        partial.unlink(missing_ok=True)
    context.owned_checkpoint_path = None
    context.owned_checkpoint_identity = None
    return RunSummary(destination, len(frame), dict(sorted(statuses.items())))


def _indices(frame: pd.DataFrame) -> Iterable[tuple[int, Any, pd.Series]]:
    for position, (index, row) in enumerate(frame.iterrows(), 1):
        yield position, index, row


def run_nist_ri(
    input_path: str | Path,
    client: Any,
    *,
    output_path: str | Path | None = None,
    sheet_name: str | None = None,
    cas_column: str = "CAS Number",
    calculated_ri_column: str = "Calculated RI",
    result_column: str = "NIST RI",
    include_provenance: bool = True,
    checkpoint_every: int = 25,
    force: bool = False,
    progress: ProgressCallback = console_progress,
) -> RunSummary:
    frame, destination, context = _prepare_run(
        input_path,
        output_path,
        suffix="_nist_result",
        sheet_name=sheet_name,
        checkpoint_every=checkpoint_every,
        force=force,
        planned_columns=(
            result_column,
            *(
                ("NIST RI Candidates", *provenance_column_names("NIST"))
                if include_provenance
                else ()
            ),
        ),
    )
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
        _checkpoint(frame, destination, context, current, checkpoint_every)
    return _finish(frame, destination, context, statuses, force=force)


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
    sheet_name: str | None = None,
    name_column: str = "Name",
    result_column: str = "Found CAS",
    include_provenance: bool = True,
    checkpoint_every: int = 25,
    force: bool = False,
    progress: ProgressCallback = console_progress,
) -> RunSummary:
    frame, destination, context = _prepare_run(
        input_path,
        output_path,
        suffix="_with_cas",
        sheet_name=sheet_name,
        checkpoint_every=checkpoint_every,
        force=force,
        planned_columns=(
            result_column,
            *(provenance_column_names("NIST") if include_provenance else ()),
        ),
    )
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
        _checkpoint(frame, destination, context, current, checkpoint_every)
    return _finish(frame, destination, context, statuses, force=force)


PUBCHEM_COLUMN_MAP = {
    "query": "query",
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
    "pubchem_url": "pubchem_url",
    "synonyms": "PubChem Synonyms",
    "cas_numbers": "PubChem CAS Numbers",
    "odor": "PubChem Odor",
    "odor_annotations": "PubChem Odor Annotations",
    "odor_sources": "PubChem Odor Sources",
    "odor_source_urls": "PubChem Odor Source URLs",
    "odor_license_urls": "PubChem Odor License URLs",
}
PUBCHEM_ODOR_KEYS = frozenset(
    {
        "odor",
        "odor_annotations",
        "odor_sources",
        "odor_source_urls",
        "odor_license_urls",
    }
)


def _compile_skip_patterns(patterns: Iterable[str] | str | None) -> tuple[re.Pattern[str], ...]:
    raw_patterns = (patterns,) if isinstance(patterns, str) else patterns or ()
    compiled: list[re.Pattern[str]] = []
    for pattern in raw_patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise ValueError(f"Invalid --skip-pattern regex {pattern!r}: {exc}") from exc
    return tuple(compiled)


def _valid_cas_candidates(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_candidates = value
    elif value is None:
        raw_candidates = ()
    else:
        raw_candidates = (value,)

    candidates: list[str] = []
    for candidate in raw_candidates:
        normalized = normalize_cas(candidate)
        if is_valid_cas(normalized) and normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _has_cell_value(value: Any) -> bool:
    """Return whether a scalar table cell contains a meaningful value."""

    if value is None:
        return False
    try:
        if bool(pd.isna(value)):
            return False
    except (TypeError, ValueError):
        pass
    return bool(clean_text(value))


def _apply_pubchem_resolution(
    frame: pd.DataFrame,
    index: Any,
    identifier: Any,
    result: LookupResult,
    *,
    resolved_cas_column: str,
    existing_cas: Any = None,
) -> None:
    candidates = _valid_cas_candidates(result.values.get("cas_numbers"))
    resolved_cas = ""
    query_cas = normalize_cas(identifier)
    has_existing_cas = _has_cell_value(existing_cas)
    input_cas = normalize_cas(existing_cas) if has_existing_cas else ""
    if result.status == "skipped":
        resolution = "skipped"
    elif result.status == "partial":
        if is_valid_cas(query_cas):
            resolution = "query_confirmed"
            resolved_cas = query_cas
        elif is_valid_cas(input_cas) and input_cas in candidates:
            resolution = "input_cas_confirmed"
            resolved_cas = input_cas
        else:
            resolution = "not_evaluated"
    elif result.status != "ok":
        resolution = "not_evaluated"
    else:
        if is_valid_cas(query_cas):
            resolution = "query_confirmed"
            resolved_cas = query_cas
        elif has_existing_cas:
            if not is_valid_cas(input_cas):
                resolution = "input_cas_invalid"
            elif input_cas in candidates:
                resolution = "input_cas_confirmed"
                resolved_cas = input_cas
            else:
                resolution = "input_cas_conflict"
        elif len(candidates) == 1:
            resolution = "unique"
            resolved_cas = candidates[0]
        elif candidates:
            resolution = "multiple"
        else:
            resolution = "missing"

    _set_cell(frame, index, "PubChem CAS Resolution", resolution)
    _set_cell(frame, index, "PubChem CAS Candidate Count", len(candidates))
    _set_cell(frame, index, resolved_cas_column, resolved_cas)


def run_pubchem(
    input_path: str | Path,
    client: Any,
    *,
    output_path: str | Path | None = None,
    sheet_name: str | None = None,
    identifier_column: str = "CAS Number",
    existing_cas_column: str | None = None,
    resolved_cas_column: str = "Resolved CAS",
    skip_patterns: Iterable[str] | str | None = None,
    include_odor: bool = True,
    include_provenance: bool = True,
    checkpoint_every: int = 25,
    force: bool = False,
    progress: ProgressCallback = console_progress,
) -> RunSummary:
    compiled_skip_patterns = _compile_skip_patterns(skip_patterns)
    planned_pubchem_columns = tuple(
        output_column
        for key, output_column in PUBCHEM_COLUMN_MAP.items()
        if include_odor or key not in PUBCHEM_ODOR_KEYS
    )
    frame, destination, context = _prepare_run(
        input_path,
        output_path,
        suffix="_pubchem",
        sheet_name=sheet_name,
        checkpoint_every=checkpoint_every,
        force=force,
        planned_columns=(
            *planned_pubchem_columns,
            "PubChem CAS Resolution",
            "PubChem CAS Candidate Count",
            resolved_cas_column,
            *(provenance_column_names("PubChem") if include_provenance else ()),
        ),
    )
    required_columns = [identifier_column]
    if existing_cas_column is not None:
        required_columns.append(existing_cas_column)
    require_columns(frame, *required_columns)
    active_output_columns = {
        *planned_pubchem_columns,
        "PubChem CAS Resolution",
        "PubChem CAS Candidate Count",
        resolved_cas_column,
        *(provenance_column_names("PubChem") if include_provenance else ()),
    }
    if existing_cas_column is not None and existing_cas_column in active_output_columns:
        raise ValueError(
            f"Existing CAS column {existing_cas_column!r} conflicts with an active PubChem "
            "output column; choose distinct input and output column names."
        )
    statuses: Counter[str] = Counter()
    total = len(frame)
    for current, index, row in _indices(frame):
        identifier = row[identifier_column]
        identifier_text = clean_text(identifier)
        matching_pattern = next(
            (pattern for pattern in compiled_skip_patterns if pattern.search(identifier_text)),
            None,
        )
        if matching_pattern is not None:
            result = LookupResult.failure(
                "PubChem",
                status="skipped",
                message=f"Identifier matched --skip-pattern {matching_pattern.pattern!r}",
            )
        else:
            result = client.lookup(identifier, include_odor=include_odor)
        _apply_result(
            frame,
            index,
            result,
            include_provenance=include_provenance,
            prefix="PubChem",
            key_map=PUBCHEM_COLUMN_MAP,
            excluded_keys=() if include_odor else PUBCHEM_ODOR_KEYS,
        )
        _apply_pubchem_resolution(
            frame,
            index,
            identifier,
            result,
            resolved_cas_column=resolved_cas_column,
            existing_cas=(row[existing_cas_column] if existing_cas_column is not None else None),
        )
        statuses[result.status] += 1
        progress(current, total, f"PubChem: {identifier} -> {result.status}")
        _checkpoint(frame, destination, context, current, checkpoint_every)
    return _finish(frame, destination, context, statuses, force=force)


def run_pyrfume(
    input_path: str | Path,
    archive_client: Any,
    *,
    pubchem_client: Any | None = None,
    output_path: str | Path | None = None,
    sheet_name: str | None = None,
    cid_column: str = "PubChem CID",
    identifier_column: str = "CAS Number",
    archives: list[str] | None = None,
    include_provenance: bool = True,
    checkpoint_every: int = 25,
    force: bool = False,
    progress: ProgressCallback = console_progress,
) -> RunSummary:
    frame, destination, context = _prepare_run(
        input_path,
        output_path,
        suffix="_pyrfume",
        sheet_name=sheet_name,
        checkpoint_every=checkpoint_every,
        force=force,
        planned_columns=(
            *(
                f"Pyrfume {archive} {field}"
                for archive in (
                    str(item).strip().casefold()
                    for item in (archives or ("aromadb", "flavornet", "superscent"))
                )
                for field in (
                    "Source Title",
                    "Source Reference",
                    "Source Authors",
                    "Source Notes",
                    "License Note",
                    "Manifest URL",
                    "Present",
                    "Name",
                    "IUPAC Name",
                    "Descriptors",
                )
            ),
            "Pyrfume Archives Matched",
            *(PUBCHEM_COLUMN_MAP.values() if pubchem_client is not None else ()),
            *(provenance_column_names("Pyrfume") if include_provenance else ()),
            *(
                provenance_column_names("PubChem")
                if include_provenance and pubchem_client is not None
                else ()
            ),
        ),
    )
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
        _checkpoint(frame, destination, context, current, checkpoint_every)
    return _finish(frame, destination, context, statuses, force=force)


def run_m2or(
    input_path: str | Path,
    client: Any,
    *,
    output_path: str | Path | None = None,
    sheet_name: str | None = None,
    cas_column: str = "CAS Number",
    include_provenance: bool = True,
    checkpoint_every: int = 25,
    force: bool = False,
    progress: ProgressCallback = console_progress,
) -> RunSummary:
    frame, destination, context = _prepare_run(
        input_path,
        output_path,
        suffix="_m2or",
        sheet_name=sheet_name,
        checkpoint_every=checkpoint_every,
        force=force,
        planned_columns=(
            *M2OR_VALUE_COLUMNS,
            *(provenance_column_names("M2OR") if include_provenance else ()),
        ),
    )
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
        _checkpoint(frame, destination, context, current, checkpoint_every)
    return _finish(frame, destination, context, statuses, force=force)


def run_mffi(
    input_path: str | Path,
    client: Any,
    *,
    output_path: str | Path | None = None,
    sheet_name: str | None = None,
    cas_column: str = "CAS Number",
    include_provenance: bool = True,
    checkpoint_every: int = 10,
    delay: float = 2.0,
    force: bool = False,
    progress: ProgressCallback = console_progress,
    sleep: Callable[[float], None] = time.sleep,
) -> RunSummary:
    frame, destination, context = _prepare_run(
        input_path,
        output_path,
        suffix="_mffi_result",
        sheet_name=sheet_name,
        checkpoint_every=checkpoint_every,
        force=force,
        planned_columns=(
            *MFFI_VALUE_COLUMNS,
            *(provenance_column_names("MFFI") if include_provenance else ()),
        ),
    )
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
        _checkpoint(frame, destination, context, current, checkpoint_every)
        if delay > 0 and current < total:
            sleep(delay)
    return _finish(frame, destination, context, statuses, force=force)


def run_chemicalbook_legacy(
    input_path: str | Path,
    client: Any,
    *,
    output_path: str | Path | None = None,
    sheet_name: str | None = None,
    cas_column: str = "CAS Number",
    include_provenance: bool = True,
    checkpoint_every: int = 5,
    delay: float = 2.0,
    force: bool = False,
    progress: ProgressCallback = console_progress,
    prompt: Callable[[str], str] = input,
    sleep: Callable[[float], None] = time.sleep,
) -> RunSummary:
    frame, destination, context = _prepare_run(
        input_path,
        output_path,
        suffix="_cb_result",
        sheet_name=sheet_name,
        checkpoint_every=checkpoint_every,
        force=force,
        planned_columns=(
            *CHEMICALBOOK_VALUE_COLUMNS,
            *(provenance_column_names("ChemicalBook") if include_provenance else ()),
        ),
    )
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
        _checkpoint(frame, destination, context, current, checkpoint_every)
        if delay > 0 and current < total:
            sleep(delay)
    return _finish(frame, destination, context, statuses, force=force)
