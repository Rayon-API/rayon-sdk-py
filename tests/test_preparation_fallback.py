import asyncio

import pytest
import rayon_sdk_py as sdk
from test_sdk import KEY, result, shape, transport


@pytest.mark.parametrize("asynchronous", [False, True])
def test_preparation_fallback_preserves_metadata_without_retry(transport, asynchronous):
    transport["body"] = result(path="isolated", fallback_reason="material_preparing")

    async def run():
        async with sdk.AsyncClient(KEY) as client:
            return await client.generate(shape())

    if asynchronous:
        response = asyncio.run(run())
    else:
        with sdk.Client(KEY) as client:
            response = client.generate(shape())
    assert response.path == "isolated"
    assert response.fallback_reason == "material_preparing"
    assert len(transport["calls"]) == 1
    assert transport["calls"][0][2]["json"] == shape()
    assert transport["calls"][0][2]["headers"]["X-Rayon-Capabilities"] == "managed-fallback-v1"


@pytest.mark.parametrize("metadata", [
    {"path": "isolated"},
    {"path": "isolated", "fallback_reason": "other_reason"},
    {"path": "native", "fallback_reason": "material_preparing"},
    {"fallback_reason": "material_preparing"},
    {"path": "other", "fallback_reason": "material_preparing"},
])
def test_invalid_or_inconsistent_fallback_stays_invalid(transport, metadata):
    transport["body"] = result(**metadata)
    with sdk.Client(KEY) as client:
        with pytest.raises(sdk.InvalidResponseError):
            client.generate(shape())
    assert len(transport["calls"]) == 1
