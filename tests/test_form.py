import copy
import pytest
import rayon_sdk_py as sdk
from rayon_sdk_py.validation import validate_shape, parse_result
from test_sdk import shape, result, transport, KEY


def form_shape(**changes):
    return shape(
        mode="form",
        form={"id": "checkout", "name": "checkout"},
        request={
            "url": "https://example.com/submit",
            "method": "POST",
            "content_type": "application/x-www-form-urlencoded; charset=UTF-8",
            "body": "tag=first&tag=second&csrf=a%2Bb&empty=",
        },
        **changes,
    )


def form_result(**changes):
    fields = {f"ExactBase{s}": "" if s == "d" else "opaque +/é~" for s in "zafbdc"}
    value = result(
        form_fields=fields,
        form_body="&".join(
            f"{k}=" + ("" if k.endswith("d") else "opaque+%2B%2F%C3%A9%7E")
            for k in fields
        ),
    )
    del value["headers"]
    value.update(changes)
    return value


def test_form_roundtrip_preserves_encoding_case_order_and_application_body(transport):
    transport["body"] = form_result()
    request = form_shape()
    with sdk.Client(KEY) as client:
        output = client.generate(request)
    assert isinstance(output, sdk.FormShapeResult)
    assert list(output.form_fields) == ["ExactBase" + s for s in "zafbdc"]
    assert output.form_body == transport["body"]["form_body"]
    assert not hasattr(output, "headers")
    assert transport["calls"][0][2]["json"] == request
    assert "opaque" not in repr(output)


@pytest.mark.parametrize(
    "mutation",
    [
        {"mode": "other"},
        {"mode": None},
        {"mode": "header"},
        {"form": {"id": "bad\n"}},
        {"form": {"html": "<form>"}},
    ],
)
def test_invalid_form_metadata(mutation):
    value = form_shape()
    value.update(mutation)
    with pytest.raises(sdk.ValidationError):
        validate_shape(value)


@pytest.mark.parametrize(
    "changes",
    [
        {"method": "GET"},
        {"content_type": "application/json"},
        {"content_type": "application/x-www-form-urlencoded; charset=latin1"},
        {"body": None},
        {"body": "a=%"},
        {"body": "a=%GG"},
        {"body": "a=%FF"},
        {"body": "a=%00"},
        {"body": "&".join(f"Base{s}=old" for s in "abcdfz")},
    ],
)
def test_form_input_rejects_invalid_transport_encoding_and_stale_family(changes):
    value = form_shape()
    value["request"].update(changes)
    with pytest.raises(sdk.ValidationError):
        validate_shape(value)


def test_empty_form_body_is_valid():
    value = form_shape()
    value["request"]["body"] = ""
    assert validate_shape(value) == value


@pytest.mark.parametrize(
    "mutation",
    [
        {"form_body": "inconsistent=x"},
        {"headers": result()["headers"]},
        {"form_fields": {"Base" + s: "x" for s in "abcdf"}},
        {"form_fields": {"Base" + s: "x" for s in "abcdfZ"}},
        {"form_fields": {"Base" + s: "x" for s in "abcdf"} | {"Otherz": "x"}},
        {"form_fields": {"Base" + s: "\n" for s in "abcdfz"}},
    ],
)
def test_form_result_validation_is_safe(mutation):
    with pytest.raises(sdk.InvalidResponseError) as exc:
        parse_result(form_result(**mutation), {}, KEY, "form")
    assert "opaque" not in str(exc.value)


def test_transport_mismatch_is_rejected():
    with pytest.raises(sdk.InvalidResponseError):
        parse_result(form_result(), {}, KEY)
    with pytest.raises(sdk.InvalidResponseError):
        parse_result(result(), {}, KEY, "form")


@pytest.mark.parametrize(
    "body",
    ["x=" + "a" * 262144, "&".join(["x=1"] * 1025), "é" * 129 + "=x", "x=\ud800"],
)
def test_form_application_limits(body):
    value = form_shape()
    value["request"]["body"] = body
    with pytest.raises(sdk.ValidationError):
        validate_shape(value)


def test_application_duplicate_state_newlines_and_partial_families_survive():
    value = form_shape()
    value["request"][
        "body"
    ] = "tag=1&tag=2&notes=line%0Aline%0D%09&Basea=application&basez=application"
    assert validate_shape(value) == value


@pytest.mark.parametrize(
    "fields",
    [
        {"Base" + s: "x" for s in "abcdf"} | {"basez": "x"},
        {"Base" + s: "x" for s in "abcdf"} | {"Baseaa": "x"},
        {"x" * 129 + s: "x" for s in "abcdfz"},
        {"Base" + s: "x" * 16385 for s in "abcdfz"},
        {"Base" + s: "" for s in "abcdfz"},
    ],
)
def test_form_result_family_and_value_limits(fields):
    with pytest.raises(sdk.InvalidResponseError):
        parse_result(form_result(form_fields=fields), {}, KEY, "form")


def test_public_form_request_type():
    assert sdk.FormShapeRequest.__required_keys__ >= {
        "mode",
        "source_url",
        "request",
        "profile",
    }


def test_form_mode_reuses_only_material_and_keeps_fresh_body(transport):
    transport["body"] = form_result()
    with sdk.Client(KEY) as client:
        first = client.generate(form_shape())
        value = form_shape()
        value["request"]["body"] = "tag=fresh&csrf=current"
        second = client.generate(value)
    sent = transport["calls"][1][2]["json"]
    assert sent["mode"] == "form"
    assert sent["request"]["body"] == "tag=fresh&csrf=current"
    assert sent["material_ref"] == first.material_ref
    assert "scripts" not in sent
    assert second is not first


def test_async_form_response_and_mode_check(transport):
    import asyncio

    async def run():
        async with sdk.AsyncClient(KEY) as client:
            transport["body"] = form_result()
            output = await client.generate(form_shape())
            assert isinstance(output, sdk.FormShapeResult)
            transport["body"] = result()
            with pytest.raises(sdk.InvalidResponseError):
                await client.generate(form_shape())

    asyncio.run(run())
