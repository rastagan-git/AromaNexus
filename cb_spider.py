"""Permission-gated legacy launcher for the original ChemicalBook workflow."""

from flavor_data_crawler.sources.chemicalbook import (
    PERMISSION_PHRASE,
    ChemicalBookLegacyClient,
)
from flavor_data_crawler.workflows import run_chemicalbook_legacy

INPUT_FILE = "Odor.xlsx"
COL_CAS = "CAS Number"


def main() -> None:
    print(
        "ChemicalBook currently disallows these automated routes in robots.txt. "
        "Continue only if you have documented permission."
    )
    if input(f"Type {PERMISSION_PHRASE!r} to continue: ").strip() != PERMISSION_PHRASE:
        print("Cancelled.")
        return
    output = INPUT_FILE.replace(".xlsx", "_cb_result.xlsx")
    with ChemicalBookLegacyClient(permission_confirmed=True) as client:
        summary = run_chemicalbook_legacy(
            INPUT_FILE,
            client,
            output_path=output,
            cas_column=COL_CAS,
            include_provenance=False,
            checkpoint_every=5,
            force=True,
        )
    print(f"Done: {summary.output_path}")


if __name__ == "__main__":
    main()
