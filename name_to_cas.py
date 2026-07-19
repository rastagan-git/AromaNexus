"""Legacy launcher for the original NIST name-to-CAS workbook workflow."""

from flavor_data_crawler.sources.nist import NistWebBookClient
from flavor_data_crawler.workflows import run_resolve_cas

INPUT_FILE = "name.xlsx"
COL_NAME = "Name"
COL_RESULT = "Found CAS"


def get_cas_by_name(name: object) -> str:
    """Compatibility helper returning the historic text statuses."""

    result = NistWebBookClient().resolve_name(name)
    if result.status == "ok":
        return str(result.values.get("cas", "Not Found"))
    return {
        "ambiguous": "Ambiguous/List Found",
        "not_found": "Not Found",
        "network_error": "Connection Error",
    }.get(result.status, "Error")


def main() -> None:
    output = INPUT_FILE.replace(".xlsx", "_with_cas.xlsx")
    summary = run_resolve_cas(
        INPUT_FILE,
        NistWebBookClient(),
        output_path=output,
        name_column=COL_NAME,
        result_column=COL_RESULT,
        include_provenance=False,
        checkpoint_every=25,
        force=True,
    )
    print(f"Done: {summary.output_path}")


if __name__ == "__main__":
    main()
