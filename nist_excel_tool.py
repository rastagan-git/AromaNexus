"""Legacy launcher for the original NIST retention-index workbook workflow."""

from aromanexus.sources.nist import NistWebBookClient
from aromanexus.workflows import run_nist_ri

INPUT_FILE = "data.xlsx"
COL_CAS = "CAS Number"
COL_CALC_RI = "Calculated RI"
COL_RESULT = "NIST RI"


def get_nist_ri(cas: object, calc_ri: object) -> object:
    """Compatibility helper returning the historic value-or-backslash shape."""

    result = NistWebBookClient().lookup_ri(cas, calc_ri)
    return result.values.get("retention_index", "\\")


def main() -> None:
    output = INPUT_FILE.replace(".xlsx", "_result.xlsx")
    summary = run_nist_ri(
        INPUT_FILE,
        NistWebBookClient(),
        output_path=output,
        cas_column=COL_CAS,
        calculated_ri_column=COL_CALC_RI,
        result_column=COL_RESULT,
        include_provenance=False,
        checkpoint_every=25,
        force=True,
    )
    print(f"Done: {summary.output_path}")


if __name__ == "__main__":
    main()
