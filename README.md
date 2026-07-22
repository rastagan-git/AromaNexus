# AromaNexus

[![CI](https://github.com/rastagan-git/AromaNexus/actions/workflows/ci.yml/badge.svg)](https://github.com/rastagan-git/AromaNexus/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)

**English** · [简体中文](README-CN.md)

A provenance-aware toolkit for turning compound workbooks into traceable chemical-sensory datasets.

AromaNexus connects chemical identity, gas-chromatographic retention indices, odor descriptors, thresholds, and optional olfactory-receptor assay evidence. For XLSX-to-XLSX runs it updates one selected worksheet while preserving supported workbook content, normalizes provider results, and records where each enrichment came from. The resulting tables are practical inputs for downstream statistics, cheminformatics, and carefully scoped machine-learning experiments.

```text
XLSX / CSV / TSV
      │
      ▼
validate identifiers ──► cached provider adapters ──► normalized fields + provenance
                                                            │
                                                            ▼
                                                new, analysis-ready table
```

## Why this version

The original four workbook scripts remain available, but the package now provides one consistent CLI with:

- exact CAS validation and explicit handling of ambiguous name matches;
- source-level status, URL, retrieval time, cache, version, license, and message fields;
- conservative request pacing, bounded retries, and persistent caching;
- atomic writes, periodic recovery checkpoints, and no accidental overwrite by default;
- workbook-aware XLSX output that retains non-target sheets, untargeted source formulas, formatting, and common worksheet features;
- optional PubChem, Pyrfume, and M2OR enrichment alongside the original NIST, MFFI, and ChemicalBook workflows.

## Installation

Python 3.11 or newer is required.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Confirm the installation and review provider modes before a live run:

```bash
aromanexus --version
aromanexus sources

# Equivalent module entry when the console launcher is unavailable
python -m aromanexus --version
```

## Quick start

The CLI accepts `.xlsx`, `.csv`, and `.tsv` tables. Column names are configurable; the examples below use the defaults.

```bash
# Canonical identity, properties, synonyms, CAS identifiers, and sourced odor text
aromanexus pubchem compounds.xlsx --identifier-column "CAS Number"

# Skip dataset-specific structural labels before a name lookup
aromanexus pubchem compounds.xlsx --identifier-column "Name" --skip-pattern '^C\d+$'

# Use an existing CAS column only to confirm candidates from a name lookup
aromanexus pubchem compounds.xlsx --identifier-column "Name" --existing-cas-column "Existing CAS"

# Skip PUG-View requests and omit the odor-only output column group
aromanexus pubchem compounds.xlsx --no-odor

# Select a worksheet by its exact name
aromanexus pubchem compounds.xlsx --sheet "Data" --identifier-column "Name"

# Closest NIST RI to an experimentally calculated RI
aromanexus nist-ri data.xlsx \
  --cas-column "CAS Number" \
  --calculated-ri-column "Calculated RI"

# Compound name to CAS through NIST WebBook
aromanexus resolve-cas names.xlsx --name-column "Name"

# Selected Pyrfume collections; resolves a CID through PubChem if needed
aromanexus pyrfume compounds.xlsx --archives aromadb,superscent

# Optional molecule–olfactory-receptor assay evidence
aromanexus m2or compounds.xlsx --cas-column "CAS Number"

# Interactive browser compatibility source
aromanexus mffi compounds.xlsx --cas-column "CAS Number"

# Permission-gated legacy source; the command asks for explicit confirmation
aromanexus chemicalbook-legacy compounds.xlsx --cas-column "CAS Number"
```

On PowerShell, put a multiline command on one line or replace Bash's `\` continuation with PowerShell's backtick.

## Commands

| Command | Default input field(s) | Purpose | Default output suffix |
| --- | --- | --- | --- |
| `aromanexus sources` | none | List providers, roles, and access modes. `providers` is an alias. | none |
| `aromanexus nist-ri INPUT` | `CAS Number`, `Calculated RI` | Match the closest value in the original NIST non-polar custom-temperature RI table. | `_nist_result` |
| `aromanexus resolve-cas INPUT` | `Name` | Resolve an unambiguous compound name to a CAS Registry Number through NIST. | `_with_cas` |
| `aromanexus pubchem INPUT` | `CAS Number` | Add CID, names, structure identifiers, selected properties, synonyms, CAS identifiers, and sourced odor annotations. | `_pubchem` |
| `aromanexus pyrfume INPUT` | `PubChem CID`, or `CAS Number` for CID resolution | Match allowlisted pinned archives: `aromadb`, `flavornet`, and/or `superscent`. Defaults to `aromadb,superscent`. | `_pyrfume` |
| `aromanexus m2or INPUT` | `CAS Number` | Aggregate molecule–receptor pairs, responsive pairs, species, human responsive receptors, and study DOIs. | `_m2or` |
| `aromanexus mffi INPUT` | `CAS Number` | Use a visible Chrome session for bilingual names, sensory characteristics, and in-water thresholds. Add `--headless` only when interaction is not needed. | `_mffi_result` |
| `aromanexus chemicalbook-legacy INPUT` | `CAS Number` | Retain the original interactive odor/threshold/type workflow. Disabled until documented permission is confirmed. | `_cb_result` |

Run `aromanexus COMMAND --help` for column and provider-specific options. Global options must precede the command:

```bash
aromanexus --cache-dir .cache/aromanexus --timeout 30 pubchem compounds.xlsx
```

For XLSX input, every table command processes the first worksheet in workbook order by default. Pass `--sheet "Data"` to select another worksheet by its exact, case-sensitive name. A missing worksheet is reported before any provider call; `--sheet` is not valid for CSV or TSV input.

### Output, checkpoints, and overwrite safety

Every table command writes a sibling file by default, keeps the original row order and columns, and adds provider fields. For example, `compounds.xlsx` becomes `compounds_pubchem.xlsx` after a PubChem run.

For XLSX-to-XLSX runs, AromaNexus starts from an immutable copy of the source package and overlays only enrichment cells on the selected worksheet. Non-target worksheet XML remains intact, as do supported source values, styles, row heights, column widths, freeze panes, filters, tables, data validation, conditional formatting, workbook properties, formulas, and cached formula results. Existing formulas are preserved outside cells explicitly targeted by an output field; deliberately targeting an existing formula cell replaces that cell as requested. Merged cells outside the selected tabular rectangle are preserved, while a merge intersecting that rectangle is rejected before provider access. Newly fetched formula-like text is escaped. The same preservation rules apply to `.partial.xlsx` checkpoints.

[Openpyxl cannot preserve every OOXML feature](https://openpyxl.readthedocs.io/en/3.1/tutorial.html). AromaNexus therefore performs an in-memory trial round trip and stops before provider calls when it detects known unsafe content—such as drawing shapes, comments, ActiveX/OLE controls, slicers, threaded comments, VML, or digital signatures—or any package part that the trial would discard. Excel's optional calculation chain may be removed so spreadsheet software can rebuild it. An explicit CSV/TSV output is a flat export and cannot retain Excel-only content.

By default, provenance columns include provider status, source URL, retrieval timestamp, cache hit, a provider-interface or pinned-snapshot label, license URL, and a diagnostic message. `Retrieved At` records when a provider or cached representation was actually obtained. It stays empty for local pre-request outcomes such as an explicit `skipped` row, invalid input, or a network failure before any response. Use `--no-provenance` only for legacy-shaped output.

PubChem reports CAS resolution separately and populates `Resolved CAS` only when the query itself is a confirmed CAS, a name lookup has exactly one checksum-valid candidate, or `--existing-cas-column` supplies a valid CAS that appears among the returned candidates. A conflicting or invalid existing CAS keeps the result unresolved; a blank cell falls back to the normal `unique`, `multiple`, or `missing` decision. For a `partial` provider result, only positive query or existing-CAS confirmation can resolve the row; decisions that depend on a complete candidate set remain `not_evaluated`. The original identifier and existing-CAS columns are never rewritten, and the CLI rejects an existing-CAS column name that overlaps an active output column.

PubChem odor enrichment is enabled by default. `--no-odor` skips PUG-View requests and does not add or update `PubChem Odor`, `PubChem Odor Annotations`, `PubChem Odor Sources`, `PubChem Odor Source URLs`, or `PubChem Odor License URLs`. If those columns already exist in the input, they are preserved unchanged.

`PubChem Version` is a per-row interface-attempt label. It is `PUG REST` when `--no-odor` is used or the lookup ends before the odor endpoint is attempted. Once a PUG-View request begins, it is `PUG REST + PUG-View`, including when the row later reports `partial`. This label does not prove that PUG-View returned or contributed an odor annotation; inspect `PubChem Status`, `PubChem Message`, and the odor fields. A row skipped before the PubChem client is called keeps a blank version.

```bash
# Choose an output explicitly
aromanexus pubchem compounds.xlsx --output results/compounds_enriched.xlsx

# Save a recoverable checkpoint every 10 rows; 0 disables checkpoints
aromanexus pubchem compounds.xlsx --checkpoint-every 10

# Replace an existing destination deliberately
aromanexus pubchem compounds.xlsx --output compounds_pubchem.xlsx --force
```

Checkpoints are named like `compounds_pubchem.partial.xlsx`. A required checkpoint path is validated before provider access, refreshed during the run, preserved if processing is interrupted, and removed after the final output succeeds. Every saved checkpoint remains a complete, openable workbook rather than a progress journal. Its preservation path reduces the overhead of repeated full-workbook serialization, but shorter intervals still perform more writes and trade speed for a more recent recovery file. AromaNexus deletes only a checkpoint created by the current run; an unrelated or externally replaced `.partial` file is left alone. Existing destinations and required checkpoint paths cause the command to stop unless `--force` is supplied. The input path—or an alias of the same file—can never be used as an output or checkpoint path, including with `--force`.

Successful HTTP responses and downloaded snapshots are cached under `~/.cache/aromanexus` by default. Set `AROMANEXUS_CACHE_DIR` or pass `--cache-dir` before the subcommand to use another location; the pre-rename cache environment variables remain accepted for compatibility.

## Data sources, access, and rights

Access policies and dataset terms can change. Re-check the linked provider documentation before a live extraction, publication, or redistribution decision. This repository does not grant rights to third-party data.

| Source | What this toolkit uses | Access and cache behavior | Rights and scientific limits |
| --- | --- | --- | --- |
| [PubChem PUG REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest) + [PUG-View](https://pubchem.ncbi.nlm.nih.gov/docs/pug-view) | Compound identity, selected properties, synonyms/CAS identifiers, and contributor-sourced odor annotations | Live NCBI APIs with persistent response caching. The client waits 0.25 s between uncached calls—4 requests/s, below PubChem's 5 requests/s ceiling—and retries bounded transient failures. | PubChem aggregates contributor records. Exports retain annotation source names, source URLs, and license URLs; review the [NCBI policies](https://www.ncbi.nlm.nih.gov/home/about/policies/) and each contributor's terms. |
| [NIST Chemistry WebBook, SRD 69](https://webbook.nist.gov/chemistry/) | Retention-index lookup and name-to-CAS resolution | Cached HTML with at least a 5-second delay between uncached requests, following the published [robots.txt](https://webbook.nist.gov/robots.txt). | [NIST Standard Reference Data rights](https://www.nist.gov/srd/public-law) apply. Fetch and cite records on demand; do not treat the service as a freely redistributable bulk dataset. |
| [Pyrfume Public Data Archive](https://github.com/pyrfume/pyrfume-data) | Pinned `aromadb`, `flavornet`, and `superscent` archive files keyed by PubChem CID | Explicit archive allowlist; selected files are downloaded from a pinned commit and cached locally. | Rights are **per manifest and upstream collection**. The repository's code license does not automatically license every dataset. Exports retain manifest source, notes, and license notes. |
| [M2OR](https://github.com/chemosim-lab/M2OR) | Molecule–olfactory-receptor pairs, response labels, species, receptors, and DOIs | Optional pinned CSV snapshot, approximately 43 MB, downloaded on first use and cached; it is not bundled in this repository. | The upstream snapshot is Apache-2.0. These are bioassay observations, not evidence of human perceptual quality, safety, efficacy, or clinical outcome. |
| [MFFI](https://mffi.sjtu.edu.cn/database/search) | Chinese/English names, sensory characteristics, and in-water thresholds | Interactive Selenium/Chrome access with conservative row pacing. No documented public API or rate policy was found. | No documented reuse license was found. A page being accessible—or allowed by robots rules—is not permission to republish its data. Use conservatively and cite the source. |
| [ChemicalBook](https://www.chemicalbook.com/) | Original odor description, odor threshold, and odor-type compatibility workflow | **Disabled by default and permission-gated.** Current [robots.txt](https://www.chemicalbook.com/robots.txt) excludes the search/property routes. The connector stays visible and manual; it never solves or bypasses CAPTCHA. | Run only with documented permission covering the intended automated access and reuse. `--i-have-permission` is an assertion by the operator, not permission supplied by this project. |

## Project skill for Codex

The repository includes a project-scoped skill at `.agents/skills/curate-aroma-data/`. In Codex, invoke:

```text
$curate-aroma-data
```

The skill inspects a workbook, chooses the smallest suitable provider set, previews access and output implications, runs one focused command, and verifies row count, schema, statuses, and provenance. It is an orchestration guide around this package—not a separate scraper or an automatic grant of data rights.

You can run its read-only workbook inspection helper directly:

```bash
python .agents/skills/curate-aroma-data/scripts/inspect_workbook.py compounds.xlsx --sheet "Data"
```

## Legacy compatibility

The pre-rename `flavor-data` command and `flavor_data_crawler` Python namespace remain compatibility aliases. New integrations should use `aromanexus`; existing automation does not need an immediate rewrite.

The original scripts and Windows launchers are retained for existing workbook layouts. They process the first worksheet; use the unified CLI when another worksheet must be selected.

| Launcher | Script | Expected workbook | Required column(s) | Output |
| --- | --- | --- | --- | --- |
| `start1.bat` | `nist_excel_tool.py` | `data.xlsx` | `CAS Number`, `Calculated RI` | `data_result.xlsx` |
| `start2.bat` | `name_to_cas.py` | `name.xlsx` | `Name` | `name_with_cas.xlsx` |
| `start3.bat` | `mffi_spider.py` | `max.xlsx` | `CAS Number` | `max_mffi_result.xlsx` |
| `start4.bat` | `cb_spider.py` | `Odor.xlsx` | `CAS Number` | `Odor_cb_result.xlsx` |

The `.bat` files prefer `.venv`, then `myenv`, then `venv`, and finally the system `python`. These compatibility scripts intentionally produce the historic, provenance-free column shape and replace their fixed result files. New work should use the CLI for explicit paths and overwrite protection. MFFI and ChemicalBook require a locally available Chrome browser; ChemicalBook still requires the permission phrase.

## Development and tests

Install the development dependencies, then run the offline test and lint suite:

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python -m pytest
```

CI runs those checks on Ubuntu and Windows with Python 3.11 and 3.13. Tests use fixtures or injected clients and do not depend on live provider websites or a Codex runtime.

## Responsible use

- Review provider terms, robots policies, citation requirements, and redistribution rights for your exact use case.
- Keep request rates conservative and prefer cached results.
- Never bypass CAPTCHA, authentication, paywalls, or other access controls.
- Treat `not_found`, `invalid_input`, `http_error`, `network_error`, `parse_error`, `missing_data`, `data_error`, `partial`, `blocked`, and `skipped` as different outcomes.
- Validate provenance and biological scope before using exports in statistics, cheminformatics, or machine-learning work.

## License

AromaNexus source code and original documentation are licensed under the
[MIT License](LICENSE).

This license does not grant rights to third-party datasets, website content,
provider responses, or generated datasets. Data obtained from PubChem, NIST,
Pyrfume, M2OR, MFFI, ChemicalBook, or other providers remains subject to each
provider's applicable terms, licenses, and usage restrictions.
