"""Legacy launcher for the original MFFI workbook workflow."""

from flavor_data_crawler.sources.mffi import MffiClient, create_chrome_driver
from flavor_data_crawler.workflows import run_mffi

INPUT_FILE = "max.xlsx"
COL_CAS = "CAS Number"


def init_driver():
    return create_chrome_driver(headless=False)


def get_mffi_data(driver, cas: object) -> dict[str, object]:
    result = MffiClient(driver=driver).lookup_cas(cas)
    return result.values or {
        "Chinese Name": "\\",
        "English Name": "\\",
        "Sensory Characteristics": "\\",
        "In Water": "\\",
    }


def main() -> None:
    output = INPUT_FILE.replace(".xlsx", "_mffi_result.xlsx")
    with MffiClient() as client:
        summary = run_mffi(
            INPUT_FILE,
            client,
            output_path=output,
            cas_column=COL_CAS,
            include_provenance=False,
            checkpoint_every=10,
            force=True,
        )
    print(f"Done: {summary.output_path}")


if __name__ == "__main__":
    main()
