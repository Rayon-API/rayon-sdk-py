from types import SimpleNamespace

import pytest
from rayon_sdk_py.errors import HTTPError
from rayon_sdk_py.validation import response_metadata
from test_sdk import transport

def test_incomplete_generation_explains_loader_and_support_without_assigning_fault():
    error=HTTPError('generic',status_code=422,code='generation_incomplete',
                    reason='generation_incomplete',billing_status='pending',retryable=False)
    assert str(error)=='Generation did not complete.'
    assert 'loader' in error.action
    assert 'For managed material, contact support with the request ID' in error.action
    assert error.retryable is False

KEY = "test-secret-key"


def failure(**extra):
    error = dict(code="access_denied", reason="account_disabled", request_id="req-123", retryable=False,
                 message=f"unsafe {KEY} session=cookie", action=f"unsafe {KEY}") | extra
    response = SimpleNamespace(status_code=403, headers={"Retry-After": "7"})
    return HTTPError("Rayon API returned an unsuccessful HTTP status.",
                     **response_metadata(response, KEY, {"error": error}))


def test_known_reasons_expose_trusted_guidance_and_preserve_metadata():
    error = failure(domain="example.com", field="profile.navigator.userAgent", billing_status="not_charged")
    assert error.reason == "account_disabled"
    assert "disabled" in str(error).lower()
    assert error.action
    assert error.domain == "example.com"
    assert error.field == "profile.navigator.userAgent"
    assert error.billing_status == "not_charged"
    assert error.code == "access_denied"
    assert error.status_code == 403
    assert error.request_id == "req-123"
    assert error.retry_after == "7"
    assert error.retryable is False
    assert "unsafe" not in repr(error.__dict__) + repr(error)
    assert KEY not in repr(error.__dict__) + repr(error)
    assert "session=cookie" not in repr(error.__dict__) + repr(error)


@pytest.mark.parametrize("extra", [dict(reason=None), dict(reason="new_server_reason"), dict(code="invalid_input"), dict(code="constructor")])
def test_legacy_and_unrecognized_pairs_keep_generic_text(extra):
    error = failure(**extra)
    assert str(error) == "Rayon API returned an unsuccessful HTTP status."
    assert error.reason is None
    assert error.action is None
    assert error.billing_status is None


@pytest.mark.parametrize("domain", ["https://example.com/private?token=x", "Example.com", "example.com:443", "x..com", "-bad.com", "example.com\n", f"{KEY}.com", "a" * 254, "127.0.0.1", None, 7])
def test_unsafe_domains_are_omitted(domain):
    assert failure(domain=domain).domain is None


@pytest.mark.parametrize("field", ["profile[secret]", "__proto__.x", "constructor.x", "profile.prototype", f"profile.{KEY}", "a" * 97, "profile\n", "request.cookie=session", None, 7])
def test_unsafe_fields_are_omitted(field):
    assert failure(field=field).field is None


@pytest.mark.parametrize("billing_status", ["charged", True, None, 1, "NOT_CHARGED"])
def test_invalid_billing_status_is_omitted(billing_status):
    assert failure(billing_status=billing_status).billing_status is None


@pytest.mark.parametrize("billing_status", ["not_charged", "pending", "unknown"])
def test_known_billing_status_is_preserved(billing_status):
    assert failure(billing_status=billing_status).billing_status == billing_status


def test_every_catalog_pair_renders_trusted_text_and_safe_domain():
    from rayon_sdk_py.errors import _ERROR_CATALOG
    for reason, entry in _ERROR_CATALOG.items():
        for code in entry["codes"]:
            error = failure(code=code, reason=reason, domain="example.com", retryable=entry["retryable"], billing_status="not_charged")
            assert str(error) == entry["message"].replace("{domain}", "example.com")
            assert error.action == entry["action"]
            assert error.reason == reason
            fallback = failure(code=code, reason=reason, domain="https://secret.invalid/path?cookie=x")
            assert str(fallback) == entry["message"].replace("{domain}", "this domain")
            assert fallback.domain is None


@pytest.mark.parametrize("async_client", [False, True])
def test_public_clients_preserve_guidance_without_retrying(transport, async_client):
    import asyncio
    import rayon_sdk_py as sdk
    from test_sdk import shape
    transport["status"] = 403
    transport["headers"] = {"X-Request-ID": "req-guidance", "Retry-After": "7"}
    transport["body"] = {"error": dict(code="access_denied", reason="domain_pending", domain="example.com",
                                     retryable=False, billing_status="not_charged", message=KEY, action=KEY)}
    async def run():
        async with sdk.AsyncClient(KEY) as client:
            await client.generate(shape())
    with pytest.raises(sdk.HTTPError) as caught:
        if async_client:
            asyncio.run(run())
        else:
            with sdk.Client(KEY) as client:
                client.generate(shape())
    error = caught.value
    assert str(error) == "Access to example.com is awaiting review."
    assert error.reason == "domain_pending"
    assert error.billing_status == "not_charged"
    assert error.request_id == "req-guidance"
    assert error.retry_after == "7"
    assert len(transport["calls"]) == 1


def test_constructor_renders_domain_safely_and_ignores_supplied_action():
    error = HTTPError("generic", code="access_denied", reason="domain_pending", domain="https://bad.invalid/path",
                      field="profile[private]", action="untrusted action")
    assert str(error) == "Access to this domain is awaiting review."
    assert error.domain is None
    assert error.field is None
    assert error.action != "untrusted action"


HISTORY_ACTION = "Check request history before sending another request. Contact support with the request ID if it remains unclear."


@pytest.mark.parametrize("billing_status", [None, "pending", "unknown", "not_charged"])
@pytest.mark.parametrize("retryable", [None, False, True])
def test_retry_guidance_accounts_for_billing_and_explicit_prohibition(billing_status, retryable):
    options = dict(code="generation_unavailable", reason="generation_unavailable", billing_status=billing_status, retryable=retryable)
    expected = HISTORY_ACTION if billing_status != "not_charged" or retryable is False else "Retry with backoff. Contact support with the request ID if this continues."
    assert HTTPError("generic", **options).action == expected
    metadata = response_metadata(SimpleNamespace(status_code=503, headers={}), KEY, {"error": options})
    assert metadata["action"] == expected
    assert HTTPError("generic", **metadata).action == expected


@pytest.mark.parametrize("billing_status", [True, 1, None, "charged", "private-token", {}, []])
def test_direct_constructor_rejects_invalid_billing_status(billing_status):
    error = HTTPError("generic", code="generation_unavailable", reason="generation_unavailable", billing_status=billing_status)
    assert error.billing_status is None
    assert error.action == HISTORY_ACTION


@pytest.mark.parametrize("billing_status", [None, "pending", "unknown", "not_charged"])
@pytest.mark.parametrize("async_client", [False, True])
def test_http_uncertain_outcome_guidance_does_not_replay(billing_status, async_client):
    import asyncio
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    import rayon_sdk_py as sdk
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            error = dict(code="generation_unavailable", reason="generation_unavailable", retryable=True, action="untrusted retry instruction")
            if billing_status is not None:
                error["billing_status"] = billing_status
            body = json.dumps({"error": error}).encode()
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Retry-After", "7")
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    async def run():
        async with sdk.AsyncClient(KEY, base_url=base_url) as client:
            await client.usage()
    try:
        with pytest.raises(sdk.HTTPError) as caught:
            if async_client:
                asyncio.run(run())
            else:
                with sdk.Client(KEY, base_url=base_url) as client:
                    client.usage()
        error = caught.value
        assert error.action == ("Retry with backoff. Contact support with the request ID if this continues." if billing_status == "not_charged" else HISTORY_ACTION)
        assert error.billing_status == billing_status
        assert error.retry_after == "7"
        assert len(calls) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
