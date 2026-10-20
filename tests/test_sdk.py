import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from curl_cffi import requests
import rayon_sdk_py as sdk

KEY = "test-secret-key"
URL = "https://example.com/page"


def shape(**changes):
    value = dict(
        source_url=URL,
        scripts=[
            dict(url="https://example.com/owned.js", source="/* owned material */")
        ],
        profile={"language": "en-GB"},
        request=dict(
            url=URL,
            method="POST",
            content_type="application/json",
            body=' {"hello": 1}\n',
        ),
        document_cookie="session=current",
    )
    value.update(changes)
    return value


def result(**changes):
    value = dict(
        headers={
            f"X-Dynamic-{s}": "" if s == "d" else "secret-value" for s in "abcdfz"
        },
        request_id="req-123",
        generation_ms=12,
        profile_used={"language": "en-GB"},
        material_ref="ref_0123456789abcdef",
        material_expires_at=(
            datetime.now(timezone.utc) + timedelta(minutes=1)
        ).isoformat(),
    )
    value.update(changes)
    return value


@pytest.mark.parametrize("reference", ["short", "ref.with.punctuation", "a" * 129])
def test_result_rejects_material_reference_that_cannot_be_reused(transport, reference):
    transport["body"] = result(material_ref=reference)
    with sdk.Client(KEY) as client:
        with pytest.raises(sdk.InvalidResponseError):
            client.generate(shape())


@pytest.fixture
def transport(monkeypatch):
    state = {"calls": [], "options": [], "body": result(), "status": 200, "headers": {}}

    class Session:
        def __init__(self, **options):
            state["options"].append(options)

        def close(self):
            state["closed"] = True

        def request(self, method, url, **options):
            state["calls"].append((method, url, options))
            if state.get("exception"):
                raise state["exception"]
            raw = (
                json.dumps(state["body"]).encode()
                if "raw" not in state
                else state["raw"]
            )
            callback = options["content_callback"]
            if callback(raw) != len(raw):
                raise requests.exceptions.RequestException("secret transport")
            return SimpleNamespace(
                status_code=state["status"], headers=requests.Headers(state["headers"])
            )

    class AsyncSession(Session):
        async def request(self, *args, **kwargs):
            return super().request(*args, **kwargs)

        async def close(self):
            super().close()

    monkeypatch.setattr(requests, "Session", Session)
    monkeypatch.setattr(requests, "AsyncSession", AsyncSession)
    return state


def test_material_contract_and_persistent_fresh_requests(transport):
    with sdk.Client(KEY) as client:
        first = client.generate(shape())
        second = client.generate(
            shape(
                profile={"language": "fr"},
                document_cookie="new",
                request=dict(
                    url=URL, method="PUT", content_type="text/plain", body=" exact\n"
                ),
            )
        )
        client.usage()
        assert isinstance(first, sdk.ShapeResult)
        assert first.headers["X-Dynamic-d"] == ""
        assert "secret-value" not in repr(first)
        assert KEY not in repr(client)
        assert second.generation_ms == 12
    assert transport["closed"]
    assert len(transport["options"]) == 1
    assert "impersonate" not in transport["options"][0]
    assert transport["options"][0]["trust_env"] is False
    method, url, options = transport["calls"][0]
    assert (method, url) == ("POST", "https://api.rayonapi.com/v1/shape")
    assert options["json"] == shape()
    assert options["headers"]["Authorization"] == f"Bearer {KEY}"
    assert options["allow_redirects"] is False
    assert transport["calls"][1][2]["json"]["request"]["body"] == " exact\n"
    assert transport["calls"][1][2]["json"]["profile"] == {"language": "fr"}
    assert transport["calls"][1][2]["json"]["document_cookie"] == "new"
    assert transport["calls"][1][2]["json"]["material_ref"] == "ref_0123456789abcdef"
    assert "scripts" not in transport["calls"][1][2]["json"]
    assert transport["calls"][2][0:2] == ("GET", "https://api.rayonapi.com/v1/usage")


def test_async_lifecycle(transport):
    async def run():
        async with sdk.AsyncClient(KEY) as client:
            assert (await client.generate(shape())).request_id == "req-123"
            await client.usage()

    asyncio.run(run())
    assert transport["closed"]


@pytest.mark.parametrize(
    "change",
    [
        {"scripts": []},
        {"scripts": [{"url": URL, "source": "x"}] * 17},
        {"material_ref": "ref"},
        {"profile": {"unknown": True}},
        {"profile": {"screen": {"width": "wide"}}},
        {"profile": {"navigator": {"unknown": 1}}},
        {"profile": {"window": {"devicePixelRatio": float("nan")}}},
        {"request": {"url": URL, "method": "POST", "content_type": None, "body": {}}},
        {
            "request": {
                "url": URL,
                "method": "POST",
                "content_type": None,
                "body": "x" * (256 * 1024 + 1),
            }
        },
        {"scripts": [{"url": URL, "source": "x" * (3 * 1024 * 1024 + 1)}]},
        {"source_url": "https://user:pass@example.com"},
    ],
)
def test_invalid_shape_before_network(transport, change):
    with pytest.raises(sdk.ValidationError):
        sdk.generate(shape(**change), KEY)
    assert not transport["calls"]


@pytest.mark.parametrize(
    "base",
    [
        "http://remote.example",
        "https://u:p@example.com",
        "https://example.com?key=1",
        "https://example.com#",
        "https:///example.com",
        "https://example.com:0",
    ],
)
def test_unsafe_base(transport, base):
    with pytest.raises(sdk.ValidationError):
        sdk.generate(shape(), KEY, base_url=base)
    assert not transport["calls"]


@pytest.mark.parametrize("status", [301, 307, 401, 410, 429, 503])
def test_error_envelope_sanitized_no_retries(transport, status):
    transport.update(
        status=status,
        body={
            "error": {
                "code": "http_error",
                "message": KEY + " private",
                "request_id": "req-safe",
            }
        },
        headers={"Retry-After": "12"},
    )
    with pytest.raises(sdk.HTTPError) as caught:
        sdk.generate(shape(), KEY)
    assert caught.value.status_code == status
    if status == 410:
        assert type(caught.value) is sdk.HTTPError
        assert str(caught.value) == "Rayon API returned an unsuccessful HTTP status."
    assert caught.value.request_id == "req-safe"
    assert caught.value.retry_after == "12"
    assert KEY not in repr(caught.value)
    assert "private" not in str(caught.value)
    assert len(transport["calls"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"headers": {"X-a": "x"}},
        {"generation_ms": -1},
        {"request_id": KEY},
        {"profile_used": []},
        {"headers": {f"X-{s}": "\n" for s in "abcdfz"}},
    ],
)
def test_invalid_result(transport, change):
    transport["body"] = result(**change)
    with pytest.raises(sdk.InvalidResponseError):
        sdk.generate(shape(), KEY)


def test_bounded_response_and_redacted_transport(transport):
    transport["raw"] = b"x" * (256 * 1024 + 1)
    with pytest.raises(sdk.InvalidResponseError):
        sdk.generate(shape(), KEY)
    transport["exception"] = requests.exceptions.RequestException(KEY)
    with pytest.raises(sdk.TransportError) as caught:
        sdk.generate(shape(), KEY)
    assert KEY not in repr(caught.value)


def test_expired_and_distinct_material_never_reuse_ref(transport):
    transport["body"] = result(material_expires_at="2000-01-01T00:00:00Z")
    with sdk.Client(KEY) as client:
        client.generate(shape())
        client.generate(shape())
        client.generate(shape(scripts=[{"url": URL, "source": "/* different */"}]))
    assert all("scripts" in call[2]["json"] for call in transport["calls"])


def test_generation_clients_and_helper_exported():
    assert callable(sdk.generate)
    assert callable(sdk.Client.generate)
    assert callable(sdk.AsyncClient.generate)


@pytest.mark.parametrize(
    "profile",
    [
        {"canvas": {"data_url": "bad"}},
        {"user_agent": "one", "navigator": {"userAgent": "two"}},
        {"language": "x" * 65536},
        {"screen": {"width": True}},
    ],
)
def test_profile_bounds_and_alias_conflicts(transport, profile):
    with pytest.raises(sdk.ValidationError):
        sdk.generate(shape(profile=profile), KEY)
    assert not transport["calls"]


def test_total_material_bound_and_unicode_encoding(transport):
    scripts = [
        {"url": URL, "source": "x" * (3 * 1024 * 1024)},
        {"url": URL, "source": "y" * (2 * 1024 * 1024)},
    ]
    with pytest.raises(sdk.ValidationError):
        sdk.generate(shape(scripts=scripts), KEY)
    with pytest.raises(sdk.ValidationError):
        sdk.generate(shape(scripts=[{"url": URL, "source": "é" * (800 * 1024)}]), KEY)
    assert not transport["calls"]


@pytest.mark.parametrize("key", [None, "", " ", "key with space", "key\n", "é"])
def test_key_validation(transport, key):
    with pytest.raises(sdk.ValidationError):
        sdk.generate(shape(), key)
    assert not transport["calls"]


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), 2147484])
def test_deadline_validation(transport, timeout):
    with pytest.raises(sdk.ValidationError):
        sdk.generate(shape(), KEY, timeout=timeout)
    assert not transport["calls"]


def test_certificate_validation_remains_enabled_and_api_cookies_discarded(transport):
    sdk.generate(shape(), KEY)
    opts = transport["calls"][0][2]
    assert opts["verify"] is True
    assert opts["discard_cookies"] is True


@pytest.mark.parametrize("body", [b"{", b"x" * (256 * 1024 + 1)])
def test_invalid_usage_response_bounded(transport, body):
    transport["raw"] = body
    with sdk.Client(KEY) as client:
        with pytest.raises(sdk.InvalidResponseError):
            client.usage()


@pytest.mark.parametrize(
    "change",
    [
        {"scripts": [{"url": URL, "source": "x" * (2 * 1024 * 1024 + 1)}]},
        {
            "scripts": [
                {"url": URL, "source": "x" * (2 * 1024 * 1024)},
                {"url": URL, "source": "y" * (1024 * 1024 + 1)},
            ]
        },
        {"document_cookie": "x" * (16 * 1024 + 1)},
        {"profile": {"screen": {"width": 0}}},
        {"profile": {"languages": []}},
        {"profile": {"window": {"devicePixelRatio": 17}}},
        {"profile": {"canvas": {"data_url": "data:image/png;base64,"}}},
        {
            "request": {
                "url": URL,
                "method": "GET",
                "content_type": "application/json",
                "body": "x",
            }
        },
        {"request": {"url": URL, "method": "POST", "content_type": None, "body": "x"}},
        {
            "request": {
                "url": URL,
                "method": "POST",
                "content_type": "application/octet-stream",
                "body": "x",
            }
        },
    ],
)
def test_gateway_contract_limits(transport, change):
    with pytest.raises(sdk.ValidationError):
        sdk.generate(shape(**change), KEY)
    assert not transport["calls"]


def test_real_sync_async_transport_compression_deadline_and_limits():
    import gzip
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            mode = self.server.mode
            if mode == "compressed":
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            try:
                if mode == "slow":
                    self.wfile.write(b"{")
                    self.wfile.flush()
                    time.sleep(0.3)
                elif mode == "oversized":
                    self.wfile.write(b"x" * (256 * 1024 + 1))
                else:
                    self.wfile.write(gzip.compress(json.dumps(result()).encode()))
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.mode = "compressed"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with sdk.Client(KEY, base_url=base, timeout=0.1) as client:
            assert client.generate(shape()).generation_ms == 12
            server.mode = "oversized"
            with pytest.raises(sdk.InvalidResponseError):
                client.generate(shape())
            server.mode = "slow"
            started = time.monotonic()
            with pytest.raises(sdk.TransportError):
                client.generate(shape())
            assert time.monotonic() - started < 0.25

        async def run():
            server.mode = "compressed"
            async with sdk.AsyncClient(KEY, base_url=base, timeout=0.1) as client:
                assert (await client.generate(shape())).generation_ms == 12
                server.mode = "slow"
                started = time.monotonic()
                with pytest.raises(sdk.TransportError):
                    await client.generate(shape())
                assert time.monotonic() - started < 0.25

        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize(
    "field",
    ["screenX", "screenY", "screenLeft", "screenTop", "pageXOffset", "pageYOffset"],
)
@pytest.mark.parametrize("value", [-2147483649, 2147483648])
def test_window_coordinates_reject_int32_overflow(transport, field, value):
    with pytest.raises(sdk.ValidationError):
        sdk.generate(shape(profile={"window": {field: value}}), KEY)
    assert not transport["calls"]


@pytest.mark.parametrize(
    "change",
    [
        {"material_ref": None, "material_expires_at": None},
        {"material_ref": None},
        {"material_expires_at": None},
    ],
)
def test_material_metadata_required_not_null(transport, change):
    transport["body"] = result(**change)
    with pytest.raises(sdk.InvalidResponseError):
        sdk.generate(shape(), KEY)


@pytest.mark.parametrize("field", ["material_ref", "material_expires_at"])
def test_material_metadata_required_not_missing(transport, field):
    del transport["body"][field]
    with pytest.raises(sdk.InvalidResponseError):
        sdk.generate(shape(), KEY)


def test_material_metadata_pair_cannot_both_be_missing(transport):
    del transport["body"]["material_ref"]
    del transport["body"]["material_expires_at"]
    with pytest.raises(sdk.InvalidResponseError):
        sdk.generate(shape(), KEY)


@pytest.mark.parametrize(
    "prefix,value", [("p" * 129, "valid"), ("valid", "é"), ("valid", "a b")]
)
def test_headers_require_bounded_prefix_visible_ascii(transport, prefix, value):
    transport["body"] = result(
        headers={
            f"{prefix}-{suffix}": "" if suffix == "d" else value for suffix in "abcdfz"
        }
    )
    with pytest.raises(sdk.InvalidResponseError):
        sdk.generate(shape(), KEY)


def test_effective_profile_size_accounts_for_defaults_and_aliases(transport):
    profile = {
        "user_agent": "u" * 8192,
        "platform": "p" * 8192,
        "language": "l" * 8192,
        "languages": ["a" * 8192, "b" * 8192, "c" * 8192],
    }
    with pytest.raises(sdk.ValidationError):
        sdk.generate(shape(profile=profile), KEY)
    assert not transport["calls"]


def test_unicode_profile_limit_counts_effective_utf8(transport):
    profile = {"navigator": {"vendor": "é" * 8192, "appName": "é" * 8192}}
    sdk.generate(shape(profile=profile), KEY)
    assert transport["calls"][0][2]["json"]["profile"] == profile


def test_async_deadline_includes_waiting_for_pool_capacity():
    import threading, time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{")
            self.wfile.flush()
            time.sleep(0.4)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def run():
        async with sdk.AsyncClient(
            KEY, base_url=f"http://127.0.0.1:{server.server_port}", timeout=0.1
        ) as client:
            started = time.monotonic()

            async def call():
                with pytest.raises(sdk.TransportError):
                    await client.generate(shape())
                return time.monotonic() - started

            elapsed = await asyncio.gather(*(call() for _ in range(21)))
            assert max(elapsed) < 0.22, elapsed

    try:
        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_shared_canonical_profile_fixtures(transport):
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parent / "fixtures/profile-contract.json").read_text()
    )

    def expand(value):
        if isinstance(value, dict) and "$repeat" in value:
            return value["$repeat"]["text"] * value["$repeat"]["count"]
        if isinstance(value, dict):
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    for case in fixture["cases"]:
        value = shape(profile=expand(case["profile"]))
        if case["valid"]:
            sdk.generate(value, KEY)
        else:
            with pytest.raises(sdk.ValidationError):
                sdk.generate(value, KEY)


@pytest.mark.parametrize("prefix", ["ee30zvqlwf", "p" * 128, "!#$%&'*+-.^_`|~"])
def test_actual_token_prefix_and_maximum_are_preserved(transport, prefix):
    headers = {
        f"{prefix}-{suffix}": "" if suffix == "d" else "visible-value"
        for suffix in "abcdfz"
    }
    transport["body"] = result(headers=headers)
    assert sdk.generate(shape(), KEY).headers == headers


def test_sync_transport_error_does_not_retain_original_exception(transport):
    transport["exception"] = requests.exceptions.RequestException(KEY)
    with pytest.raises(sdk.TransportError) as caught:
        sdk.generate(shape(), KEY)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


def test_async_transport_error_does_not_retain_original_exception(transport):
    transport["exception"] = requests.exceptions.RequestException(KEY)

    async def run():
        async with sdk.AsyncClient(KEY) as client:
            with pytest.raises(sdk.TransportError) as caught:
                await client.generate(shape())
            assert caught.value.__context__ is None
            assert caught.value.__cause__ is None

    asyncio.run(run())


def test_async_timeout_error_does_not_retain_cancelled_task(monkeypatch, transport):
    import rayon_sdk_py.client as module

    async def wait(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(requests.AsyncSession, "request", wait)

    async def run():
        async with sdk.AsyncClient(KEY, timeout=0.01) as client:
            with pytest.raises(sdk.TransportError) as caught:
                await client.generate(shape())
            assert caught.value.__context__ is None
            assert caught.value.__cause__ is None

    asyncio.run(run())


def test_public_profile_preflight_preserves_supplied_fields_and_copies():
    profile = {"navigator": {"vendor": "😀" * 5000}, "window": {"screenX": -2147483648}}
    checked = sdk.validate_profile(profile)
    assert checked == profile
    checked["navigator"]["vendor"] = "changed"
    assert profile["navigator"]["vendor"] == "😀" * 5000
    assert "user_agent" not in checked
    with pytest.raises(sdk.ValidationError) as caught:
        sdk.validate_profile({"window": {"screenX": 2147483648}})
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


def test_public_profile_preflight_matches_all_shared_cases():
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parent / "fixtures/profile-contract.json").read_text()
    )

    def expand(v):
        if isinstance(v, dict) and "$repeat" in v:
            return v["$repeat"]["text"] * v["$repeat"]["count"]
        if isinstance(v, dict):
            return {k: expand(item) for k, item in v.items()}
        if isinstance(v, list):
            return list(map(expand, v))
        return v

    for case in fixture["cases"]:
        value = expand(case["profile"])
        if case["valid"]:
            assert sdk.validate_profile(value) == value
        else:
            with pytest.raises(sdk.ValidationError) as caught:
                sdk.validate_profile(value)
            assert caught.value.__context__ is None
            assert caught.value.__cause__ is None


@pytest.mark.parametrize("mode", ["client", "helper", "async"])
@pytest.mark.parametrize("override", [None, 75])
def test_generation_default_deadline_is_45_seconds_and_overrides_survive(
    transport, mode, override
):
    options = {} if override is None else {"timeout": override}
    if mode == "helper":
        sdk.generate(shape(), KEY, **options)
    elif mode == "client":
        with sdk.Client(KEY, **options) as client:
            client.generate(shape())
            client.usage()
    else:

        async def run():
            async with sdk.AsyncClient(KEY, **options) as client:
                await client.generate(shape())
                await client.usage()

        asyncio.run(run())
    assert all(
        (45 if override is None else override) - .1 < call[2]["timeout"] <= (45 if override is None else override)
        for call in transport["calls"]
    )
