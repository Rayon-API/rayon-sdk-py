import asyncio

import pytest
import rayon_sdk_py as sdk
from rayon_sdk_py.validation import parse_result
from test_sdk import KEY, result, shape, transport


def headers():
    return {
        f"Exact-Base-{s}": "" if s == "d" else "original-value"
        for s in "abcdfz"
    } | {"eXACT-bASE-A0": "fresh-supplement+/%="}


@pytest.mark.parametrize("explicit_mode", [False, True])
def test_optional_a0_preserves_all_original_names_and_values(transport, explicit_mode):
    expected = headers()
    transport["body"] = result(headers=expected)
    request = shape(**({"mode": "header"} if explicit_mode else {}))
    generated = sdk.generate(request, KEY)
    assert generated.headers == expected
    assert "fresh-supplement" not in repr(generated)


def test_optional_a0_is_fresh_when_material_is_reused(transport):
    async def run():
        async with sdk.AsyncClient(KEY) as client:
            transport["body"] = result(headers=headers())
            first = await client.generate(shape())
            transport["body"]["headers"]["eXACT-bASE-A0"] = "next-fresh-value"
            second = await client.generate(shape())
            assert first.headers["eXACT-bASE-A0"] == "fresh-supplement+/%="
            assert second.headers["eXACT-bASE-A0"] == "next-fresh-value"
        assert transport["calls"][1][2]["json"]["material_ref"] == first.material_ref
        assert "scripts" not in transport["calls"][1][2]["json"]
        assert "headers" not in transport["calls"][1][2]["json"]

    asyncio.run(run())


@pytest.mark.parametrize("suffix", list("abcdfz"))
def test_optional_a0_never_replaces_a_required_header(suffix):
    value = headers()
    del value[f"Exact-Base-{suffix}"]
    with pytest.raises(sdk.InvalidResponseError):
        parse_result(result(headers=value), {}, KEY)


@pytest.mark.parametrize(
    "extra",
    [
        {"Other-a0": "value"},
        {"Exact-Base-a1": "value"},
        {"Exact-Base-A": "value"},
        {"Exact-Base-a0": "duplicate"},
        {"eXACT-bASE-A0": ""},
        {"eXACT-bASE-A0": "a b"},
        {"eXACT-bASE-A0": "unsafe\r\n"},
        {"eXACT-bASE-A0": "é"},
        {"Exact-Base-a0\n": "value"},
        {"eXACT-bASE-A0": 123},
        {"p" * 129 + "-a0": "value"},
    ],
)
def test_optional_a0_rejects_invalid_families_duplicates_and_values(extra):
    value = headers()
    if "Exact-Base-a0" not in extra:
        del value["eXACT-bASE-A0"]
    with pytest.raises(sdk.InvalidResponseError):
        parse_result(result(headers=value | extra), {}, KEY)


def test_optional_a0_obeys_the_response_byte_limit(transport):
    transport["body"] = result(headers=headers() | {"eXACT-bASE-A0": "x" * (256 * 1024)})
    with pytest.raises(sdk.InvalidResponseError):
        sdk.generate(shape(), KEY)


@pytest.mark.parametrize("prefix", ["CuKtomer", "Cuſtomer", "Cuıstomer", "Cuİstomer"])
@pytest.mark.parametrize("optional_a0", [False, True])
def test_header_family_names_require_ascii_tokens(prefix, optional_a0):
    suffixes = list("abcdfz") + (["A0"] if optional_a0 else [])
    value = {f"{prefix}-{suffix}": "" if suffix == "d" else "value" for suffix in suffixes}
    with pytest.raises(sdk.InvalidResponseError):
        parse_result(result(headers=value), {}, KEY)
