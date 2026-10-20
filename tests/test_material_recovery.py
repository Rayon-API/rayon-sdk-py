import asyncio
import copy
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
import rayon_sdk_py as sdk
from test_sdk import KEY, shape, result, transport


def expired():
    return sdk.HTTPError('safe', status_code=422, code='material_expired', billing_status='not_charged')


@pytest.mark.parametrize('reference_only', [False, True])
def test_confirmed_miss_uploads_original_once_with_current_context(transport, monkeypatch, reference_only):
    with sdk.Client(KEY) as client:
        first = client.generate(shape())
        calls = []
        def send(method, path, body, **kwargs):
            calls.append(copy.deepcopy(body))
            if len(calls) == 1:
                raise expired()
            return result(), {}
        monkeypatch.setattr(client, '_send', send)
        current = shape(document_cookie='current', profile={'language': 'fr'})
        if reference_only:
            del current['scripts']
            current['material_ref'] = first.material_ref
        client.generate(current)
    assert len(calls) == 2
    assert 'material_ref' in calls[0] and 'scripts' not in calls[0]
    assert calls[1]['scripts'] == shape()['scripts']
    assert 'material_ref' not in calls[1]
    assert calls[1]['document_cookie'] == 'current'
    assert calls[1]['profile'] == {'language': 'fr'}


@pytest.mark.parametrize('failure', [
    sdk.HTTPError('safe', status_code=422, code='material_expired'),
    sdk.HTTPError('safe', status_code=422, code='material_expired', billing_status='pending'),
    sdk.HTTPError('safe', status_code=500, code='generation_failed', billing_status='not_charged'),
    sdk.TransportError('safe'), sdk.InvalidResponseError('safe'),
])
def test_ambiguous_and_other_failures_are_never_retried(transport, monkeypatch, failure):
    with sdk.Client(KEY) as client:
        client.generate(shape())
        calls = []
        def send(*args, **kwargs):
            calls.append(args)
            raise failure
        monkeypatch.setattr(client, '_send', send)
        with pytest.raises(type(failure)):
            client.generate(shape())
        assert len(calls) == 1


def test_material_miss_recovery_is_limited_to_one_attempt(transport, monkeypatch):
    with sdk.Client(KEY) as client:
        client.generate(shape())
        calls = []
        def send(*args, **kwargs):
            calls.append(args)
            raise expired()
        monkeypatch.setattr(client, '_send', send)
        with pytest.raises(sdk.HTTPError):
            client.generate(shape())
        assert len(calls) == 2


def test_refresh_before_expiry_and_defensive_original_copy(transport, monkeypatch):
    source = shape()
    transport['body'] = result(material_expires_at=(datetime.now(timezone.utc)+timedelta(seconds=3)).isoformat())
    with sdk.Client(KEY) as client:
        client.generate(source)
        source['scripts'][0]['source'] = 'caller changed'
        client.generate(shape())
    assert all('scripts' in call[2]['json'] for call in transport['calls'])


def test_sync_initial_material_upload_is_coalesced(transport, monkeypatch):
    with sdk.Client(KEY) as client:
        calls = []
        entered, release = threading.Event(), threading.Event()
        def send(method, path, body, **kwargs):
            calls.append(copy.deepcopy(body))
            if 'scripts' in body:
                entered.set()
                assert release.wait(2)
            return result(), {}
        monkeypatch.setattr(client, '_send', send)
        failures = []
        def run():
            try: client.generate(shape())
            except BaseException as error: failures.append(error)
        threads = [threading.Thread(target=run) for _ in range(8)]
        for thread in threads: thread.start()
        assert entered.wait(1)
        time.sleep(.03)
        release.set()
        for thread in threads: thread.join(2)
        assert not failures
        assert len(calls) == 8
        assert sum('scripts' in body for body in calls) == 1


def test_async_initial_upload_and_waiter_cancellation_are_isolated(transport, monkeypatch):
    async def run():
        async with sdk.AsyncClient(KEY) as client:
            calls = []
            entered, release = asyncio.Event(), asyncio.Event()
            async def send(method, path, body, **kwargs):
                calls.append(copy.deepcopy(body))
                if 'scripts' in body:
                    entered.set()
                    await release.wait()
                return result(), {}
            monkeypatch.setattr(client, '_send', send)
            leader = asyncio.create_task(client.generate(shape()))
            await entered.wait()
            waiter = asyncio.create_task(client.generate(shape()))
            survivor = asyncio.create_task(client.generate(shape()))
            await asyncio.sleep(.01)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError): await waiter
            release.set()
            await asyncio.gather(leader, survivor)
            assert len(calls) == 2
            assert sum('scripts' in body for body in calls) == 1
    asyncio.run(run())


def test_cache_retention_is_bounded_and_client_scoped(transport):
    with sdk.Client(KEY) as client:
        for i in range(140):
            client.generate(shape(scripts=[{'url': 'https://example.com/owned.js', 'source': str(i)}]))
        assert len(client._cache) <= 128
    with sdk.Client(KEY) as client:
        client.generate(shape())
    assert 'scripts' in transport['calls'][-1][2]['json']


def test_async_confirmed_simultaneous_misses_share_one_refresh(transport, monkeypatch):
    async def run():
        async with sdk.AsyncClient(KEY) as client:
            await client.generate(shape())
            calls = []
            misses = 0
            all_missed = asyncio.Event()
            async def send(method, path, body, **kwargs):
                nonlocal misses
                calls.append(copy.deepcopy(body))
                if body.get('material_ref') == 'ref_0123456789abcdef':
                    misses += 1
                    if misses == 6: all_missed.set()
                    await all_missed.wait()
                    raise expired()
                if 'scripts' in body:
                    await asyncio.sleep(.02)
                return result(material_ref='ref_fedcba9876543210'), {}
            monkeypatch.setattr(client, '_send', send)
            await asyncio.wait_for(asyncio.gather(*(client.generate(shape(document_cookie=str(i))) for i in range(6))), 2)
            assert sum('scripts' in body for body in calls) == 1
            assert len(calls) == 12
    asyncio.run(run())


def test_async_leader_failure_does_not_issue_waiter_generation(transport, monkeypatch):
    async def run():
        async with sdk.AsyncClient(KEY) as client:
            calls = []
            entered, release = asyncio.Event(), asyncio.Event()
            async def send(method, path, body, **kwargs):
                calls.append(body)
                entered.set()
                await release.wait()
                raise sdk.TransportError('safe')
            monkeypatch.setattr(client, '_send', send)
            first = asyncio.create_task(client.generate(shape()))
            await entered.wait()
            waiter = asyncio.create_task(client.generate(shape()))
            await asyncio.sleep(.01)
            release.set()
            failures = await asyncio.gather(first, waiter, return_exceptions=True)
            assert all(isinstance(error, sdk.TransportError) for error in failures)
            assert len(calls) == 1
    asyncio.run(run())


def test_late_old_success_cannot_restore_reference_during_refresh(transport, monkeypatch):
    async def run():
        async with sdk.AsyncClient(KEY) as client:
            await client.generate(shape())
            old_started, old_release = asyncio.Event(), asyncio.Event()
            upload_started, upload_release = asyncio.Event(), asyncio.Event()
            calls = []
            async def send(method, path, body, **kwargs):
                calls.append(copy.deepcopy(body))
                if body['document_cookie'] == 'old':
                    old_started.set()
                    await old_release.wait()
                    return result(), {}
                if 'scripts' in body:
                    upload_started.set()
                    await upload_release.wait()
                    return result(material_ref='ref_fedcba9876543210'), {}
                if body.get('material_ref') == 'ref_0123456789abcdef':
                    raise expired()
                return result(material_ref='ref_fedcba9876543210'), {}
            monkeypatch.setattr(client, '_send', send)
            old = asyncio.create_task(client.generate(shape(document_cookie='old')))
            await old_started.wait()
            refresh = asyncio.create_task(client.generate(shape(document_cookie='refresh')))
            await upload_started.wait()
            old_release.set()
            await old
            follower = asyncio.create_task(client.generate(shape(document_cookie='follower')))
            await asyncio.sleep(.01)
            assert not any(body['document_cookie'] == 'follower' for body in calls)
            upload_release.set()
            await asyncio.gather(refresh, follower)
            assert calls[-1]['material_ref'] == 'ref_fedcba9876543210'
    asyncio.run(run())


def test_byte_budget_eviction_does_not_recover_with_discarded_source(transport):
    with sdk.Client(KEY) as client:
        for i in range(18):
            transport['body'] = result(material_ref=f'ref_{i:016d}')
            client.generate(shape(scripts=[{'url': 'https://example.com/owned.js', 'source': 'x' * (1024 * 1024) + str(i)}]))
        transport['status'] = 422
        transport['body'] = {'error': {'code': 'material_expired', 'billing_status': 'not_charged'}}
        current = shape(material_ref='ref_0000000000000000')
        del current['scripts']
        before = len(transport['calls'])
        with pytest.raises(sdk.HTTPError):
            client.generate(current)
        assert len(transport['calls']) == before + 1


@pytest.mark.parametrize('asynchronous', [False, True])
def test_recovery_uses_one_overall_generation_deadline(transport, monkeypatch, asynchronous):
    async def run_async():
        async with sdk.AsyncClient(KEY, timeout=.08) as client:
            await client.generate(shape())
            calls = []
            async def send(method, path, body, *, timeout=None):
                budget = .08 if timeout is None else timeout
                calls.append(budget)
                await asyncio.sleep(min(.05, budget))
                if budget < .05: raise sdk.TransportError('safe')
                if len(calls) == 1: raise expired()
                return result(), {}
            monkeypatch.setattr(client, '_send', send)
            with pytest.raises(sdk.TransportError): await client.generate(shape())
            assert len(calls) == 2 and calls[1] < .05
    if asynchronous:
        asyncio.run(run_async())
    else:
        with sdk.Client(KEY, timeout=.08) as client:
            client.generate(shape())
            calls = []
            def send(method, path, body, *, timeout=None):
                budget = .08 if timeout is None else timeout
                calls.append(budget)
                time.sleep(min(.05, budget))
                if budget < .05: raise sdk.TransportError('safe')
                if len(calls) == 1: raise expired()
                return result(), {}
            monkeypatch.setattr(client, '_send', send)
            with pytest.raises(sdk.TransportError): client.generate(shape())
            assert len(calls) == 2 and calls[1] < .05


@pytest.mark.parametrize('asynchronous', [False, True])
def test_material_wait_and_send_share_one_deadline(transport, monkeypatch, asynchronous):
    async def run_async():
        async with sdk.AsyncClient(KEY, timeout=.08) as client:
            entered = asyncio.Event()
            async def send(method, path, body, *, timeout=None):
                budget = .08 if timeout is None else timeout
                entered.set()
                await asyncio.sleep(min(.05, budget))
                if budget < .05: raise sdk.TransportError('safe')
                return result(), {}
            monkeypatch.setattr(client, '_send', send)
            leader = asyncio.create_task(client.generate(shape()))
            await entered.wait()
            with pytest.raises(sdk.TransportError): await client.generate(shape())
            await leader
    if asynchronous:
        asyncio.run(run_async())
    else:
        with sdk.Client(KEY, timeout=.08) as client:
            entered = threading.Event()
            failures = []
            def send(method, path, body, *, timeout=None):
                budget = .08 if timeout is None else timeout
                entered.set()
                time.sleep(min(.05, budget))
                if budget < .05: raise sdk.TransportError('safe')
                return result(), {}
            monkeypatch.setattr(client, '_send', send)
            def first():
                try: client.generate(shape())
                except BaseException as error: failures.append(error)
            leader = threading.Thread(target=first)
            leader.start()
            assert entered.wait(1)
            with pytest.raises(sdk.TransportError): client.generate(shape())
            leader.join(1)
            assert not failures
