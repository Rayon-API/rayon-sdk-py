# Rayon Python SDK

A synchronous client for `POST /solve` on the Rayon API. Python 3.10 or newer is required.

Version `0.1.0` is prepared locally; it has **not yet been published to PyPI**.
From a checkout, install with:

```sh
python -m pip install .
```

After the first PyPI release, installation will be:

```sh
python -m pip install rayon-sdk-py
```

```python
import os
from rayon_sdk_py import solve

result = solve(
    "https://example.com/page",
    os.environ["RAYON_API_KEY"],
    # Optional JSON fingerprint values:
    profile={"user_agent": "your browser user agent"},
)
print(result.status, result.method, result.duration_ms)
```

`solve(target_url, api_key, *, profile=None, base_url="https://api.rayonapi.com", timeout=150)`
performs one request using curl_cffi Chrome impersonation. Timeout is a finite positive
number of seconds. The SDK disables redirects and environment proxies, and never retries.
Decoded response bodies are limited to 2 MiB; larger responses stop the transfer
and raise `InvalidResponseError`.
Custom API endpoints require HTTPS; HTTP is supported only for `localhost`, `127.0.0.1`,
or `[::1]` development endpoints. URLs cannot contain credentials or fragments;
the API base URL also cannot contain a query.

The request body contains only `target_url` and, when supplied, `profile`.
The API key is sent as a Bearer authorization header. Use an account and target
domain approved for your application.

An accepted result contains exactly one six-header family with a variable prefix
and the suffixes `a`, `b`, `c`, `d`, `f`, and `z`; `d` may be empty.
Acceptance means the headers were captured. It does not mean the target website
verified them. `result.errors` can contain diagnostics from earlier solver tiers
even when a fallback succeeds.

`SolveResult` exposes `status`, `method`, `target_url`, `duration_ms`, `headers`,
`cookies`, `profile_used`, and `errors`. Headers, cookies, URL, profile, and diagnostics
are excluded from its repr because replay data can be sensitive.

Cookies remain a list of records with required string fields `name`, `value`,
`domain`, and `path`. Extra JSON metadata is preserved. Cookie scope matters:
do not flatten cookies into a name/value dictionary. The SDK does not invent
`secure`, expiry, or other browser attributes absent from the API response.
When replaying a result, preserve cookie domains and paths and use the returned
`profile_used` values for a compatible browser fingerprint.

```python
from curl_cffi.requests import Cookies

jar = Cookies()
for cookie in result.cookies:
    jar.set(cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"])
# result.headers, jar, and result.profile_used are available for your replay client.
```

Handle failures explicitly:

```python
import os
from rayon_sdk_py import HTTPError, RayonError, SolveFailedError, solve

try:
    result = solve("https://example.com/page", os.environ["RAYON_API_KEY"])
except SolveFailedError as exc:
    # HTTP 200 with a failed/rejected result also raises.
    print(exc.result.status)
except HTTPError as exc:
    print(exc.status_code, exc.request_id, exc.retry_after)
except RayonError as exc:
    print(str(exc))
```

All SDK errors inherit from `RayonError`. `ValidationError` is raised before
network access; `TransportError` covers network failures; `RedirectError` is an
`HTTPError`; `InvalidResponseError` covers invalid JSON or malformed responses.
Exception messages do not include response bodies, credentials, or underlying
transport messages. HTTP response errors expose `status_code`, `request_id`, and
`retry_after` (a validated seconds or HTTP date header string, when present).
Invalid diagnostic headers or values reflecting the API key are discarded.
Decide whether and when
to retry in your application; admitted solve attempts can consume quota.

For local development:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
python -m build
python -m twine check dist/*
```

Tests are offline and patch the transport. CI tests Python 3.10, 3.12, and 3.14
and builds the wheel and source distribution. See [RELEASE.md](RELEASE.md) for
the pending trusted publisher setup. Licensed under [MIT](LICENSE).
