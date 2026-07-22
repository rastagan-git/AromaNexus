# Output and validation contract

## Identity

- Preserve the original input identifier.
- Use PubChem CID and InChIKey as canonical joins when available.
- Keep CAS as an external identifier and validate its checksum before exact-match providers.
- Never silently pick an ambiguous name result.

## PubChem CAS resolution

Keep provider execution and CAS curation in separate columns:

- `PubChem Status`: whether the provider request and record parsing succeeded.
- `PubChem CAS Numbers`: every checksum-valid candidate retained for review.
- `PubChem CAS Candidate Count`: the number of distinct valid candidates.
- `PubChem CAS Resolution`: the conservative resolution decision.
- `Resolved CAS`: populate only for `query_confirmed` or `unique`.

Interpret `PubChem CAS Resolution` as follows:

- `query_confirmed`: the input was a checksum-valid CAS and PubChem resolved its record.
- `unique`: a successful name lookup returned exactly one valid CAS candidate.
- `multiple`: more than one valid candidate remains; keep `Resolved CAS` empty.
- `missing`: a successful record returned no valid CAS candidate; keep `Resolved CAS` empty.
- `not_evaluated`: provider failure prevented a defensible CAS decision.
- `skipped`: an explicit user-supplied rule excluded the row before lookup.

## Status values

- `ok`: a provider returned a parsed record.
- `not_found`: the provider responded successfully but no exact record matched.
- `ambiguous`: more than one defensible identity matched.
- `invalid_input`: the identifier is empty, malformed, or fails validation.
- `network_error`: transport or remote-service failure; safe to retry later.
- `http_error`: the provider returned a non-success HTTP response that was not a clean not-found result.
- `parse_error`: the response arrived but its structure could not be interpreted; investigate a selector/schema change.
- `missing_data`: a required local or cached snapshot is unavailable and downloading is disabled or failed before parsing.
- `data_error`: every selected archive failed to load; inspect the per-archive diagnostic message.
- `partial`: at least one selected source succeeded and at least one failed, or a provider returned usable data with warnings.
- `blocked`: access policy or missing permission prevented the request.
- `skipped`: a user deliberately excluded a record through an interactive choice or explicit skip rule.

Do not merge an access, transport, HTTP, snapshot, parse, or partial failure into `not_found`.

## Provenance

Keep provider status, source URL, retrieval time, cache-hit flag, pinned version or snapshot, license URL, and message columns. For PubChem odor text, also keep contributor source names, URLs, and license URLs.

## Workbook QA

After every run, confirm:

1. Output row count and row order equal the input.
2. Original columns remain present.
3. Requested output columns exist.
4. Every processed row has a typed status.
5. Remote strings beginning with `=`, `+`, `-`, or `@` are stored as literal text.
6. Partial outputs are reported separately if a run is interrupted.
7. `multiple`, `missing`, `not_evaluated`, and `skipped` PubChem CAS resolutions never contain an automatic `Resolved CAS`.
8. XLSX worksheet order and names match the input, and supported non-target worksheet content and features are unchanged.
9. Source formulas and cached results outside explicitly targeted output cells, plus styles, dimensions, freeze panes, filters, tables, data validation, conditional formatting, and workbook properties, remain present where applicable.
10. Merged cells outside the selected tabular rectangle remain present; a merge intersecting that rectangle is rejected before provider access.
11. The target worksheet used for post-run inspection is the same exact worksheet selected for enrichment, and per-sheet content digests are compared.

For XLSX input, the default target is the first worksheet in workbook order. Pass `--sheet "Name"` to both the command and inspection helper when another worksheet is intended. Never pass `--sheet` for CSV or TSV; flat output cannot satisfy workbook-level preservation checks. XLSX preflight rejects known unsafe features and any OOXML package part dropped by its in-memory trial write. Excel's optional calculation chain may be removed and rebuilt by spreadsheet software.
