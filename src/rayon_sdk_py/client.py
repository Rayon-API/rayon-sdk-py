import asyncio
import hashlib
import json
import time
import threading
from datetime import datetime
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
        self._cache = {}
        self._cache_bytes = 0
        self._material_lock = threading.Lock()
        self._flights = {}
        self._closed = False

    def __repr__(self):
        return f"{type(self).__name__}(credentials=[REDACTED], closed={self._closed})"

    def _shape(self, value):
        if self._closed:
            raise ValidationError("Rayon client is closed.")
        body = validate_shape(value)
        scripts = body.get("scripts")
        key = None
        if scripts is not None:
            key = hashlib.sha256(json.dumps(
                [body["source_url"], scripts], sort_keys=True,
                ensure_ascii=False, separators=(",", ":"),
            ).encode()).hexdigest()
        elif "material_ref" in body:
            with self._material_lock:
                for candidate, cached in self._cache.items():
                    if (cached["ref"] == body["material_ref"]
                            and cached["source_url"] == body["source_url"]):
                        key, scripts = candidate, cached["scripts"]
                        break
        return body, key, scripts

    def _select_material(self, body, key, scripts, factory):
        """Claim one upload; other callers wait without sharing generation results."""
        if key is None:
            return None, False
        with self._material_lock:
            if self._closed:
                raise ValidationError("Rayon client is closed.")
            if key in self._flights:
                return self._flights[key], False
            cached = self._cache.get(key)
            if cached and cached["expires"] > time.time() + 5:
                body.pop("scripts", None)
                body["material_ref"] = cached["ref"]
                return None, False
            body.pop("material_ref", None)
            body["scripts"] = scripts
            # Retained coordination is bounded; existing flights still coalesce.
            flight = factory() if len(self._flights) < 128 else None
            if flight is not None:
                self._flights[key] = flight
            return flight, True

    def _remember(self, key, scripts, body, result):
        # Reference generations cannot extend TTL or undo a confirmed miss.
        if key is None or "scripts" not in body:
            return
        expiry = datetime.fromisoformat(result.material_expires_at.replace("Z", "+00:00")).timestamp()
        with self._material_lock:
            if self._closed:
                return
            previous = self._cache.get(key)
            size = len(json.dumps([body["source_url"], scripts], ensure_ascii=False).encode())
            if size > 16 * 1024 * 1024:
                return
            if previous:
                self._cache_bytes -= previous["size"]
                del self._cache[key]
            while self._cache and (len(self._cache) >= 128 or self._cache_bytes + size > 16 * 1024 * 1024):
                oldest = self._cache.pop(next(iter(self._cache)))
                self._cache_bytes -= oldest["size"]
            self._cache[key] = dict(ref=result.material_ref, expires=expiry,
                source_url=body["source_url"], scripts=scripts, size=size)
            self._cache_bytes += size

    def _invalidate(self, key, reference):
        with self._material_lock:
            cached = self._cache.get(key)
            if cached and cached["ref"] == reference:
                cached["expires"] = 0

    @staticmethod
    def _recoverable(error, body, scripts):
        return (scripts is not None and "material_ref" in body
                and isinstance(error, HTTPError) and error.status_code == 422
                and error.code == "material_expired" and error.billing_status == "not_charged")

    def _finish_flight(self, key, flight, success):
        if flight is None:
            return
        with self._material_lock:
            if self._flights.get(key) is flight:
                del self._flights[key]
            if isinstance(flight, threading.Event):
                flight.success = success
                flight.set()
            elif not flight.done():
                flight.set_result(success)

    def _clear_material(self):
        with self._material_lock:
            self._closed = True
            self._cache.clear()
            self._cache_bytes = 0
            for flight in self._flights.values():
                if isinstance(flight, threading.Event):
                    flight.success = False
                    flight.set()
                elif not flight.done():
                    flight.set_result(False)
            self._flights.clear()

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
            self._clear_material()
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

    def generate(
        self, shape: ShapeRequest | FormShapeRequest
    ) -> ShapeResult | FormShapeResult:
        body, key, scripts = self._shape(shape)
        recovered = False
        deadline = time.monotonic() + self._timeout
        while True:
            flight, owner = self._select_material(body, key, scripts, threading.Event)
            if flight is not None and not owner:
                if not flight.wait(max(0, deadline - time.monotonic())) or not flight.success:
                    raise TransportError("Rayon material establishment could not be completed.")
                continue
            success = False
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportError("Rayon API request could not be completed.")
                value, metadata = self._send("POST", "/v1/shape", body, timeout=remaining)
                result = parse_result(value, metadata, self._api_key, body.get("mode", "header"))
                self._remember(key, scripts, body, result)
                success = True
                return result
            except HTTPError as error:
                if recovered or not self._recoverable(error, body, scripts):
                    raise
                self._invalidate(key, body["material_ref"])
                recovered = True
            finally:
                self._finish_flight(key, flight, success)

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
            self._clear_material()
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

    async def generate(
        self, shape: ShapeRequest | FormShapeRequest
    ) -> ShapeResult | FormShapeResult:
        body, key, scripts = self._shape(shape)
        recovered = False
        deadline = asyncio.get_running_loop().time() + self._timeout
        while True:
            flight, owner = self._select_material(body, key, scripts,
                asyncio.get_running_loop().create_future)
            if flight is not None and not owner:
                failed = False
                try:
                    ready = await asyncio.wait_for(asyncio.shield(flight),
                        timeout=max(0, deadline - asyncio.get_running_loop().time()))
                    failed = not ready
                except asyncio.TimeoutError:
                    failed = True
                if failed:
                    raise TransportError("Rayon material establishment could not be completed.")
                continue
            success = False
            try:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TransportError("Rayon API request could not be completed.")
                value, metadata = await self._send("POST", "/v1/shape", body, timeout=remaining)
                result = parse_result(value, metadata, self._api_key, body.get("mode", "header"))
                self._remember(key, scripts, body, result)
                success = True
                return result
            except HTTPError as error:
                if recovered or not self._recoverable(error, body, scripts):
                    raise
                self._invalidate(key, body["material_ref"])
                recovered = True
            finally:
                self._finish_flight(key, flight, success)

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
