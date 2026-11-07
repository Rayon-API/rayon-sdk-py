import asyncio
import json
from typing import Any, overload
from .preparation import SyncPreparation, AsyncPreparation, strict_loads
from .models import ShapeRequest, ShapeResult, FormShapeResult, FormShapeRequest
from curl_cffi import CurlOpt, requests
from curl_cffi.curl import CURL_WRITEFUNC_ERROR
from .errors import (
    HTTPError,
    InvalidResponseError,
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
    def __init__(self, api_key, *, base_url="https://api.rayonapi.com", timeout=45):
        connection(api_key, base_url, timeout)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._closed = False

    def __repr__(self):
        return f"{type(self).__name__}(credentials=[REDACTED], closed={self._closed})"







    def _mark_closed(self):
        self._closed = True

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

    def _decode(self, response, content, state, *, preparation=False):
        if state["oversized"]:
            raise InvalidResponseError("Rayon API response exceeded the 256 KiB limit.")
        try:
            body = strict_loads(content) if preparation else json.loads(bytes(content))
        except (ValueError, UnicodeError, RecursionError):
            body = None
        metadata = response_metadata(response, self._api_key, body)
        if 300 <= response.status_code < 400:
            raise RedirectError(
                "Rayon API returned a redirect; no redirect was followed.", **metadata
            )
        if response.status_code != 200 and not (preparation == "POST" and response.status_code == 202):
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


class Client(SyncPreparation, _BaseClient):
    """Persistent ordinary-TLS API session. Use as a context manager or close explicitly."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.rayonapi.com",
        timeout: float = 45,
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
            self._mark_closed()
            self._session.close()

    def _send(self, method, path, body=None, *, timeout=None, headers=None, preparation=False):
        if self._closed:
            raise ValidationError("Rayon client is closed.")
        options, content, state = self._options(body)
        if headers:
            options["headers"].update(headers)
        budget = self._timeout if timeout is None else timeout
        if budget <= 0:
            raise TransportError("Rayon API request could not be completed.")
        options["timeout"] = budget
        failed = False
        try:
            response = self._session.request(method, self._base_url + path, **options)
        except requests.exceptions.RequestException:
            failed = True
        if failed:
            self._failed(state)
        return self._decode(response, content, state, preparation=method if preparation else False)

    @overload
    def generate(self, shape: ShapeRequest) -> ShapeResult: ...

    @overload
    def generate(self, shape: FormShapeRequest) -> FormShapeResult: ...

    def generate(self, shape: ShapeRequest | FormShapeRequest) -> ShapeResult | FormShapeResult:
        if self._closed:
            raise ValidationError("Rayon client is closed.")
        body = validate_shape(shape)
        value, metadata = self._send("POST", "/v1/shape", body)
        if not isinstance(value, dict) or value.get("path") not in (None, "native") or value.get("fallback_reason") is not None:
            raise InvalidResponseError("Unexpected generation response; check request history before retrying.", **metadata)
        return parse_result(value, metadata, self._api_key, body.get("mode", "header"))

    def usage(self) -> dict[str, Any]:
        """Read account usage; never invokes a billable generation."""
        value, _ = self._send("GET", "/v1/usage")
        return value


class AsyncClient(AsyncPreparation, _BaseClient):
    """Persistent asynchronous session. Use async with or await aclose()."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.rayonapi.com",
        timeout: float = 45,
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
            self._mark_closed()
            await self._session.close()

    async def _send(self, method, path, body=None, *, timeout=None, headers=None, preparation=False):
        if self._closed:
            raise ValidationError("Rayon client is closed.")
        options, content, state = self._options(body)
        if headers:
            options["headers"].update(headers)
        budget = self._timeout if timeout is None else timeout
        if budget <= 0:
            raise TransportError("Rayon API request could not be completed.")
        options["timeout"] = budget
        loop = asyncio.get_running_loop()
        deadline = loop.time() + budget

        async def complete():
            response = await self._session.request(
                method, self._base_url + path, **options
            )
            decoded = self._decode(response, content, state, preparation=method if preparation else False)
            if loop.time() >= deadline:
                raise asyncio.TimeoutError
            return decoded

        failed = False
        try:
            decoded = await asyncio.wait_for(complete(), timeout=budget)
        except (asyncio.TimeoutError, requests.exceptions.RequestException):
            failed = True
        if failed:
            self._failed(state)
        return decoded

    @overload
    async def generate(self, shape: ShapeRequest) -> ShapeResult: ...

    @overload
    async def generate(self, shape: FormShapeRequest) -> FormShapeResult: ...

    async def generate(self, shape: ShapeRequest | FormShapeRequest) -> ShapeResult | FormShapeResult:
        if self._closed:
            raise ValidationError("Rayon client is closed.")
        body = validate_shape(shape)
        value, metadata = await self._send("POST", "/v1/shape", body)
        if not isinstance(value, dict) or value.get("path") not in (None, "native") or value.get("fallback_reason") is not None:
            raise InvalidResponseError("Unexpected generation response; check request history before retrying.", **metadata)
        return parse_result(value, metadata, self._api_key, body.get("mode", "header"))

    async def usage(self) -> dict[str, Any]:
        value, _ = await self._send("GET", "/v1/usage")
        return value


@overload
def generate(
    shape: ShapeRequest,
    api_key: str,
    *,
    base_url: str = "https://api.rayonapi.com",
    timeout: float = 45,
) -> ShapeResult: ...


@overload
def generate(
    shape: FormShapeRequest,
    api_key: str,
    *,
    base_url: str = "https://api.rayonapi.com",
    timeout: float = 45,
) -> FormShapeResult: ...


def generate(
    shape: ShapeRequest | FormShapeRequest,
    api_key: str,
    *,
    base_url: str = "https://api.rayonapi.com",
    timeout: float = 45,
) -> ShapeResult | FormShapeResult:
    """One-shot helper. Reuse Client for connection pooling and material-reference caching."""
    with Client(api_key, base_url=base_url, timeout=timeout) as client:
        return client.generate(shape)
