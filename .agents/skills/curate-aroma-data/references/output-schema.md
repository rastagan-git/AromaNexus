# Output and validation contract

## Identity

- Preserve the original input identifier.
- Use PubChem CID and InChIKey as canonical joins when available.
- Keep CAS as an external identifier and validate its checksum before exact-match providers.
- Never silently pick an ambiguous name result.

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
- `skipped`: a user deliberately skipped an interactive record.

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
