import json
import math
import re
from datetime import datetime
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urlsplit
from .errors import InvalidResponseError, ValidationError
from .models import ShapeResult

MAX_RESPONSE_BYTES = 256 * 1024


def valid_url(value, *, base=False):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 8192
        or any(ord(c) <= 32 or ord(c) == 127 for c in value)
        or "\\" in value
        or "#" in value
    ):
        return False
    if not re.match(r"^https?://[^/?#]+", value) or "@" in value.split("/", 3)[2]:
        return False
    try:
        p = urlsplit(value)
        return (
            p.scheme in {"http", "https"}
            and bool(p.hostname)
            and p.username is None
            and p.password is None
            and (p.port is None or 0 < p.port <= 65535)
            and (
                not base
                or (
                    "?" not in value
                    and (
                        p.scheme == "https"
                        or p.hostname in {"localhost", "127.0.0.1", "::1"}
                    )
                )
            )
        )
    except ValueError:
        return False


def connection(api_key, base_url, timeout):
    if (
        not isinstance(api_key, str)
        or not api_key
        or any(not 33 <= ord(c) <= 126 for c in api_key)
    ):
        raise ValidationError("api_key must be a nonempty ASCII token.")
    if not valid_url(base_url, base=True):
        raise ValidationError(
            "base_url must be HTTPS or local HTTP without credentials, query, or fragment."
        )
    try:
        valid = (
            type(timeout) in (int, float)
            and math.isfinite(timeout)
            and 0 < timeout <= 2147483.647
        )
    except OverflowError:
        valid = False
    if not valid:
        raise ValidationError(
            "timeout must be finite positive seconds within the supported deadline."
        )


def json_copy(value):
    def visit(v, seen):
        if v is None or type(v) in (str, bool, int):
            return
        if type(v) is float and math.isfinite(v):
            return
        if type(v) not in (dict, list) or id(v) in seen:
            raise ValueError
        seen.add(id(v))
        try:
            if isinstance(v, dict):
                for k, item in v.items():
                    if not isinstance(k, str) or k in {
                        "__proto__",
                        "constructor",
                        "prototype",
                    }:
                        raise ValueError
                    visit(item, seen)
            else:
                for item in v:
                    visit(item, seen)
        finally:
            seen.remove(id(v))

    visit(value, set())
    return json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False))


def byte_size(value):
    return len(
        json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    )


def profile_valid(profile):
    fields = {
        "user_agent": str,
        "platform": str,
        "language": str,
        "languages": list,
        "screen": dict,
        "window": dict,
        "webgl": dict,
        "canvas": dict,
        "navigator": dict,
    }
    nested = {
        "screen": dict.fromkeys(
            (
                "width",
                "height",
                "availWidth",
                "availHeight",
                "colorDepth",
                "pixelDepth",
            ),
            int,
        ),
        "window": {
            **dict.fromkeys(
                (
                    "innerWidth",
                    "innerHeight",
                    "outerWidth",
                    "outerHeight",
                    "screenX",
                    "screenY",
                    "screenLeft",
                    "screenTop",
                    "pageXOffset",
                    "pageYOffset",
                ),
                int,
            ),
            "devicePixelRatio": (int, float),
        },
        "webgl": dict.fromkeys(("renderer", "vendor"), str),
        "canvas": {"data_url": str},
        "navigator": {
            **dict.fromkeys(
                (
                    "userAgent",
                    "platform",
                    "vendor",
                    "appVersion",
                    "appCodeName",
                    "appName",
                    "product",
                    "language",
                ),
                str,
            ),
            "languages": list,
            "hardwareConcurrency": int,
            "maxTouchPoints": int,
            "webdriver": bool,
            "cookieEnabled": bool,
            "doNotTrack": (str, type(None)),
        },
    }

    def check(v, schema):
        if not isinstance(v, dict) or not v.keys() <= schema.keys():
            return False
        for k, item in v.items():
            types = schema[k] if isinstance(schema[k], tuple) else (schema[k],)
            if type(item) not in types or (
                k == "languages" and not all(type(x) is str for x in item)
            ):
                return False
        return True

    if not check(profile, fields):
        return False
    if any(
        not check(profile[k], schema) for k, schema in nested.items() if k in profile
    ):
        return False
    nav = profile.get("navigator", {})
    if any(
        k in profile and alias in nav and profile[k] != nav[alias]
        for k, alias in [
            ("user_agent", "userAgent"),
            ("platform", "platform"),
            ("language", "language"),
            ("languages", "languages"),
        ]
    ):
        return False
    if (
        "canvas" in profile
        and "data_url" in profile["canvas"]
        and not profile["canvas"]["data_url"].startswith("data:image/png;base64,")
    ):
        return False
    for obj in [profile, nav, profile.get("webgl", {})]:
        if any(isinstance(item, str) and len(item) > 8192 for item in obj.values()):
            return False
        if "languages" in obj and (
            not 1 <= len(obj["languages"]) <= 32
            or any(len(x) > 8192 for x in obj["languages"])
        ):
            return False
    for section, spec in {
        "screen": {
            "width": (1, 32768),
            "height": (1, 32768),
            "availWidth": (0, 32768),
            "availHeight": (0, 32768),
            "colorDepth": (1, 64),
            "pixelDepth": (1, 64),
        },
        "window": {
            "innerWidth": (1, 32768),
            "innerHeight": (1, 32768),
            "outerWidth": (1, 32768),
            "outerHeight": (1, 32768),
            "devicePixelRatio": (0.1, 16),
        },
        "navigator": {"hardwareConcurrency": (1, 1024), "maxTouchPoints": (0, 100)},
    }.items():
        if any(
            key in profile.get(section, {}) and not lo <= profile[section][key] <= hi
            for key, (lo, hi) in spec.items()
        ):
            return False
    canvas = profile.get("canvas", {})
    if "data_url" in canvas and not re.fullmatch(
        r"data:image/png;base64,[A-Za-z0-9+/]+={0,2}", canvas["data_url"]
    ):
        return False
    return True


def validate_shape(value):
    try:
        v = json_copy(value)
        if (
            not isinstance(v, dict)
            or not {"source_url", "profile", "request"} <= v.keys()
            or not v.keys()
            <= {
                "source_url",
                "scripts",
                "material_ref",
                "profile",
                "request",
                "document_cookie",
            }
        ):
            raise ValueError
        if not valid_url(v["source_url"]) or ("scripts" in v) == ("material_ref" in v):
            raise ValueError
        if "scripts" in v:
            if not isinstance(v["scripts"], list) or not 1 <= len(v["scripts"]) <= 16:
                raise ValueError
            for s in v["scripts"]:
                if (
                    not isinstance(s, dict)
                    or s.keys() != {"url", "source"}
                    or not valid_url(s["url"])
                    or not isinstance(s["source"], str)
                    or not s["source"]
                    or len(s["source"].encode()) > 2 * 1024 * 1024
                ):
                    raise ValueError
            if sum(len(s["source"].encode()) for s in v["scripts"]) > 3 * 1024 * 1024:
                raise ValueError
        elif not isinstance(v["material_ref"], str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{16,128}", v["material_ref"]
        ):
            raise ValueError
        if not profile_valid(v["profile"]) or byte_size(v["profile"]) > 64 * 1024:
            raise ValueError
        r = v["request"]
        if (
            not isinstance(r, dict)
            or r.keys() != {"url", "method", "content_type", "body"}
            or not valid_url(r["url"])
            or not isinstance(r["method"], str)
            or r["method"]
            not in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
        ):
            raise ValueError
        if r["content_type"] is not None and (
            not isinstance(r["content_type"], str)
            or len(r["content_type"]) > 256
            or not re.fullmatch(
                r"[\w!#$&^.+-]+/[\w!#$&^.+-]+(?:\s*;[^\r\n]*)?", r["content_type"]
            )
            or any(ord(c) < 32 or ord(c) == 127 for c in r["content_type"])
        ):
            raise ValueError
        if r["body"] is not None and (
            not isinstance(r["body"], str) or len(r["body"].encode()) > 256 * 1024
        ):
            raise ValueError
        if r["body"] is not None and (
            r["method"] in ("GET", "HEAD")
            or not r["content_type"]
            or r["content_type"].split(";")[0].lower()
            in ("application/octet-stream", "application/pdf", "application/zip")
            or r["content_type"]
            .lower()
            .startswith(("image/", "audio/", "video/", "multipart/"))
        ):
            raise ValueError
        if "document_cookie" in v and (
            not isinstance(v["document_cookie"], str)
            or len(v["document_cookie"].encode()) > 16 * 1024
            or any(ord(c) < 32 or ord(c) == 127 for c in v["document_cookie"])
        ):
            raise ValueError
        if byte_size(v) > 4 * 1024 * 1024:
            raise ValueError
        return v
    except (ValueError, TypeError, RecursionError, OverflowError, UnicodeError):
        raise ValidationError("Invalid material shape request.") from None


def safe_id(value, api_key):
    return (
        value
        if isinstance(value, str)
        and api_key not in value
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value)
        else None
    )


def response_metadata(response, api_key, body=None):
    request_id = safe_id(response.headers.get("X-Request-ID"), api_key)
    code = None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        error = body["error"]
        request_id = safe_id(error.get("request_id"), api_key) or request_id
        val = error.get("code")
        code = (
            val
            if isinstance(val, str)
            and api_key not in val
            and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", val)
            else None
        )
    retry = response.headers.get("Retry-After")
    if not isinstance(retry, str) or api_key in retry or len(retry) > 128:
        retry = None
    elif not re.fullmatch(r"[0-9]{1,10}", retry):
        try:
            if format_datetime(parsedate_to_datetime(retry), usegmt=True) != retry:
                retry = None
        except (ValueError, TypeError, OverflowError):
            retry = None
    return dict(
        status_code=response.status_code,
        request_id=request_id,
        retry_after=retry,
        code=code,
    )


def parse_result(body, metadata, api_key):
    try:
        v = json_copy(body)
        if (
            not isinstance(v, dict)
            or not {"headers", "request_id", "generation_ms", "profile_used"}
            <= v.keys()
        ):
            raise ValueError
        if (
            not safe_id(v["request_id"], api_key)
            or type(v["generation_ms"]) is not int
            or v["generation_ms"] < 0
            or not isinstance(v["profile_used"], dict)
        ):
            raise ValueError
        headers = v["headers"]
        if not isinstance(headers, dict) or len(headers) != 6:
            raise ValueError
        families = []
        suffixes = []
        for name, value in headers.items():
            m = re.fullmatch(r"([!#$%&'*+\-.^_`|~0-9A-Za-z]+)-([abcdfz])", name, re.I)
            if (
                not m
                or not isinstance(value, str)
                or any(ord(c) < 32 or ord(c) == 127 or ord(c) > 255 for c in value)
                or (m[2].lower() != "d" and not value.strip())
            ):
                raise ValueError
            families.append(m[1].lower())
            suffixes.append(m[2].lower())
        if len(set(families)) != 1 or set(suffixes) != set("abcdfz"):
            raise ValueError
        ref = v.get("material_ref")
        expiry = v.get("material_expires_at")
        if (ref is None) != (expiry is None):
            raise ValueError
        if ref is not None:
            if (
                not isinstance(ref, str)
                or not re.fullmatch(r"[A-Za-z0-9._:-]{1,256}", ref)
                or not isinstance(expiry, str)
                or len(expiry) > 64
                or datetime.fromisoformat(expiry.replace("Z", "+00:00")).utcoffset()
                is None
            ):
                raise ValueError
        return ShapeResult(
            headers, v["request_id"], v["generation_ms"], v["profile_used"], ref, expiry
        )
    except (ValueError, TypeError, RecursionError, OverflowError, UnicodeError):
        raise InvalidResponseError(
            "Rayon API returned an invalid shape response.", **metadata
        ) from None
