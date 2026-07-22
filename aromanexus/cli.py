"""Command-line interface for AromaNexus."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from aromanexus import __version__
from aromanexus.sources.chemicalbook import (
    PERMISSION_PHRASE,
    ChemicalBookLegacyClient,
)
from aromanexus.sources.mffi import MffiClient
from aromanexus.workflows import (
    CHEMICALBOOK_VALUE_COLUMNS,
    MFFI_VALUE_COLUMNS,
    RunSummary,
    preflight_table_run,
    provenance_column_names,
    run_chemicalbook_legacy,
    run_m2or,
    run_mffi,
    run_nist_ri,
    run_pubchem,
    run_pyrfume,
    run_resolve_cas,
)

SOURCE_TABLE = """\
Provider       Access mode          Role                                      Default
PubChem        PUG REST/PUG-View    Identity, properties, sourced odor text   yes
NIST WebBook   cached HTML          Retention index and name-to-CAS            explicit
Pyrfume        pinned archive files Curated descriptor collections             explicit
M2OR           cached 43 MB CSV     Odorant-receptor bioassay evidence         explicit
MFFI           visible browser      Bilingual sensory fields and thresholds    explicit
ChemicalBook   permission-gated     Legacy manual compatibility only           disabled

Run `aromanexus <command> --help` for source-specific controls. The legacy
`flavor-data` command remains an alias. Data access and redistribution rights
remain source-specific; exported rows retain provenance.
"""


def _add_table_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", type=Path, help="Input .xlsx, .csv, or .tsv file")
    parser.add_argument(
        "--sheet",
        metavar="SHEET_NAME",
        help="XLSX worksheet to enrich (defaults to the first worksheet in workbook order)",
    )
    parser.add_argument(
        "-o", "--output", type=Path, help="Output path (defaults to a sibling file)"
    )
    parser.add_argument("--force", action="store_true", help="Replace an existing output file")
    parser.add_argument(
        "--no-provenance",
        action="store_true",
        help="Omit status and source metadata columns (legacy-style output)",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=25,
        metavar="N",
        help="Write a recoverable partial output every N records; 0 disables it",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aromanexus",
        description=(
            "Collect and normalize retention-index, odorant, and olfactory-receptor data "
            "with source-level provenance."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--cache-dir", type=Path, help="Override the provider cache directory")
    parser.add_argument(
        "--timeout", type=float, default=20, help="Network/browser timeout in seconds"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("sources", "providers"):
        source_parser = subparsers.add_parser(
            name, help="List provider capabilities and access modes"
        )
        source_parser.set_defaults(handler=_handle_sources)

    nist = subparsers.add_parser("nist-ri", help="Match the nearest NIST retention index")
    _add_table_arguments(nist)
    nist.add_argument("--cas-column", default="CAS Number")
    nist.add_argument("--calculated-ri-column", default="Calculated RI")
    nist.add_argument("--result-column", default="NIST RI")
    nist.set_defaults(handler=_handle_nist_ri)

    resolve = subparsers.add_parser("resolve-cas", help="Resolve compound names through NIST")
    _add_table_arguments(resolve)
    resolve.add_argument("--name-column", default="Name")
    resolve.add_argument("--result-column", default="Found CAS")
    resolve.set_defaults(handler=_handle_resolve_cas)

    pubchem = subparsers.add_parser(
        "pubchem", help="Add PubChem identifiers, properties, and sourced odor annotations"
    )
    _add_table_arguments(pubchem)
    pubchem.add_argument("--identifier-column", default="CAS Number")
    pubchem.add_argument(
        "--skip-pattern",
        action="append",
        default=[],
        metavar="REGEX",
        help="Skip identifiers matching this regex before lookup; repeat for multiple patterns",
    )
    pubchem.add_argument(
        "--resolved-cas-column",
        default="Resolved CAS",
        help=(
            "Output column populated only when the query, an existing CAS, or one unique "
            "candidate is confirmed"
        ),
    )
    pubchem.add_argument(
        "--existing-cas-column",
        metavar="COLUMN",
        help=(
            "Optional existing CAS column used to confirm name-query candidates; "
            "invalid or conflicting values remain unresolved"
        ),
    )
    pubchem.add_argument(
        "--no-odor",
        action="store_true",
        help="Skip PUG-View requests and do not add or update odor-only output columns",
    )
    pubchem.set_defaults(handler=_handle_pubchem)

    pyrfume = subparsers.add_parser(
        "pyrfume", help="Match CIDs against selected pinned Pyrfume archive collections"
    )
    _add_table_arguments(pyrfume)
    pyrfume.add_argument("--cid-column", default="PubChem CID")
    pyrfume.add_argument("--identifier-column", default="CAS Number")
    pyrfume.add_argument(
        "--archives",
        default="aromadb,superscent",
        help="Comma-separated allowlisted archives (aromadb, flavornet, superscent)",
    )
    pyrfume.set_defaults(handler=_handle_pyrfume)

    m2or = subparsers.add_parser(
        "m2or", help="Add optional olfactory-receptor evidence from the cached M2OR snapshot"
    )
    _add_table_arguments(m2or)
    m2or.add_argument("--cas-column", default="CAS Number")
    m2or.set_defaults(handler=_handle_m2or)

    mffi = subparsers.add_parser("mffi", help="Run the visible-browser MFFI compatibility source")
    _add_table_arguments(mffi)
    mffi.add_argument("--cas-column", default="CAS Number")
    mffi.add_argument("--headless", action="store_true")
    mffi.set_defaults(handler=_handle_mffi)

    chemicalbook = subparsers.add_parser(
        "chemicalbook-legacy",
        help="Run the permission-gated, manual ChemicalBook compatibility source",
    )
    _add_table_arguments(chemicalbook)
    chemicalbook.add_argument("--cas-column", default="CAS Number")
    chemicalbook.add_argument(
        "--i-have-permission",
        action="store_true",
        help="Assert that your use is authorized despite current robots exclusions",
    )
    chemicalbook.set_defaults(handler=_handle_chemicalbook)
    return parser


def _common_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "output_path": args.output,
        "sheet_name": args.sheet,
        "include_provenance": not args.no_provenance,
        "checkpoint_every": args.checkpoint_every,
        "force": args.force,
    }


def _http_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    values: dict[str, Any] = {"timeout": args.timeout}
    if args.cache_dir is not None:
        values["cache_dir"] = args.cache_dir
    return values


def _handle_sources(_: argparse.Namespace) -> int:
    print(SOURCE_TABLE)
    return 0


def _handle_nist_ri(args: argparse.Namespace) -> RunSummary:
    from aromanexus.sources.nist import NistWebBookClient

    client = NistWebBookClient(**_http_kwargs(args))
    return run_nist_ri(
        args.input,
        client,
        cas_column=args.cas_column,
        calculated_ri_column=args.calculated_ri_column,
        result_column=args.result_column,
        **_common_kwargs(args),
    )


def _handle_resolve_cas(args: argparse.Namespace) -> RunSummary:
    from aromanexus.sources.nist import NistWebBookClient

    client = NistWebBookClient(**_http_kwargs(args))
    return run_resolve_cas(
        args.input,
        client,
        name_column=args.name_column,
        result_column=args.result_column,
        **_common_kwargs(args),
    )


def _handle_pubchem(args: argparse.Namespace) -> RunSummary:
    from aromanexus.sources.pubchem import PubChemClient

    client = PubChemClient(**_http_kwargs(args))
    return run_pubchem(
        args.input,
        client,
        identifier_column=args.identifier_column,
        existing_cas_column=args.existing_cas_column,
        resolved_cas_column=args.resolved_cas_column,
        skip_patterns=args.skip_pattern,
        include_odor=not args.no_odor,
        **_common_kwargs(args),
    )


def _handle_pyrfume(args: argparse.Namespace) -> RunSummary:
    from aromanexus.sources.pubchem import PubChemClient
    from aromanexus.sources.pyrfume import PyrfumeArchiveClient

    archive_client = PyrfumeArchiveClient(cache_dir=args.cache_dir, timeout=args.timeout)
    pubchem_client = PubChemClient(**_http_kwargs(args))
    archives = [name.strip() for name in args.archives.split(",") if name.strip()]
    return run_pyrfume(
        args.input,
        archive_client,
        pubchem_client=pubchem_client,
        cid_column=args.cid_column,
        identifier_column=args.identifier_column,
        archives=archives,
        **_common_kwargs(args),
    )


def _handle_m2or(args: argparse.Namespace) -> RunSummary:
    from aromanexus.sources.m2or import M2ORClient

    client = M2ORClient(cache_dir=args.cache_dir, timeout=args.timeout)
    return run_m2or(args.input, client, cas_column=args.cas_column, **_common_kwargs(args))


def _handle_mffi(args: argparse.Namespace) -> RunSummary:
    preflight_table_run(
        args.input,
        output_path=args.output,
        suffix="_mffi_result",
        sheet_name=args.sheet,
        checkpoint_every=args.checkpoint_every,
        force=args.force,
        required_columns=(args.cas_column,),
        planned_columns=(
            *MFFI_VALUE_COLUMNS,
            *(provenance_column_names("MFFI") if not args.no_provenance else ()),
        ),
    )
    with MffiClient(timeout=args.timeout, headless=args.headless) as client:
        return run_mffi(args.input, client, cas_column=args.cas_column, **_common_kwargs(args))


def _confirm_chemicalbook_permission(args: argparse.Namespace) -> bool:
    if args.i_have_permission:
        return True
    print(
        "ChemicalBook currently excludes the automated search/property routes in robots.txt.\n"
        "This compatibility connector is not a CAPTCHA bypass and must only be used with "
        "documented permission."
    )
    return input(f"Type {PERMISSION_PHRASE!r} to continue: ").strip() == PERMISSION_PHRASE


def _handle_chemicalbook(args: argparse.Namespace) -> RunSummary | int:
    preflight_table_run(
        args.input,
        output_path=args.output,
        suffix="_cb_result",
        sheet_name=args.sheet,
        checkpoint_every=args.checkpoint_every,
        force=args.force,
        required_columns=(args.cas_column,),
        planned_columns=(
            *CHEMICALBOOK_VALUE_COLUMNS,
            *(provenance_column_names("ChemicalBook") if not args.no_provenance else ()),
        ),
    )
    if not _confirm_chemicalbook_permission(args):
        print("ChemicalBook compatibility run cancelled.", file=sys.stderr)
        return 2
    with ChemicalBookLegacyClient(
        permission_confirmed=True,
        timeout=args.timeout,
    ) as client:
        return run_chemicalbook_legacy(
            args.input,
            client,
            cas_column=args.cas_column,
            **_common_kwargs(args),
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if hasattr(args, "input") and not args.input.is_file():
            raise FileNotFoundError(f"Input file does not exist: {args.input}")
        result = args.handler(args)
        if isinstance(result, RunSummary):
            counts = ", ".join(f"{key}={value}" for key, value in result.status_counts.items())
            print(f"Saved {result.rows} rows to {result.output_path}")
            print(f"Statuses: {counts or 'none'}")
            return 0
        return int(result or 0)
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "Stopped by user. The latest .partial output is preserved when available.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
