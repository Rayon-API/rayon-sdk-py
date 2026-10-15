# Changelog

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
