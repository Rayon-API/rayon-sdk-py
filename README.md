# Rayon Python SDK

Synchronous and asynchronous clients for `POST /v1/shape` and `GET /v1/usage`.
Python 3.10+ is required. Keep your API key on your server.

[Documentation](https://docs.rayonapi.com/) · [Releases](https://github.com/Rayon-API/rayon-sdk-py/releases)

## Install

```sh
python -m pip install 'rayon-sdk-py>=1,<2'
```

## Generate headers

Prepare the full protection scripts from your authorized integration, in execution order.
URLs supply context; the SDK and API do not download them.

```python
import json
import os
from pathlib import Path
from rayon_sdk_py import Client, ShapeRequest

shape: ShapeRequest = {
    "source_url": "https://example.com/page",
    "scripts": [{
        "url": "https://example.com/assets/owned.js",
        "source": Path("owned.js").read_text(encoding="utf-8"),
    }],
    "profile": json.loads(Path("owned-profile.json").read_text(encoding="utf-8")),
    "request": {
        "url": "https://example.com/api/items",
        "method": "POST",
        "content_type": "application/json",
        "body": '{"item":1}',
    },
}
with Client(os.environ["RAYON_API_KEY"]) as client:
    result = client.generate(shape)
    # Apply result.headers with your own target client and session.
```

Use exactly one of `scripts` or a server-issued `material_ref`, with its original `source_url`.
Capture a fresh profile from your browser; `validate_profile(profile)` provides offline validation.
Keep the target URL, method, content type and body exact. GET/HEAD use `body=None`.
See [material preparation](https://docs.rayonapi.com/material) and [profiles and sessions](https://docs.rayonapi.com/profiles-and-sessions).

Persistent clients reuse unexpired material references. A failed reference is never automatically retried.
To replace an invalid cached reference before expiry, use a fresh client with your saved scripts.
No generation is automatically retried; admitted requests may consume account credit.
Results contain six site-specific headers and material metadata. No target cookies are returned.
Your target client maintains its own session and transport; generation does not guarantee target acceptance.

`client.usage()` reads account usage. `generate()` is a one-shot helper; `RayonError` is the base error.
`AsyncClient` supports `async with`, `await client.generate(shape)` and `await client.usage()`.
See the [API reference](https://docs.rayonapi.com/api-reference), [errors](https://docs.rayonapi.com/errors) and [migration guide](https://docs.rayonapi.com/migration).

[Support](mailto:support@rayonapi.com) · [Discord](https://discord.gg/TwhkJNyHWs) · [MIT license](LICENSE)
