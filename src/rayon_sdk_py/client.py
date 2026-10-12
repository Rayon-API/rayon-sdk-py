import asyncio
import hashlib
import json
import time
from datetime import datetime
from typing import Any
from .models import ShapeRequest, ShapeResult
from curl_cffi import CurlOpt, requests
from curl_cffi.curl import CURL_WRITEFUNC_ERROR
from .errors import (
    HTTPError,
    InvalidResponseError,
    MigrationError,
    RedirectError,
    TransportError,
    ValidationError,
)
from .validation import (
    MAX_RESPONSE_BYTES,
    connection,
    parse_result,
    response_metadata,
    validate_shape,
)


class _BaseClient:
    def __init__(self, api_key, *, base_url="https://api.rayonapi.com", timeout=150):
        connection(api_key, base_url, timeout)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._cache = {}
        self._closed = False

    def __repr__(self):
        return f"{type(self).__name__}(credentials=[REDACTED], closed={self._closed})"

    def _shape(self, value):
        if self._closed:
            raise ValidationError("Rayon client is closed.")
        body = validate_shape(value)
        key = None
        if "scripts" in body:
            key = hashlib.sha256(
                json.dumps(
                    [body["source_url"], body["scripts"]],
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            cached = self._cache.get(key)
            if cached and cached[1] > time.time():
                del body["scripts"]
                body["material_ref"] = cached[0]
            elif cached:
                del self._cache[key]
        return body, key

    def _remember(self, key, result):
        if key and result.material_ref and result.material_expires_at:
            expiry = datetime.fromisoformat(
                result.material_expires_at.replace("Z", "+00:00")
            ).timestamp()
            if expiry > time.time():
                if len(self._cache) >= 128:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = (result.material_ref, expiry)

    def _options(self, body):
        content = bytearray()
        state = {"oversized": False}

        def collect(chunk):
            if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                state["oversized"] = True
                return CURL_WRITEFUNC_ERROR
            content.extend(chunk)
            return len(chunk)

        options = dict(
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._timeout,
            allow_redirects=False,
            content_callback=collect,
            verify=True,
            discard_cookies=True,
        )
        if body is not None:
            options["json"] = body
        return options, content, state

    def _decode(self, response, content, state):
        if state["oversized"]:
            raise InvalidResponseError("Rayon API response exceeded the 256 KiB limit.")
        try:
            body = json.loads(bytes(content))
        except (ValueError, UnicodeError, RecursionError):
            body = None
        metadata = response_metadata(response, self._api_key, body)
        if 300 <= response.status_code < 400:
            raise RedirectError(
                "Rayon API returned a redirect; no redirect was followed.", **metadata
            )
        if response.status_code == 410:
            raise MigrationError(
                "This API is retired. Migrate to POST /v1/shape with caller-supplied material.",
                **metadata,
            )
        if response.status_code != 200:
            raise HTTPError(
                "Rayon API returned an unsuccessful HTTP status.", **metadata
            )
        if not isinstance(body, dict):
            raise InvalidResponseError("Rayon API returned invalid JSON.", **metadata)
        return body, metadata

    def _failed(self, state):
        if state["oversized"]:
            raise InvalidResponseError(
                "Rayon API response exceeded the 256 KiB limit."
            ) from None
        raise TransportError("Rayon API request could not be completed.") from None


class Client(_BaseClient):
    """Persistent ordinary-TLS API session. Use as a context manager or close explicitly."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.rayonapi.com",
        timeout: float = 150,
    ):
        super().__init__(api_key, base_url=base_url, timeout=timeout)
        self._session = requests.Session(
            trust_env=False, curl_options={CurlOpt.PROXY: ""}
        )

    def __enter__(self):
        if self._closed:
            raise ValidationError("Rayon client is closed.")
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if not self._closed:
            self._session.close()
            self._cache.clear()
            self._closed = True

    def _send(self, method, path, body=None):
        if self._closed:
            raise ValidationError("Rayon client is closed.")
        options, content, state = self._options(body)
        try:
            response = self._session.request(method, self._base_url + path, **options)
        except requests.exceptions.RequestException:
            self._failed(state)
        return self._decode(response, content, state)

    def generate(self, shape: ShapeRequest) -> ShapeResult:
        body, key = self._shape(shape)
        value, metadata = self._send("POST", "/v1/shape", body)
        result = parse_result(value, metadata, self._api_key)
        self._remember(key, result)
        return result

    def usage(self) -> dict[str, Any]:
        """Read account usage; never invokes a billable generation."""
        value, _ = self._send("GET", "/v1/usage")
        return value


class AsyncClient(_BaseClient):
    """Persistent asynchronous session. Use async with or await aclose()."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.rayonapi.com",
        timeout: float = 150,
    ):
        super().__init__(api_key, base_url=base_url, timeout=timeout)
        self._session = requests.AsyncSession(
            trust_env=False, curl_options={CurlOpt.PROXY: ""}
        )

    async def __aenter__(self):
        if self._closed:
            raise ValidationError("Rayon client is closed.")
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self):
        if not self._closed:
            await self._session.close()
            self._cache.clear()
            self._closed = True

    async def _send(self, method, path, body=None):
        if self._closed:
            raise ValidationError("Rayon client is closed.")
        options, content, state = self._options(body)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout

        async def complete():
            response = await self._session.request(
                method, self._base_url + path, **options
            )
            decoded = self._decode(response, content, state)
            if loop.time() >= deadline:
                raise asyncio.TimeoutError
            return decoded

        try:
            return await asyncio.wait_for(complete(), timeout=self._timeout)
        except (asyncio.TimeoutError, requests.exceptions.RequestException):
            self._failed(state)

    async def generate(self, shape: ShapeRequest) -> ShapeResult:
        body, key = self._shape(shape)
        value, metadata = await self._send("POST", "/v1/shape", body)
        result = parse_result(value, metadata, self._api_key)
        self._remember(key, result)
        return result

    async def usage(self) -> dict[str, Any]:
        value, _ = await self._send("GET", "/v1/usage")
        return value


def generate(
    shape: ShapeRequest,
    api_key: str,
    *,
    base_url: str = "https://api.rayonapi.com",
    timeout: float = 150,
) -> ShapeResult:
    """One-shot helper. Reuse Client for connection pooling and material-reference caching."""
    with Client(api_key, base_url=base_url, timeout=timeout) as client:
        return client.generate(shape)
