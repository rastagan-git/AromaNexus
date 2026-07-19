---
name: curate-aroma-data
description: Use AromaNexus to validate, normalize, enrich, and export flavor, odor, aroma, and chemical-sensory datasets with source-level provenance. Use for XLSX, CSV, or TSV workbooks containing CAS numbers, compound names, calculated retention indices, sensory descriptors, odor thresholds, or olfactory-receptor evidence; for selecting among NIST, PubChem, Pyrfume, M2OR, MFFI, and the permission-gated ChemicalBook compatibility connector; and for verifying analysis-ready outputs. Do not use to bypass access controls, relicense source data, or make biomedical or machine-learning claims unsupported by the exported evidence.
---

# Curate Aroma Data

Build traceable compound tables through the repository's `aromanexus` CLI. Keep the skill as an orchestration layer; modify provider behavior in the Python package, not here.

## Workflow

1. Inspect the input without modifying it.
   - Run `python .agents/skills/curate-aroma-data/scripts/inspect_workbook.py INPUT` from the repository root.
   - Confirm the row count, exact column names, identifier quality, duplicates, and formula-like cells.
2. Choose the smallest provider set that supplies the requested fields.
   - Read [references/provider-matrix.md](references/provider-matrix.md) before any network or browser operation.
   - Prefer PubChem for canonical identity and sourced odor annotations.
   - Use NIST only for the existing retention-index or name-resolution workflows.
   - Use Pyrfume only for explicitly selected archives after reviewing each manifest note.
   - Use M2OR only when receptor bioassay evidence is relevant; label species and assay scope.
3. Preview the operation.
   - State the input, new output path, selected provider, expected columns, approximate request count, cache behavior, and material access caveats.
   - Write a sibling output by default. Do not pass `--force` or overwrite the input unless the user explicitly requests that exact replacement.
4. Run one focused command.
   - Identity and odor metadata: `aromanexus pubchem INPUT --identifier-column "CAS Number"`
   - Retention indices: `aromanexus nist-ri INPUT --cas-column "CAS Number" --calculated-ri-column "Calculated RI"`
   - Names to CAS: `aromanexus resolve-cas INPUT --name-column "Name"`
   - Curated descriptors: `aromanexus pyrfume INPUT --archives aromadb,superscent`
   - Receptor evidence: `aromanexus m2or INPUT --cas-column "CAS Number"`
   - Source inventory: `aromanexus sources`
5. Verify the result.
   - Re-run the inspection script on the output.
   - Confirm identical row order and row count, expected new fields, typed status counts, source URL, retrieval time, version, and license/access fields.
   - Treat `http_error`, `network_error`, `parse_error`, `missing_data`, `data_error`, `partial`, `blocked`, and `skipped` separately from `not_found`.
   - Consult [references/output-schema.md](references/output-schema.md) when reconciling columns or statuses.
6. Report the output path, provider versions, status counts, partial failures, and any source terms the user must still review.

## Guardrails

- Keep NIST's interval at five seconds or slower and retain caching.
- Never automate CAPTCHA solving. Keep browser sources visible when user intervention may be required.
- Do not run ChemicalBook automation unless the user confirms documented permission; its current robots policy excludes the legacy routes.
- Do not describe the toolkit as AI-powered. Say that structured exports can support downstream statistics, cheminformatics, or machine-learning experiments.
- Do not bundle or republish downloaded Pyrfume or M2OR data in the repository.
- Preserve remote text as literal spreadsheet cells to prevent formula execution.
