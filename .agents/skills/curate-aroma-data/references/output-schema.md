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
- `Resolved CAS`: populate only for `query_confirmed`, `input_cas_confirmed`, or `unique`.

Interpret `PubChem CAS Resolution` as follows:

- `query_confirmed`: the input was a checksum-valid CAS and PubChem resolved its record.
- `input_cas_confirmed`: for a non-CAS query, the optional existing CAS was valid and appeared among the returned candidates.
- `input_cas_conflict`: the optional existing CAS was valid but absent from the returned candidates; keep `Resolved CAS` empty.
- `input_cas_invalid`: the optional existing CAS was nonblank but invalid; keep `Resolved CAS` empty.
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

When the optional existing-CAS cell is blank or missing, use the normal `unique`, `multiple`, or `missing` rule. A valid CAS query itself always takes precedence as `query_confirmed`. Never modify the existing-CAS column or remove candidates from `PubChem CAS Numbers`.

For a `partial` provider result, accept only positive `query_confirmed` or `input_cas_confirmed` evidence. Do not infer `unique`, `multiple`, `missing`, `input_cas_conflict`, or `input_cas_invalid` from a potentially incomplete secondary response; use `not_evaluated` instead.

## Optional odor columns

PubChem odor enrichment is enabled by default. With `--no-odor`, skip PUG-View requests and do not add or update `PubChem Odor`, `PubChem Odor Annotations`, `PubChem Odor Sources`, `PubChem Odor Source URLs`, or `PubChem Odor License URLs`. Preserve any such columns already present in the input.

## Provenance

Keep provider status, source URL, retrieval time, cache-hit flag, provider-interface or pinned-snapshot label, license URL, and message columns. For PubChem odor text, also keep contributor source names, URLs, and license URLs.

`Retrieved At` is the timestamp of an actual provider or cached representation. Leave it empty for outcomes decided before any representation was obtained, including explicit skips, local input validation failures, and transport failures before a response. A received HTTP or parse-error response retains its retrieval timestamp.

Interpret `PubChem Version` as the interfaces attempted for that row. Use `PUG REST` when odor lookup is disabled or the lookup ends before the PUG-View odor endpoint is attempted. Once that endpoint request begins, use `PUG REST + PUG-View`, even if the request produces no odor annotation or the row becomes `partial`. This label does not prove that PUG-View contributed data; inspect `PubChem Status`, `PubChem Message`, and the odor fields. Keep the version blank for a row skipped before calling the PubChem client.

## Workbook QA

After every run, confirm:

1. Output row count and row order equal the input.
2. Original columns remain present.
3. Requested output columns exist.
4. Every processed row has a typed status.
5. Remote strings beginning with `=`, `+`, `-`, or `@` are stored as literal text.
6. Partial outputs are reported separately if a run is interrupted.
7. `multiple`, `missing`, `input_cas_conflict`, `input_cas_invalid`, `not_evaluated`, and `skipped` PubChem CAS resolutions never contain an automatic `Resolved CAS`.
8. XLSX worksheet order and names match the input, and supported non-target worksheet content and features are unchanged.
9. Source formulas and cached results outside explicitly targeted output cells, plus styles, dimensions, freeze panes, filters, tables, data validation, conditional formatting, and workbook properties, remain present where applicable.
10. Merged cells outside the selected tabular rectangle remain present; a merge intersecting that rectangle is rejected before provider access.
11. The target worksheet used for post-run inspection is the same exact worksheet selected for enrichment, and per-sheet content digests are compared.

For XLSX input, the default target is the first worksheet in workbook order. Pass `--sheet "Name"` to both the command and inspection helper when another worksheet is intended. Never pass `--sheet` for CSV or TSV; flat output cannot satisfy workbook-level preservation checks. XLSX preflight rejects known unsafe features and any OOXML package part dropped by its in-memory trial write. Excel's optional calculation chain may be removed and rebuilt by spreadsheet software.
