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

Custom material must be prepared before generation.
Deploy the compatible server before migrating clients.

Requires Python 3.10+.

```sh
python -m pip install 'rayon-sdk-py>=3.0.1,<4'
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
    # Apply result.headers with your target client. Keep client open for further calls.
```

Use `AsyncClient` with `async with` and `await client.generate(shape)` in async
applications. Both clients accept the same inputs and return the same metadata.

Apply every returned header unchanged, including optional `a0`, to the exact
request. Keep application headers and session state in your target client.
Generate fresh telemetry for each request and inspect the target response to
check acceptance. Rayon returns no target cookies.

## Material and readiness

Generation accepts ready managed material or a ready private reference. Custom
scripts must go through preparation. Unsupported, expired or unprepared inputs
return an explicit error. Generation does not prepare material or retry automatically.

SDK 3.0.1 accepts a successful managed preparation fallback with `path: isolated`
and `fallback_reason: material_preparing`. These fields remain available on the
result so your application can report degraded operation. The SDK advertises this
capability automatically; generation request bodies stay unchanged. Older SDKs
remain native-only on a server configured for the capability migration. A fallback
requires fresh managed material and is never an automatic retry by the SDK.

## Custom material requires preparation

Preparation can take several minutes. Wait helpers return as soon as ready, with a
30-minute default limit. Timeouts and cancellation leave the job available to resume.

```python
ready = client.prepare_and_wait(explicit_shape)
context = {k: v for k, v in explicit_shape.items() if k not in ("scripts", "material_ref")}
result = client.generate({**context, "material_ref": ready.material_ref})
```

Submit complete sources and the intended context with the preparation helper. Wait for
`state: ready`, then use its `material_ref` for generation.
A queued job can already contain a reference; that does not establish readiness.
Readiness is scoped to supported inputs. Normal request inputs may vary only within
that documented scope; an unchanged program does not establish universal coverage.

Refresh custom material outside generation before the earlier of `ready_until` and
`material_expires_at`, or after a supported deployment change. Wait for the replacement
to become ready before switching references. Keep original sources on your side for
refresh. Expired references are never recovered by uploading scripts to a solve call.
For managed header calls, keep both material fields omitted on every request.
Form mode requires an explicit ready reference.

## Client options and errors

Reuse one client for connections. `usage()` is a free access/allowance check.
Default API URL: `https://api.rayonapi.com`; timeout: 45 seconds. Set `base_url`
or `timeout` in the constructor. Use `validate_profile` for offline validation.

Errors inherit `RayonError`: `ValidationError`, `TransportError`, `HTTPError`
and `InvalidResponseError`. Metadata includes `status_code`, `request_id`,
`code`, `retry_after`, `reason`, `action`, `domain`, `field`, `billing_status`
and `retryable` when available. Check request history before retrying a timeout
or uncertain billing outcome. Generation is never automatically retried. Refresh expired custom material through preparation before resubmitting a solve.

The client retains no solve-upload source cache. Automatic generation never pins a returned reference. The SDK
does not fetch target scripts, send target requests or cache generated telemetry.

[Errors](https://docs.rayonapi.com/errors) · [Release instructions](RELEASE.md) ·
[Support](mailto:support@rayonapi.com) · [MIT license](LICENSE)
