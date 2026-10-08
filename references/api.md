# Official API and runtime notes

Reviewed 2026-10-08. Public documentation is authoritative for the target account/version.

## [Neon API](https://neon.com/docs/reference/api-reference)

Bearer authentication against https://console.neon.tech/api/v2.

## [Branch listing](https://api-docs.neon.tech/reference/listprojectbranches)

Explicit project branch inspection.

## [OpenAPI](https://neon.com/api_spec/release/v2.json)

Current public v2 API schema for endpoint/request validation.

## Boundaries

Python 3.10+. `NEON_API_KEY` or an explicit `NEON_API_KEY_FILE` (private regular file). No default team or organization, no account-specific token discovery.

Management API only: no SQL execution or secret retrieval workflow. Generic API mutations are an escape hatch, not schema validation. Lists expose a single response page; use --param and provider pagination. Connection credentials are redacted and not recoverable through this CLI.

HTTP helpers do not follow redirects or automatically retry writes. A timeout can mean an unknown outcome; inspect the target before retrying. Secret-field redaction is defense in depth, not a guarantee that arbitrary free text is safe to publish.
