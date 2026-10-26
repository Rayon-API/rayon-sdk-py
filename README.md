# Rayon Python SDK

## Explicit material preparation (2.0.0)

This release is coordinated with the backend preparation API deployment. Availability
must be confirmed before using these methods against a deployed API.

```python
from rayon_sdk_py import Client, PreparationError

with Client(api_key) as client:
    job = client.prepare(shape)  # existing full ShapeRequest, no generation
    try:
        ready = client.wait_until_ready(job.preparation_id, wait_timeout=60)
    except PreparationError as error:
        # Safe ID can resume an existing job later; timeout does not cancel it.
        preparation_id = error.preparation_id
        raise
    current = client.get_preparation(ready.preparation_id)
    # Or explicitly combine creation and waiting:
    ready = client.prepare_and_wait(shape, wait_timeout=60)
```

`AsyncClient` exposes the same four methods with `await`. Cancelling an async wait
raises `PreparationCancelledError` (a `PreparationError` with `kind="aborted"`) with a safe
`preparation_id`; the server job continues. `PreparationError.kind` is `timeout`,
`failed`, `expired`, or `aborted`. The typed cancellation error preserves resumable
metadata across supported Python versions rather than marking the task cancelled.
HTTP/transport/invalid-response errors during a wait also
retain the safe preparation ID for resumption.

`Preparation` reports `queued`, `learning`, `validating`, `publishing`, `ready`,
`failed`, or `expired`. A successful wait returns `ReadyMaterial`: safe metadata
including the reusable `material_ref`, material expiry, `ready_until`, and the
confirmed `rust` execution backend. It contains no scripts, cookies, or generated
headers. Readiness is scoped to the exact supplied request/profile/cookie/mode/form
context and its lifetime; use the current full context when preparing again.

Preparation is opt-in. `generate()` keeps its existing signature and result and
never creates a preparation job or waits for learning. Preparation does not reuse
or populate the source-only generation cache, and independent full contexts are
never coalesced. Each prepare invocation uses a fresh `Idempotency-Key`; the SDK
does not retry ambiguous POST results. Waiting uses bounded long polling and
jittered retries for transient GET failures under a monotonic time budget.


Generate Shape headers or form telemetry and read account usage. Keep your API
key server-side. Your integration owns its HTTP client or browser and target session.

[Quickstart](https://docs.rayonapi.com/quickstart) ·
[SDK guide](https://github.com/Rayon-API/docs/blob/main/guide/python.md) ·
[All SDKs](https://docs.rayonapi.com/sdks)

## Install

```sh
python -m pip install 'rayon-sdk-py>=2.0.0,<3'
```

## Check usage, then generate

Set `RAYON_API_KEY`. Prepare `shape.json` using the
[input guide](https://docs.rayonapi.com/material): source-page URL, complete ordered
script sources, a profile object and the exact target request. Include browser
measurements or JavaScript-visible cookies only when your flow requires them.

```python
import json
import os
from pathlib import Path
from rayon_sdk_py import Client

with Client(os.environ["RAYON_API_KEY"]) as client:
    usage = client.usage()  # Free; no generation quota used.
    print(usage)
    shape = json.loads(Path("shape.json").read_text(encoding="utf-8"))
    result = client.generate(shape)
    # Apply result.headers using your existing target client/session.
    # Reuse client here for further requests with their current inputs.
    print(result.request_id)
```

Apply the entire returned header map unchanged, including optional `a0`, to that
exact request. Keep required application headers, authentication and session state
in your target client. RayonAPI does not download scripts, send the target request
or return target cookies. Inspect the target response to establish acceptance.

## Form telemetry

For observed URL-encoded form telemetry, use `mode: "form"` and supply the exact
application body before telemetry insertion. The result has `form_fields` and
`form_body`, without generated headers. Prepend `form_body` once to the original
body, preserving its bytes, duplicate fields and encoding. See
[Form payload integration](https://docs.rayonapi.com/form-payload-integration)
for complete examples.

## Client options and errors

Requires Python 3.10+. Use `AsyncClient` with `async with`,
`await client.usage()` and `await client.generate(shape)` in async applications.
Set `timeout=45` in the constructor to set the API timeout.
Errors inherit `RayonError`: `ValidationError`, `TransportError`, `HTTPError`
and `InvalidResponseError`. Available metadata includes `status_code`,
`request_id`, `code`, `retry_after`, `reason`, `action`, `domain`, `field`,
`billing_status` and `retryable`.

The default API URL is `https://api.rayonapi.com`; default timeout is 45 seconds.
Keep one client open across calls. Python and JavaScript SDK 2.0.0 reuse material
in both modes while generating fresh telemetry for each request. Read the
[material and recovery policy](https://docs.rayonapi.com/material#reuse-material-not-headers)
for cache scope, limits and the single confirmed uncharged material recovery.

Check request history before resubmitting after a timeout or uncertain billing
outcome. See [errors and retry guidance](https://docs.rayonapi.com/errors),
[request fields](https://docs.rayonapi.com/api-reference) and
[browser/session inputs](https://docs.rayonapi.com/profiles-and-sessions).
The [Python download helper](https://github.com/Rayon-API/rayon-examples) is optional.

[Support](mailto:support@rayonapi.com) ·
[Releases](https://github.com/Rayon-API/rayon-sdk-py/releases) · [MIT license](LICENSE)
