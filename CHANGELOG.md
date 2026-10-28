# Changelog

## 2.1.0 — managed material

- Allow omitted material for managed header generation; preserve explicit overrides and preparation.
- Keep automatic selection current across repeated requests and material changes.
- Expose safe fallback and operation metadata. Keep existing retry, privacy and output validation.

## 2.0.0 — explicit material preparation

- Add explicit sync/async preparation, status polling, bounded waits, safe ready metadata and resumable errors for the available additive preparation API.
- Document complete-output validation and Rust-only execution for ready preparations; keep mandatory prepared-only cutover disabled, with the 30-day migration schedule announced separately.
- Validate preparation responses strictly and isolate readiness from source-only generation caching.
- Keep generation signatures, result frames and confirmed unbilled material-miss recovery unchanged.
- Preserve typed resumable cancellation errors across supported Python versions.

## 1.1.5 — 2026-10-23

- Clarify generation failure and incomplete-result messages with conditional script-loader and support guidance.
- Explain generated header and form validation failures without assigning fault to supplied material.

## 1.1.4 — 2026-10-20

- Bound retained original material to 128 bundles / 16 MiB per client and coalesce simultaneous uploads.
- Refresh material on the next generation shortly before expiry; recover once from confirmed uncharged material expiry.
- Keep cancellation, transport failures and ambiguous billing outcomes outside automatic recovery.

## 1.1.3 — 2026-10-19

- Add optional trusted error reasons, recovery guidance, safe domain/field metadata and billing status.
- Preserve existing exception types, codes, request IDs and retry behavior.

## 1.1.2 — 2026-10-17

- Expose the API’s optional retryable flag without changing retry behaviour.
- Explain request-history settlement states and uncertain outcomes.

## 1.1.1

Clarify HTTP errors and current API guidance.

## 1.1.0

Add opt-in `mode: "form"` generation with typed form results, exact-case ordered
fields, and a telemetry-only encoded body. Validate form transport, UTF-8, limits,
and complete telemetry families. Default header generation and material reuse remain
compatible. Accept the six required headers plus an optional fresh same-family `a0`,
preserving returned names and values. Reject incomplete, duplicate, mixed-family and
unsafe header sets. Form results remain exactly six fields. Reject mismatched response
transports and redact form values in inspection.

## 1.0.3

Documentation-only release: clarify prepared input, caller-owned material and sessions,
six-header application, timeout/retry handling, and links to documentation and examples.
No runtime or public interface changes.
