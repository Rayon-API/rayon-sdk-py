import asyncio
import json
import time
import pytest
import rayon_sdk_py as sdk
from test_sdk import KEY, shape, transport

ID = "prep_0123456789abcdef"
def frame(state="ready", **changes):
    value = dict(preparation_id=ID, state=state, status_url=f"/v1/materials/preparations/{ID}",
        retry_after_ms=0, preparation_expires_at="2099-01-01T00:00:00Z", material_ref="ref_0123456789abcdef",
        material_expires_at="2099-01-01T00:00:00Z", ready_until="2099-01-01T00:00:00Z" if state == "ready" else None,
        execution_backend="rust" if state == "ready" else None, error={"code":"preparation_failed"} if state in ("failed", "expired") else None)
    value.update(changes)
    return value

def test_prepare_has_explicit_post_full_context_unique_idempotency_and_no_generation(transport):
    transport.update(body=frame("queued"), status=202)
    with sdk.Client(KEY) as client:
        first = client.prepare(shape())
        second = client.prepare(shape(profile={"language":"fr"}))
    assert first.state == second.state == "queued"
    calls = transport["calls"]
    assert len(calls) == 2
    assert all(c[0:2] == ("POST", "https://api.rayonapi.com/v1/materials/prepare") for c in calls)
    assert calls[0][2]["json"] == shape()
    keys = [c[2]["headers"]["Idempotency-Key"] for c in calls]
    assert keys[0] != keys[1] and all(len(k) >= 16 for k in keys)
    assert "owned material" not in repr(first) and KEY not in repr(first)

@pytest.mark.parametrize("changes", [{"state":"unknown"}, {"status_url":"https://evil.example/job"},
    {"scripts":[]}, {"retry_after_ms":float("nan")}, {"retry_after_ms":60001}, {"execution_backend":None},
    {"preparation_id":"bad"}, {"material_expires_at":"yesterday"}, {"error":{"message":"secret"}}])
def test_preparation_rejects_unsafe_or_invalid_frames(transport, changes):
    transport["body"] = frame(**changes)
    with sdk.Client(KEY) as client, pytest.raises(sdk.InvalidResponseError):
        client.prepare(shape())

@pytest.mark.parametrize("raw", [b'{"state":"queued","state":"ready"}', b'{"state":NaN}', b'\xff'])
def test_preparation_rejects_duplicate_nonfinite_and_invalid_utf8(transport, raw):
    transport["raw"] = raw
    with sdk.Client(KEY) as client, pytest.raises(sdk.InvalidResponseError):
        client.get_preparation(ID)

def test_wait_is_bounded_terminal_and_resumable(transport, monkeypatch):
    transport["body"] = frame("queued")
    with sdk.Client(KEY) as client:
        started = time.monotonic()
        with pytest.raises(sdk.PreparationError) as caught:
            client.wait_until_ready(ID, wait_timeout=.02)
        assert caught.value.kind == "timeout" and caught.value.preparation_id == ID
        assert time.monotonic() - started < .2
        transport["body"] = frame("failed")
        with pytest.raises(sdk.PreparationError) as caught:
            client.wait_until_ready(ID)
        assert caught.value.kind == "failed"
        transport["body"] = frame()
        assert isinstance(client.wait_until_ready(ID), sdk.ReadyMaterial)
    assert all(c[1].startswith(f"https://api.rayonapi.com/v1/materials/preparations/{ID}?wait=") for c in transport["calls"])

def test_async_prepare_wait_and_cancellation(transport):
    async def run():
        transport["body"] = frame()
        async with sdk.AsyncClient(KEY) as client:
            assert isinstance(await client.prepare_and_wait(shape()), sdk.ReadyMaterial)
            transport["body"] = frame("queued", retry_after_ms=10000)
            task = asyncio.create_task(client.wait_until_ready(ID))
            await asyncio.sleep(.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError) as caught:
                await task
            assert caught.value.preparation_id == ID
    asyncio.run(run())

def test_get_rejects_path_injection_before_request(transport):
    with sdk.Client(KEY) as client, pytest.raises(sdk.ValidationError):
        client.get_preparation("../other")
    assert not transport["calls"]

@pytest.mark.parametrize('state', ['queued', 'learning', 'validating', 'publishing', 'ready', 'failed', 'expired'])
def test_all_preparation_states_and_terminal_error_sanitization(transport, state):
    transport['body'] = frame(state)
    if state in ('failed', 'expired'):
        transport['body']['error'] = {'code': 'preparation_failed', 'reason': 'untrusted_reason', 'action': 'PRIVATE SOURCE', 'retryable': False}
    with sdk.Client(KEY) as client:
        value = client.get_preparation(ID)
        assert value.state == state
        assert 'PRIVATE SOURCE' not in repr(value)
        assert 'untrusted_reason' not in repr(value)

@pytest.mark.parametrize('changes', [
    {'ready_until':'2099-02-30T00:00:00Z'},
    {'preparation_expires_at':'2099-02-30T00:00:00Z'},
    {'error':{'code':'preparation_failed','retryable':None}},
    {'error':{'code':'preparation_failed','action':None}},
    {'error':{'code':'preparation_failed','reason':None}},
    {'error':None},
])
def test_terminal_preparation_response_is_strict_and_errors_resume(transport, changes):
    transport['body'] = frame('failed', **changes)
    with sdk.Client(KEY) as client, pytest.raises(sdk.InvalidResponseError) as caught:
        client.wait_until_ready(ID)
    assert caught.value.preparation_id == ID

@pytest.mark.parametrize('is_async', [False, True])
def test_wait_retries_only_transient_get_and_preserves_deadline(transport, monkeypatch, is_async):
    calls = []
    def send(method, path, body=None, **options):
        calls.append((method, path, options))
        if len(calls) == 1:
            raise sdk.HTTPError('safe', status_code=503)
        return frame(), {}
    async def async_send(*args, **kwargs):
        return send(*args, **kwargs)
    async def run():
        async with sdk.AsyncClient(KEY) as client:
            monkeypatch.setattr(client, '_send', async_send)
            return await client.wait_until_ready(ID, wait_timeout=.5)
    if is_async:
        value = asyncio.run(run())
    else:
        with sdk.Client(KEY) as client:
            monkeypatch.setattr(client, '_send', send)
            value = client.wait_until_ready(ID, wait_timeout=.5)
    assert isinstance(value, sdk.ReadyMaterial)
    assert len(calls) == 2 and all(c[0] == 'GET' for c in calls)
    assert 0 < calls[1][2]['timeout'] < calls[0][2]['timeout'] <= .5

@pytest.mark.parametrize('status', [400, 401, 403, 404, 422])
def test_wait_does_not_retry_permanent_get_failures(transport, status):
    transport.update(status=status, body={'error':{'code':'preparation_unknown'}})
    with sdk.Client(KEY) as client, pytest.raises(sdk.HTTPError) as caught:
        client.wait_until_ready(ID)
    assert caught.value.preparation_id == ID
    assert len(transport['calls']) == 1

def test_prepare_never_retries_ambiguous_post(transport):
    transport.update(status=503, body={'error':{'code':'preparation_unavailable'}})
    with sdk.Client(KEY) as client, pytest.raises(sdk.HTTPError):
        client.prepare(shape())
    assert len(transport['calls']) == 1

def test_get_rejects_202(transport):
    transport.update(status=202, body=frame('queued'))
    with sdk.Client(KEY) as client, pytest.raises(sdk.HTTPError):
        client.get_preparation(ID)

def test_ids_containing_credentials_are_rejected_without_retention_or_requests(transport):
    ident = 'prep_' + KEY + '_0123456789'
    with sdk.Client(KEY) as client:
        for operation in (client.get_preparation, client.wait_until_ready):
            with pytest.raises(sdk.ValidationError) as caught:
                operation(ident)
            assert KEY not in repr(caught.value) and not hasattr(caught.value, 'preparation_id')
    assert not transport['calls']

def test_terminal_wait_error_preserves_safe_code_and_retryability(transport):
    transport['body'] = frame('failed', error={'code':'preparation_failed', 'retryable':False})
    with sdk.Client(KEY) as client, pytest.raises(sdk.PreparationError) as caught:
        client.wait_until_ready(ID)
    assert caught.value.code == 'preparation_failed' and caught.value.retryable is False

@pytest.mark.parametrize('error', [
    {'code':'preparation_failed','reason':'r'*129},
    {'code':'preparation_failed','action':'a'*2049},
])
def test_preparation_error_string_bounds(transport, error):
    transport['body'] = frame('failed', error=error)
    with sdk.Client(KEY) as client, pytest.raises(sdk.InvalidResponseError):
        client.get_preparation(ID)
