# Rayon Python SDK

Rayon manages current material for supported public sources. Send the source-page
URL, profile and exact request. No script collection or preparation is needed for
this header flow. Replace the reserved example URLs with your approved source and
endpoint. `{}` uses default profile values; supply measured values when needed.

Keep the API key server-side. Your integration owns the target HTTP client,
authentication, cookies and session. Rayon generates telemetry; your client sends
the target request.

[Quickstart](https://docs.rayonapi.com/quickstart) ·
[Material options](https://docs.rayonapi.com/material) ·
[API reference](https://docs.rayonapi.com/api-reference)

## Install

Requires Python 3.10+.

```sh
python -m pip install 'rayon-sdk-py>=2.1.0,<3'
```

## Generate

```python
import os
from rayon_sdk_py import Client

shape = {
    "source_url": "https://shop.example.com/account",
    "profile": {},
    "request": {
        "url": "https://shop.example.com/api/check",
        "method": "POST",
        "content_type": "application/json",
        "body": "{}",
    },
}
with Client(os.environ["RAYON_API_KEY"]) as client:
    result = client.generate(shape)
    if result.fallback_reason:
        print("A fallback was used. Contact support with request ID:", result.request_id)
    # Apply result.headers with your target client. Keep client open for further calls.
```

Use `AsyncClient` with `async with` and `await client.generate(shape)` in async
applications. Both clients accept the same inputs and return the same metadata.

Apply every returned header unchanged, including optional `a0`, to the exact
request. Header names may use a hyphen before the suffix or a compact prefix; preserve them exactly. Keep application headers and session state in your target client.
Generate fresh telemetry for each request and inspect the target response to
check acceptance. Rayon returns no target cookies.

## Fallback reporting

When `fallback_reason` is present and non-null, a fallback was used. Contact
support with `request_id` about the mapping issue. `fallback_message` provides
safe guidance when available. Do not infer fallback from timing alone.

Results also expose optional `path`, `material_reuse`, `discovery_state` and
`discovery_duration_ms`. Older responses can omit these fields.

## Optional material and preparation

For an explicit override, supply either `scripts` (complete ordered sources) or
`material_ref` (a private reference), never both. Omit the unused field; null and
empty values are invalid. Customer uploads and references remain private to the
API key. For an inline script, set `inline: true` and use the document URL; omit the flag for external scripts. Automatic requests should keep both fields omitted on every call so
new public material can be selected.

Form mode still requires explicit material. Set `mode: "form"`, supply the exact
URL-encoded POST application body before telemetry insertion, and prepend the
returned `form_body` once. It contains telemetry only. Preserve duplicate fields
and encoding. See [form integration](https://docs.rayonapi.com/form-payload-integration).

Preparation is optional for explicit material. It checks the supplied context
before a workload; it is separate from managed selection and generation.
Usable validated mappings can be ready without every internal record being mapped.
Generated headers and form fields must still pass output validation.

```python
# explicit_shape includes scripts or material_ref and the current full context.
ready = client.prepare_and_wait(explicit_shape, wait_timeout=60)
current = {k: v for k, v in explicit_shape.items() if k not in ("scripts", "material_ref")}
result = client.generate({**current, "material_ref": ready.material_ref})
```

Sync and async clients retain `prepare`, `get_preparation`, `wait_until_ready`
and `prepare_and_wait`. Waits default to 60 seconds; status long polls accept
0–10 seconds. `Preparation` exposes states and `ReadyMaterial` confirms readiness.
Timeout/cancellation leaves the server job running. `PreparationError` retains
`preparation_id` and a `kind` of `timeout`, `failed`, `expired` or `aborted`.
Async cancellation raises `PreparationCancelledError`, retaining the resumable ID.
Readiness expires separately from the source reference; prepare current explicit
context again after expiry or relevant input changes.

## Client options and errors

Reuse one client for connections. `usage()` is a free access/allowance check.
Default API URL: `https://api.rayonapi.com`; timeout: 45 seconds. Set `base_url`
or `timeout` in the constructor. Use `validate_profile` for offline validation.

Errors inherit `RayonError`: `ValidationError`, `TransportError`, `HTTPError`
and `InvalidResponseError`. Metadata includes `status_code`, `request_id`,
`code`, `retry_after`, `reason`, `action`, `domain`, `field`, `billing_status`
and `retryable` when available. Check request history before retrying a timeout
or uncertain billing outcome. Only a definite uncharged `material_expired`
receives one recovery attempt, while original explicit sources remain retained.
No other generation error is automatically retried.

Explicit-source caching retains up to 128 bundles / 16 MiB per client, coalesces
uploads and refreshes near expiry. References last up to five minutes and may
expire earlier. Automatic generation never pins a returned reference. The SDK
does not fetch target scripts, send target requests or cache generated telemetry.

[Errors](https://docs.rayonapi.com/errors) · [Release instructions](RELEASE.md) ·
[Support](mailto:support@rayonapi.com) · [MIT license](LICENSE)
