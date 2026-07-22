---
name: curate-aroma-data
description: Use AromaNexus to validate, normalize, enrich, and export flavor, odor, aroma, and chemical-sensory datasets with source-level provenance. Use for XLSX, CSV, or TSV files containing CAS numbers, compound names, calculated retention indices, sensory descriptors, odor thresholds, or olfactory-receptor evidence; for selecting among NIST, PubChem, Pyrfume, M2OR, MFFI, and the permission-gated ChemicalBook compatibility connector; and for verifying analysis-ready outputs. Do not use to bypass access controls, relicense source data, or make biomedical or machine-learning claims unsupported by the exported evidence.
---

# Curate Aroma Data

Build traceable compound tables through the repository's `aromanexus` CLI. Keep the skill as an orchestration layer; modify provider behavior in the Python package, not here.

If the console launcher is unavailable, replace `aromanexus ...` with the equivalent `python -m aromanexus ...` invocation.

## Workflow

1. Inspect the input without modifying it.
   - For XLSX, run `python .agents/skills/curate-aroma-data/scripts/inspect_workbook.py INPUT --sheet "SHEET"` from the repository root. Omit `--sheet` only when the first worksheet is the intended target.
   - For CSV or TSV, run the inspector without `--sheet`; flat files have no worksheets.
   - Confirm the worksheet order and exact target when applicable, row count, exact column names, identifier quality, duplicates, source formulas, workbook properties, per-sheet content digests, styles, dimensions, and reported features.
   - Identify section labels, headers, totals, and other structural rows before provider calls. Define an explicit dataset-specific skip rule; do not assume that text such as `C6` is globally non-chemical.
2. Choose the smallest provider set that supplies the requested fields.
   - Read [references/provider-matrix.md](references/provider-matrix.md) before any network or browser operation.
   - Prefer PubChem for canonical identity and sourced odor annotations.
   - Use NIST only for the existing retention-index or name-resolution workflows.
   - Use Pyrfume only for explicitly selected archives after reviewing each manifest note.
   - Use M2OR only when receptor bioassay evidence is relevant; label species and assay scope.
3. Preview the operation.
   - State the input, selected worksheet for XLSX, new output path, selected provider, expected columns, skip patterns, whether odor annotations are requested, any existing-CAS confirmation column, approximate request count, cache behavior, and material access caveats.
   - Write a sibling output by default. Never reuse the input path as the output path; `--force` is only for a separate existing destination.
   - Keep XLSX input and output when worksheet formulas, formatting, or other workbook content must survive; CSV/TSV output is a flat export.
4. Run one focused command.
   - Identity and odor metadata: `aromanexus pubchem INPUT --identifier-column "CAS Number"`
   - Name lookup with dataset-specific structural rows: `aromanexus pubchem INPUT --identifier-column "Name" --skip-pattern '^C\d+$'`
   - Name lookup with a conservative existing-CAS signal: `aromanexus pubchem INPUT --identifier-column "Name" --existing-cas-column "Existing CAS"`
   - Identity without PUG-View requests or odor-only output columns: `aromanexus pubchem INPUT --no-odor`
   - Retention indices: `aromanexus nist-ri INPUT --cas-column "CAS Number" --calculated-ri-column "Calculated RI"`
   - Names to CAS: `aromanexus resolve-cas INPUT --name-column "Name"`
   - Curated descriptors: `aromanexus pyrfume INPUT --archives aromadb,superscent`
   - Receptor evidence: `aromanexus m2or INPUT --cas-column "CAS Number"`
   - Source inventory: `aromanexus sources`
   - For XLSX only, append `--sheet "SHEET"` to any table command when the target is not the first worksheet. Never pass `--sheet` for CSV or TSV.
5. Verify the result.
   - Re-run the inspection script on the same worksheet for XLSX, or without `--sheet` for CSV/TSV.
   - Confirm identical row order and row count, expected new fields, typed status counts, source URL, retrieval time, version, and license/access fields. Treat a blank retrieval time as correct when no provider or cached representation was obtained, including an explicit pre-request skip.
   - For XLSX output, also compare worksheet order and names, per-sheet content digests, workbook properties, non-target-sheet content, untargeted source formulas and cached values, styles, dimensions, and reported workbook features.
   - Treat `PubChem Status` as provider execution state, not proof of a uniquely resolved CAS. Check `PubChem CAS Resolution`, candidate count, and `Resolved CAS` separately.
   - Leave `multiple`, `missing`, `input_cas_conflict`, and `input_cas_invalid` CAS resolutions unresolved; retain all candidates and route only the affected rows to a targeted fallback source or manual review.
   - Treat `http_error`, `network_error`, `parse_error`, `missing_data`, `data_error`, `partial`, `blocked`, and `skipped` separately from `not_found`.
   - Consult [references/output-schema.md](references/output-schema.md) when reconciling columns or statuses.
6. Report the output path, provider versions, status counts, partial failures, and any source terms the user must still review.

## Guardrails

- Keep NIST's interval at five seconds or slower and retain caching.
- Never automate CAPTCHA solving. Keep browser sources visible when user intervention may be required.
- Do not run ChemicalBook automation unless the user confirms documented permission; its current robots policy excludes the legacy routes.
- Do not describe the toolkit as AI-powered. Say that structured exports can support downstream statistics, cheminformatics, or machine-learning experiments.
- Do not bundle or republish downloaded Pyrfume or M2OR data in the repository.
- Preserve newly fetched remote text as literal spreadsheet cells to prevent formula execution. Preserve legitimate source formulas outside cells explicitly targeted by an output field.
- Preserve merged cells outside the selected tabular rectangle; stop before provider calls when a merge intersects that rectangle.
- Stop before provider calls if XLSX preflight reports a known unsafe feature or any OOXML package part that the in-memory trial write would discard.
- Never select the first PubChem CAS candidate merely because the provider status is `ok`.
- Use an existing CAS column only to confirm a returned candidate for a non-CAS query. Never overwrite it or use a conflicting/invalid value to force resolution.
