import asyncio
import json
import pytest
import rayon_sdk_py as sdk
from test_sdk import transport, shape, result, KEY

def managed():
    value = shape()
    del value["scripts"]
    return value

def test_automatic_omission_survives_explicit_cache_and_rotation(transport):
    with sdk.Client(KEY) as client:
        client.generate(shape())
        for i in range(3):
            transport["body"] = result(material_ref=f"ref_0123456789abcde{i}")
            client.generate(managed())
    for _, _, options in transport["calls"][1:]:
        body = options["json"]
        assert "scripts" not in body and "material_ref" not in body

def test_async_automatic_and_metadata(transport):
    metadata = dict(path="isolated", material_reuse=False, discovery_duration_ms=12.5, discovery_state="failed", fallback_reason="unknown_material", fallback_message="A fallback was used. Contact support with this request ID.")
    transport["body"] = result(**metadata)
    async def run():
        async with sdk.AsyncClient(KEY) as client:
            for _ in range(2):
                response = await client.generate(managed())
                for key, value in metadata.items():
                    assert getattr(response, key) == value
    asyncio.run(run())
    for _, _, options in transport["calls"]:
        assert "material_ref" not in options["json"]

@pytest.mark.parametrize("extra", [{"scripts":None},{"scripts":[]},{"material_ref":None},{"material_ref":""},{"scripts":[],"material_ref":"ref_0123456789abcdef"},{"mode":"form","request":{"url":"https://shop.example.com/", "method":"POST","content_type":"application/x-www-form-urlencoded","body":"a=b"}}])
def test_invalid_explicit_fields_and_automatic_form(transport, extra):
    with sdk.Client(KEY) as client:
        with pytest.raises(sdk.ValidationError): client.generate({**managed(), **extra})
    assert not transport["calls"]

def test_preparation_still_needs_material(transport):
    with sdk.Client(KEY) as client:
        with pytest.raises(sdk.ValidationError): client.prepare(managed())
    assert not transport["calls"]

@pytest.mark.parametrize("extra", [{"path":"other"},{"material_reuse":1},{"discovery_duration_ms":-1},{"discovery_duration_ms":float("inf")},{"discovery_state":"unsafe detail"},{"fallback_reason":"unsafe detail"},{"fallback_message":"unsafe\nmessage"}])
def test_invalid_operation_metadata(transport, extra):
    transport["body"] = result(**extra)
    with sdk.Client(KEY) as client:
        with pytest.raises(sdk.InvalidResponseError): client.generate(managed())

def test_nullable_metadata_and_zero_duration(transport):
    transport["body"] = result(path="native", material_reuse=True, discovery_duration_ms=0, discovery_state=None, fallback_reason=None)
    with sdk.Client(KEY) as client:
        response=client.generate(managed())
        assert response.discovery_duration_ms == 0 and response.fallback_reason is None

@pytest.mark.parametrize("suffixes", [list("abcdfz"), [*"abcdfz","a0"]])
def test_compact_header_family(transport, suffixes):
    headers={f"Compact{s}":"" if s == "d" else "value" for s in suffixes}
    transport["body"] = result(headers=headers)
    with sdk.Client(KEY) as client: assert client.generate(managed()).headers == headers

def test_inline_material_stays_distinct_in_cache(transport):
    with sdk.Client(KEY) as client:
        for inline in [False,True]:
            value=shape();value["scripts"][0]["inline"]=inline
            client.generate(value)
        for inline in [None,1,"true"]:
            value=shape();value["scripts"][0]["inline"]=inline
            with pytest.raises(sdk.ValidationError):client.generate(value)
    assert [options["json"]["scripts"][0]["inline"] for _,_,options in transport["calls"]] == [False,True]
