# Rayon Python SDK

Synchronous and asynchronous Python clients for RayonAPI Shape header and form generation and account usage.
Requires Python 3.10+. Keep your API key on your server.

[Documentation](https://docs.rayonapi.com/) · [Examples](https://github.com/Rayon-API/rayon-examples) · [Releases](https://github.com/Rayon-API/rayon-sdk-py/releases)

## Install

```sh
python -m pip install 'rayon-sdk-py>=1,<2'
```

## Generate headers

Prepare `shape.json` with the required raw protection JavaScript in execution order, including
loaders and payloads where used. Include their context URLs, a current browser profile,
JavaScript-visible cookies (`document_cookie`) and the exact target URL, method, content type
and body string. See
[material preparation](https://docs.rayonapi.com/material) and
[profiles and sessions](https://docs.rayonapi.com/profiles-and-sessions).
The SDK and API use URLs as context; they do not download scripts or send the target request.

```python
import json
import os
from pathlib import Path
from rayon_sdk_py import Client, ShapeRequest

shape: ShapeRequest = json.loads(Path("shape.json").read_text(encoding="utf-8"))
with Client(os.environ["RAYON_API_KEY"], timeout=45) as client:
    result = client.generate(shape)
    target_headers = dict(result.headers)
    print(result.request_id)
```

Apply every returned `target_headers` to that exact request using your own target client and session.
Header mode returns the six required same-family `a`, `b`, `c`, `d`, `f`, `z` headers
and may include a fresh same-family `a0` header. Preserve all returned names, case and values.
Keep its browser identity consistent with `result.profile_used` and retain the session's cookies.
The response also includes `generation_ms`, `material_ref` and `material_expires_at`;
it does not return target cookies or verify target acceptance.

Supply exactly one of `scripts` or a server-issued `material_ref` with its original `source_url`.
All four `request` fields are required; GET/HEAD use `content_type=None`, `body=None`.
Preserve body whitespace and encoding. Persistent clients reuse unexpired material references,
while each call generates fresh headers from the supplied profile, request and cookies.
If a cached reference fails, use a fresh client with the saved scripts.

## Generate form telemetry

Requires SDK 1.1+. Set `mode="form"` and provide a POST with
`application/x-www-form-urlencoded`. `request.body` is the application form **before**
telemetry insertion, including duplicate fields and current CSRF/session values.
Optional `form={"id": "checkout", "name": "checkout"}` describes the form selector.

```python
from rayon_sdk_py import Client, FormShapeRequest

# prepared_material contains source_url, scripts (or material_ref), profile and cookies.
application_body = "item=first&item=second&csrf=current%2Bvalue"
form_shape: FormShapeRequest = {
    **prepared_material,
    "mode": "form",
    "form": {"id": "checkout"},
    "request": {
        "url": "https://example.com/submit",
        "method": "POST",
        "content_type": "application/x-www-form-urlencoded",
        "body": application_body,
    },
}
with Client(os.environ["RAYON_API_KEY"]) as client:
    result = client.generate(form_shape)  # FormShapeResult; no headers
    target_body = result.form_body + ("&" + application_body if application_body else "")
```

`form_fields` contains exactly six raw values under the exact observed names and case;
a larger `a` value remains one field and does not add `a0`.
`form_body` contains only those telemetry fields, already encoded once in observed
insertion order. Prepend it once to the original application body; do not encode it
again, convert application fields to a dictionary, or send stale telemetry in the input.
Retain the same cookies and browser identity for the target request. The SDK calls
public `POST /v1/shape`; it does not use the private `/solve` tool.

## Clients and errors

The SDK authenticates with `Authorization: Bearer <API key>` and defaults to
`https://api.rayonapi.com` with a 45-second API request timeout.
`AsyncClient` supports `async with`, `await client.generate(shape)` and `await client.usage()`.
`client.usage()` reads account usage; `generate(shape, api_key)` is a one-shot helper.

Errors inherit `RayonError`: `ValidationError` for invalid input, `TransportError` for network
failures/timeouts, `HTTPError` for API failures and `InvalidResponseError` for invalid responses.
HTTP errors expose sanitized `status_code`, `request_id`, `code` and `retry_after`.
No automatic retries. A client timeout may occur after successful generation; check history before retrying.
See the [API reference](https://docs.rayonapi.com/api-reference) and [errors](https://docs.rayonapi.com/errors).

[Support](mailto:support@rayonapi.com) · [Discord](https://discord.gg/TwhkJNyHWs) · [MIT license](LICENSE)
