# Rayon Python SDK

Material-only clients for `POST /v1/shape` and `GET /v1/usage`. Requires Python 3.10+.

```sh
python -m pip install 'rayon-sdk-py>=1,<2'
```

Prepare JavaScript material from files you own or are authorized to use. URLs provide execution context; neither SDK nor API downloads them. Preserve script order.

```python
import os
from pathlib import Path
from rayon_sdk_py import Client, ShapeRequest

shape: ShapeRequest = {
    "source_url": "https://example.com/page",
    "scripts": [{
        "url": "https://example.com/assets/owned.js",
        "source": Path("owned.js").read_text(encoding="utf-8"),
    }],
    "profile": {"user_agent": "your actual user agent", "language": "en-GB"},
    "request": {
        "url": "https://example.com/api/items",
        "method": "POST",
        "content_type": "application/json",
        "body": ' {"item": 1}\n',  # Exact target body, including whitespace.
    },
    "document_cookie": "session=current",  # Current JavaScript-visible cookies.
}
with Client(os.environ["RAYON_API_KEY"]) as client:
    result = client.generate(shape)
    usage = client.usage()
    # Explicitly access result.headers and result.profile_used for your target client.
```

`Client(api_key, *, base_url="https://api.rayonapi.com", timeout=45)` owns a persistent ordinary-TLS session. Close it with `with` or `client.close()`. `AsyncClient` has the same operations using `async with`, `await client.generate(shape)`, `await client.usage()`, and `await client.aclose()`. `generate(shape, api_key, *, base_url=..., timeout=45)` is a one-shot helper. API keys remain in the Bearer authorization header.

Supply exactly one of `scripts` and `material_ref`. `source_url`, `profile`, and all four `request` fields are always required. Use `body=None` when the target request has no body; an empty string represents an explicit empty body. GET and HEAD require `body=None`; a supplied body requires a supported text content type. Bodies are never parsed, reformatted, or encoded as a JSON object by this SDK.

Persistent clients cache only material references, keyed by source URL and ordered script URLs and source. Each cache is scoped to one client, API key, and server, and uses the server's `material_expires_at` expiry. Repeating the same material uses its unexpired reference; profile, request, and document cookies are freshly copied for every call. Expired entries trigger a fresh upload on the next call with scripts. A failed reference request is never automatically retried. You may also explicitly supply a server-issued reference together with its original source URL.

`validate_profile(profile)` is a public offline preflight helper. It enforces the same strict fields, alias conflicts, numeric ranges, and effective UTF-8 profile budget as generation, and returns a deep copy of the supplied fields. It neither fills defaults in the returned object nor sends a network request. Text limits count Unicode code points.

`BrowserProfile` accepts `user_agent`, `platform`, `language`, `languages`, `screen`, `window`, `webgl`, `canvas`, and `navigator`. Nested fields are strictly checked, and conflicting top-level/navigator aliases are rejected. `{}` selects server defaults. Screen/window dimensions, WebGL renderer/vendor, navigator identity, and a PNG `canvas.data_url` are supported. The response's effective `profile_used` omits canvas pixels.

`ShapeResult` contains `headers`, `request_id`, `generation_ms`, `profile_used`, and required `material_ref`/`material_expires_at`. The six header names use the actual dynamic common prefix and suffixes `a`, `b`, `c`, `d`, `f`, `z`; `d` may be empty. Prefixes are HTTP tokens of at most 128 characters and header values contain visible ASCII only. Generation does not assert target acceptance. No cookies, status, or internal execution method are returned. Sensitive headers, profile data, and references are excluded from repr.

Limits are 4 MiB of serialized request JSON, 16 scripts, 2 MiB per script and 3 MiB of total UTF-8 source, 256 KiB of UTF-8 target body, 64 KiB of effective UTF-8 profile JSON (including defaults and alias expansion), and 16 KiB of document cookies. Decoded API responses are bounded to 256 KiB and stop the transfer when exceeded. Timeout covers the total API request, including async connection-pool waiting and response decoding. TLS certificate verification remains enabled; redirects and environment proxies are disabled. Custom bases require HTTPS, except local HTTP on `localhost`, `127.0.0.1`, or `[::1]`; credentials, fragments, and base queries are refused. API transport does not impersonate a browser.

All errors inherit `RayonError`. `ValidationError` precedes network access; `TransportError` covers network failures; `InvalidResponseError` covers malformed/oversized responses. HTTP failures expose sanitized `status_code`, `request_id`, `code`, and `retry_after`; raw server messages and transport exception details are discarded. `RedirectError` and `MigrationError` inherit `HTTPError`. HTTP 410 requires migration; HTTP 429 exposes a validated `Retry-After` seconds or HTTP-date value. No request is retried automatically: admitted generations can consume quota.

## Migration from 0.1

Version 1.0 removes the URL-only `solve` function and `SolveResult`. Replace it with `generate` and caller-prepared scripts (or a material reference), a fresh browser profile, and an exact target request context. Replace duration/status/method/cookie handling with `generation_ms`, `headers`, and `profile_used`. Existing published 0.1 distributions and tags remain unchanged; they target the retired API.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
python -m build
python -m twine check dist/*
```

See [RELEASE.md](RELEASE.md) for release checks. Licensed under [MIT](LICENSE).
