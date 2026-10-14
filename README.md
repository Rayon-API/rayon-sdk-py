# Rayon Python SDK

Synchronous and asynchronous Python clients for RayonAPI Shape header generation and account usage.
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

Apply all six `target_headers` to that exact request using your own target client and session.
Keep its browser identity consistent with `result.profile_used` and retain the session's cookies.
The response also includes `generation_ms`, `material_ref` and `material_expires_at`;
it does not return target cookies or verify target acceptance.

Supply exactly one of `scripts` or a server-issued `material_ref` with its original `source_url`.
All four `request` fields are required; GET/HEAD use `content_type=None`, `body=None`.
Preserve body whitespace and encoding. Persistent clients reuse unexpired material references,
while each call generates fresh headers from the supplied profile, request and cookies.
If a cached reference fails, use a fresh client with the saved scripts.

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
