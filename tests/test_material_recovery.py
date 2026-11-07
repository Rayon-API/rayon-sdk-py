"""Generation never refreshes sources or starts a preparation job."""
import asyncio
import pytest
import rayon_sdk_py as sdk
from test_sdk import KEY, shape, explicit_shape, result, transport

@pytest.mark.parametrize("asynchronous", [False, True])
def test_source_generation_rejected_before_network(transport, asynchronous):
    async def run():
        async with sdk.AsyncClient(KEY) as client:
            with pytest.raises(sdk.ValidationError): await client.generate(explicit_shape())
    if asynchronous: asyncio.run(run())
    else:
        with sdk.Client(KEY) as client:
            with pytest.raises(sdk.ValidationError): client.generate(explicit_shape())
    assert not transport["calls"]

@pytest.mark.parametrize("code,status", [("material_expired",422),("material_not_prepared",409),("capacity_exceeded",429)])
def test_generation_failure_never_uploads_sources_or_retries(transport, code, status):
    transport.update(status=status,body={"error":{"code":code,"billing_status":"not_charged"}})
    with sdk.Client(KEY) as client:
        with pytest.raises(sdk.HTTPError): client.generate(shape())
    assert len(transport["calls"]) == 1
    assert "scripts" not in transport["calls"][0][2]["json"]

@pytest.mark.parametrize("metadata", [{"path":"isolated"},{"fallback_reason":"unknown_material"}])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_unexpected_fallback_is_not_retried(transport, metadata, asynchronous):
    transport["body"] = result(**metadata)
    transport["headers"] = {"X-Request-ID": "req-123"}
    async def run():
        async with sdk.AsyncClient(KEY) as client:
            with pytest.raises(sdk.InvalidResponseError) as caught:
                await client.generate(shape())
        return caught.value
    if asynchronous:
        error = asyncio.run(run())
    else:
        with sdk.Client(KEY) as client:
            with pytest.raises(sdk.InvalidResponseError) as caught:
                client.generate(shape())
        error = caught.value
    assert error.request_id == "req-123"
    assert error.status_code == 200
    assert len(transport["calls"]) == 1
