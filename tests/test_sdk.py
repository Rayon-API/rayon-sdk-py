import importlib

import pytest
from curl_cffi import requests


TARGET = "https://example.com/page"
KEY = "rayon_test_secret"


def accepted(**changes):
    body = {
        "status": "accepted",
        "method": "playwright",
        "target_url": TARGET,
        "duration_ms": 123,
        "headers": {f"X-RandomPrefix-{suffix}": "" if suffix == "d" else f"secret-{suffix}"
                    for suffix in "abcdfz"},
        "cookies": [{"name": "session", "value": "cookie-secret", "domain": ".example.com", "path": "/page"}],
        "profile_used": {"user_agent": "profile-secret"},
        "errors": ["Earlier tier failed"],
    }
    body.update(changes)
    return body


class Response:
    def __init__(self, body=None, status=200, headers=None):
        self.body = accepted() if body is None else body
        self.status_code = status
        self.headers = requests.Headers(headers or {})

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


@pytest.fixture
def sdk():
    try:
        return importlib.import_module("rayon_sdk_py")
    except ModuleNotFoundError:
        pytest.fail("The public SDK module is not implemented")


@pytest.fixture
def transport(monkeypatch):
    state = {"response": Response(), "calls": [], "session_options": []}

    class Session:
        def __init__(self, **options):
            state["session_options"].append(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            state["closed"] = True

        def post(self, url, **options):
            state["calls"].append((url, options))
            if "exception" in state:
                raise state["exception"]
            for chunk in state.get("chunks", []):
                callback = options.get("content_callback")
                if callback is not None and callback(chunk) != len(chunk):
                    state["aborted"] = True
                    raise requests.exceptions.RequestException("Body callback aborted")
            return state["response"]

    monkeypatch.setattr(requests, "Session", Session)
    return state


def test_solve_sends_only_public_body_and_returns_accepted_fallback(transport):
    try:
        sdk = importlib.import_module("rayon_sdk_py")
    except ModuleNotFoundError:
        pytest.fail("The public SDK module is not implemented")
    profile = {"user_agent": "Chrome"}
    result = sdk.solve(TARGET, KEY, profile=profile)
    assert isinstance(result, sdk.SolveResult)
    assert result.status == "accepted"
    assert result.errors == ["Earlier tier failed"]
    assert result.headers["X-RandomPrefix-d"] == ""
    assert result.cookies == accepted()["cookies"]
    assert result.profile_used == accepted()["profile_used"]
    url, options = transport["calls"][0]
    assert url == "https://api.rayonapi.com/solve"
    assert options["json"] == {"target_url": TARGET, "profile": profile}
    assert options["headers"]["Authorization"] == f"Bearer {KEY}"
    assert options["timeout"] == 150
    assert options["allow_redirects"] is False
    assert transport["session_options"][0]["trust_env"] is False
    assert transport["session_options"][0]["impersonate"] == "chrome"
    assert transport["closed"]


def test_defaults_omit_profile_and_custom_base_is_supported(sdk, transport):
    sdk.solve(TARGET, KEY, base_url="http://localhost:8080/api/", timeout=2.5)
    url, options = transport["calls"][0]
    assert url == "http://localhost:8080/api/solve"
    assert options["json"] == {"target_url": TARGET}
    assert options["timeout"] == 2.5


def test_result_repr_hides_replay_credentials(sdk, transport):
    result = sdk.solve(TARGET, KEY)
    assert all(secret not in repr(result) for secret in (KEY, "cookie-secret", "profile-secret", "secret-a"))


@pytest.mark.parametrize("target", [None, "", "ftp://example.com", "https:///page", "https://u:p@example.com", "https://example.com\n", "https://example.com:bad", "https://example.com/#fragment"])
def test_invalid_target_never_reaches_network(sdk, transport, target):
    with pytest.raises(sdk.ValidationError):
        sdk.solve(target, KEY)
    assert not transport["calls"]


@pytest.mark.parametrize("key", [None, "", " ", "key\r\nx: value", "key with space", "é"])
def test_invalid_api_key_never_reaches_network(sdk, transport, key):
    with pytest.raises(sdk.ValidationError):
        sdk.solve(TARGET, key)
    assert not transport["calls"]


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), None, True, "10"])
def test_invalid_timeout_never_reaches_network(sdk, transport, timeout):
    with pytest.raises(sdk.ValidationError):
        sdk.solve(TARGET, KEY, timeout=timeout)
    assert not transport["calls"]


@pytest.mark.parametrize("base", [None, "", "ftp://example.com", "http://example.com", "https://u:p@example.com", "https://example.com?key=secret", "https://example.com#fragment", "https://example.com\t", "https://example.com:bad"])
def test_invalid_base_url_never_reaches_network(sdk, transport, base):
    with pytest.raises(sdk.ValidationError):
        sdk.solve(TARGET, KEY, base_url=base)
    assert not transport["calls"]


@pytest.mark.parametrize("profile", [[], {"bad": object()}, {"bad": float("nan")}, {"profile": "bad"}, {1: "bad"}, {"nested": {1: "bad"}}])
def test_invalid_profile_never_reaches_network(sdk, transport, profile):
    with pytest.raises(sdk.ValidationError):
        sdk.solve(TARGET, KEY, profile=profile)
    assert not transport["calls"]


@pytest.mark.parametrize("status", [401, 403, 422, 429, 503])
def test_http_errors_are_safe_and_expose_diagnostics(sdk, transport, status):
    transport["response"] = Response({"secret": KEY}, status, {"X-Request-ID": "req-123", "Retry-After": "30"})
    with pytest.raises(sdk.HTTPError) as caught:
        sdk.solve(TARGET, KEY)
    error = caught.value
    assert error.status_code == status
    assert error.request_id == "req-123"
    assert error.retry_after == "30"
    assert KEY not in str(error) + repr(error)
    assert len(transport["calls"]) == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_are_typed_and_not_followed(sdk, transport, status):
    transport["response"] = Response(status=status, headers={"Location": f"https://example.com/{KEY}"})
    with pytest.raises(sdk.RedirectError) as caught:
        sdk.solve(TARGET, KEY)
    assert caught.value.status_code == status
    assert KEY not in str(caught.value)
    assert len(transport["calls"]) == 1


def test_network_failure_is_typed_safe_and_not_retried(sdk, transport):
    transport["exception"] = requests.exceptions.RequestException(f"Authorization: {KEY}")
    with pytest.raises(sdk.TransportError) as caught:
        sdk.solve(TARGET, KEY)
    assert KEY not in str(caught.value) + repr(caught.value)
    assert caught.value.__cause__ is None
    assert len(transport["calls"]) == 1


@pytest.mark.parametrize("failure", [ValueError, UnicodeError, RecursionError])
def test_invalid_json_is_typed_safe(sdk, transport, failure):
    transport["response"] = Response(failure(KEY))
    with pytest.raises(sdk.InvalidResponseError) as caught:
        sdk.solve(TARGET, KEY)
    assert KEY not in str(caught.value)
    assert caught.value.__cause__ is None


def test_cookie_scope_and_extra_metadata_are_preserved(sdk, transport):
    cookies = [
        {"name": "session", "value": "first", "domain": "example.com", "path": "/"},
        {"name": "session", "value": "second", "domain": ".example.com", "path": "/page", "future": {"flag": True}},
    ]
    transport["response"] = Response(accepted(cookies=cookies))
    result = sdk.solve(TARGET, KEY)
    assert result.cookies == cookies
    assert all("secure" not in cookie and "expiry" not in cookie for cookie in result.cookies)


def test_header_family_is_case_insensitive_and_prefix_is_variable(sdk, transport):
    headers = {f"Telemetry_9-{suffix}": "" if suffix == "D" else "value" for suffix in "ABCDfZ"}
    transport["response"] = Response(accepted(headers=headers))
    assert sdk.solve(TARGET, KEY).headers == headers


def test_cycle_in_profile_is_a_validation_error(sdk, transport):
    profile = {}
    profile["nested"] = profile
    with pytest.raises(sdk.ValidationError):
        sdk.solve(TARGET, KEY, profile=profile)
    assert not transport["calls"]


@pytest.mark.parametrize("status", ["failed", "rejected"])
def test_nonaccepted_200_throws_solve_failure(sdk, transport, status):
    transport["response"] = Response(accepted(status=status, headers={}, errors=[KEY]))
    with pytest.raises(sdk.SolveFailedError) as caught:
        sdk.solve(TARGET, KEY)
    assert caught.value.result.status == status
    assert caught.value.result.errors == [KEY]
    assert KEY not in str(caught.value) + repr(caught.value) + repr(caught.value.result)


@pytest.mark.parametrize("changes", [
    {"status": "unexpected"}, {"method": "none"}, {"target_url": "https://different.example/"},
    {"duration_ms": -1}, {"duration_ms": True}, {"duration_ms": 1.5},
    {"headers": {"X-Prefix-a": "a"}}, {"headers": {f"X-Prefix-{s}": "" for s in "abcdfz"}},
    {"headers": {**accepted()["headers"], "X-Other-a": "a"}},
    {"headers": {**accepted()["headers"], "X-RandomPrefix-a": 1}},
    {"headers": {**accepted()["headers"], "X-RandomPrefix-a": "a\r\nBad: value"}},
    {"cookies": {}}, {"cookies": [{"name": "n", "value": "v"}]},
    {"cookies": [{"name": "n", "value": 1, "domain": "example.com", "path": "/"}]},
    {"profile_used": []}, {"errors": "error"}, {"errors": [1]},
])
def test_malformed_response_is_rejected(sdk, transport, changes):
    transport["response"] = Response(accepted(**changes))
    with pytest.raises(sdk.InvalidResponseError):
        sdk.solve(TARGET, KEY)


def test_missing_response_fields_are_not_synthesized(sdk, transport):
    body = accepted()
    del body["cookies"]
    transport["response"] = Response(body)
    with pytest.raises(sdk.InvalidResponseError):
        sdk.solve(TARGET, KEY)


def test_actual_curl_adapter_disables_environment_proxy_without_network(sdk, monkeypatch):
    from curl_cffi import Curl, CurlError, CurlOpt

    options = []
    original = Curl.setopt

    def setopt(curl, option, value):
        options.append((option, value))
        return original(curl, option, value)

    def perform(curl):
        raise CurlError("Network disabled by test", code=7)

    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setattr(Curl, "setopt", setopt)
    monkeypatch.setattr(Curl, "perform", perform)
    with pytest.raises(sdk.TransportError):
        sdk.solve(TARGET, KEY)
    assert (CurlOpt.PROXY, "") in options
    assert (CurlOpt.FOLLOWLOCATION, 0) in options


@pytest.mark.parametrize("request_id,retry_after", [
    (KEY, KEY), ("prefix-" + KEY, "30\r\nBad: value"),
    ("x" * 129, "99999999999"), ("id\nsecret", "tomorrow"),
    ("Bearer secret", "Fri, 99 Oct 2026 00:00:00 GMT"),
])
def test_http_diagnostics_drop_reflected_credentials_and_invalid_headers(sdk, transport, request_id, retry_after):
    transport["response"] = Response(status=429, headers={"X-Request-ID": request_id, "Retry-After": retry_after})
    with pytest.raises(sdk.HTTPError) as caught:
        sdk.solve(TARGET, KEY)
    assert caught.value.request_id is None
    assert caught.value.retry_after is None
    assert KEY not in str(caught.value.__dict__)


def test_valid_http_date_retry_after_is_preserved(sdk, transport):
    value = "Mon, 12 Oct 2026 10:00:00 GMT"
    transport["response"] = Response(status=429, headers={"Retry-After": value})
    with pytest.raises(sdk.HTTPError) as caught:
        sdk.solve(TARGET, KEY)
    assert caught.value.retry_after == value


def test_oversized_decoded_response_aborts_before_collecting_more(sdk, transport):
    transport["chunks"] = [b'x' * (1024 * 1024), b'y' * (1024 * 1024), b'z', KEY.encode()]
    with pytest.raises(sdk.InvalidResponseError) as caught:
        sdk.solve(TARGET, KEY)
    assert transport.get("aborted") is True
    assert KEY not in str(caught.value)


def test_actual_adapter_body_callback_limits_decoded_bytes_and_preserves_timeout(sdk, monkeypatch):
    from curl_cffi import Curl, CurlError, CurlOpt

    options = {}
    original = Curl.setopt

    def setopt(curl, option, value):
        options[option] = value
        return original(curl, option, value)

    def perform(curl):
        callback = options.get(CurlOpt.WRITEFUNCTION)
        if callable(callback):
            assert callback(b'x' * (2 * 1024 * 1024)) == 2 * 1024 * 1024
            assert callback(KEY.encode()) != len(KEY)
        raise CurlError("Write aborted: " + KEY, code=23)

    monkeypatch.setattr(Curl, "setopt", setopt)
    monkeypatch.setattr(Curl, "perform", perform)
    with pytest.raises(sdk.InvalidResponseError) as caught:
        sdk.solve(TARGET, KEY)
    assert callable(options[CurlOpt.WRITEFUNCTION])
    assert options[CurlOpt.TIMEOUT_MS] == 150_000
    assert KEY not in str(caught.value)


def test_actual_adapter_parses_json_from_multiple_decoded_chunks(sdk, monkeypatch):
    import json
    from curl_cffi import Curl, CurlOpt

    options = {}
    original = Curl.setopt
    payload = json.dumps(accepted()).encode()

    def setopt(curl, option, value):
        options[option] = value
        return original(curl, option, value)

    def perform(curl):
        callback = options[CurlOpt.WRITEFUNCTION]
        assert callback(payload[:30]) == 30
        assert callback(payload[30:]) == len(payload) - 30

    def parse_response(*args, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.headers = requests.Headers({"X-Request-ID": "req-123"})
        return response

    monkeypatch.setattr(Curl, "setopt", setopt)
    monkeypatch.setattr(Curl, "perform", perform)
    monkeypatch.setattr(requests.Session, "_parse_response", parse_response)
    result = sdk.solve(TARGET, KEY)
    assert result.headers == accepted()["headers"]
    assert result.cookies == accepted()["cookies"]
