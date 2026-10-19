import json
import math
import re
from datetime import datetime
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urlsplit, unquote_plus, quote_plus
from .errors import InvalidResponseError, ValidationError, trusted_guidance, safe_domain, safe_field
from .models import BrowserProfile, ShapeResult, FormShapeResult

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


DEFAULT_PROFILE = {
    "user_agent": "Mozilla/5.0",
    "platform": "MacIntel",
    "language": "en-US",
    "languages": ["en-US", "en"],
    "screen": {
        "width": 1920,
        "height": 1080,
        "availWidth": 1920,
        "availHeight": 1040,
        "colorDepth": 24,
        "pixelDepth": 24,
    },
    "window": {
        "innerWidth": 1920,
        "innerHeight": 1040,
        "outerWidth": 1920,
        "outerHeight": 1080,
        "devicePixelRatio": 1.0,
        "screenX": 0,
        "screenY": 0,
        "screenLeft": 0,
        "screenTop": 0,
        "pageXOffset": 0,
        "pageYOffset": 0,
    },
    "webgl": {"renderer": "Sandbox Renderer", "vendor": "Google Inc."},
    "canvas": {
        "data_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII="
    },
    "navigator": {
        "userAgent": "Mozilla/5.0",
        "platform": "MacIntel",
        "vendor": "Google Inc.",
        "appVersion": "5.0",
        "appCodeName": "Mozilla",
        "appName": "Netscape",
        "product": "Gecko",
        "language": "en-US",
        "languages": ["en-US", "en"],
        "hardwareConcurrency": 8,
        "maxTouchPoints": 0,
        "webdriver": False,
        "cookieEnabled": True,
        "doNotTrack": None,
    },
}


def effective_profile(profile):
    """Measure the canonical browser identity, including defaults and aliases."""
    effective = json_copy(DEFAULT_PROFILE)
    for key, value in profile.items():
        if isinstance(value, dict):
            effective[key].update(value)
        else:
            effective[key] = value
    navigator = effective["navigator"]
    supplied_navigator = profile.get("navigator", {})
    for top, alias in [
        ("user_agent", "userAgent"),
        ("platform", "platform"),
        ("language", "language"),
        ("languages", "languages"),
    ]:
        value = (
            supplied_navigator[alias] if alias in supplied_navigator else effective[top]
        )
        effective[top] = value
        navigator[alias] = value
    if "appVersion" not in supplied_navigator:
        navigator["appVersion"] = re.sub(r"^Mozilla/", "", effective["user_agent"])
    effective["window"]["devicePixelRatio"] = float(
        effective["window"]["devicePixelRatio"]
    )
    return effective


def effective_profile_size(profile):
    return len(
        json.dumps(effective_profile(profile), ensure_ascii=False).encode("utf-8")
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
            **dict.fromkeys(
                (
                    "screenX",
                    "screenY",
                    "screenLeft",
                    "screenTop",
                    "pageXOffset",
                    "pageYOffset",
                ),
                (-2147483648, 2147483647),
            ),
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


def validate_profile(profile: BrowserProfile) -> BrowserProfile:
    """Validate without network access; return a deep copy of supplied fields."""
    try:
        checked = json_copy(profile)
        if profile_valid(checked) and effective_profile_size(checked) <= 64 * 1024:
            return checked
    except (ValueError, TypeError, RecursionError, OverflowError, UnicodeError):
        pass
    raise ValidationError("Invalid browser profile.")


FORM_NAME = re.compile(r"([!#$%&'*+\-.^_`|~0-9A-Za-z]{1,128})([abcdfz])")


def form_pairs(body):
    """Strict decoding with ordered duplicate application fields preserved."""
    if not isinstance(body, str) or len(body.encode()) > 256 * 1024:
        raise ValueError
    if re.search(r"%(?![0-9A-Fa-f]{2})", body):
        raise ValueError
    pairs = []
    for part in body.split("&"):
        if not part:
            continue
        key, _, val = part.partition("=")
        key = unquote_plus(key, encoding="utf-8", errors="strict")
        val = unquote_plus(val, encoding="utf-8", errors="strict")
        if "\x00" in key or "\x00" in val or len(key.encode()) > 256:
            raise ValueError
        pairs.append((key, val))
        if len(pairs) > 1024:
            raise ValueError
    return pairs


def validate_form_request(v, r):
    mode = v.get("mode", "header")
    if mode not in ("header", "form"):
        raise ValueError
    if mode == "header":
        if "form" in v:
            raise ValueError
        return
    if (
        r["method"] != "POST"
        or not isinstance(r["content_type"], str)
        or not re.fullmatch(
            r'application/x-www-form-urlencoded(?:\s*;\s*charset\s*=\s*(?:"(?:utf-8|utf8)"|utf-8|utf8))?\s*',
            r["content_type"],
            re.I,
        )
    ):
        raise ValueError
    if "form" in v:
        form = v["form"]
        if not isinstance(form, dict) or not form.keys() <= {"id", "name"}:
            raise ValueError
        for value in form.values():
            if (
                not isinstance(value, str)
                or len(value) > 256
                or any(ord(c) < 32 or ord(c) == 127 for c in value)
            ):
                raise ValueError
            value.encode("utf-8", errors="strict")
    families = {}
    for name, _ in form_pairs(r["body"]):
        match = FORM_NAME.fullmatch(name)
        if match:
            families.setdefault(match[1], set()).add(match[2])
    if any(slots == set("abcdfz") for slots in families.values()):
        raise ValueError


def safe_form_fields(fields, body):
    if not isinstance(fields, dict) or len(fields) != 6:
        raise ValueError
    families, slots = set(), set()
    for name, value in fields.items():
        match = FORM_NAME.fullmatch(name)
        if (
            not match
            or not isinstance(value, str)
            or len(value.encode()) > 16384
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or (match[2] != "d" and not value)
        ):
            raise ValueError
        families.add(match[1])
        slots.add(match[2])

    def encode(value):
        return quote_plus(value, safe="*", encoding="utf-8", errors="strict").replace(
            "~", "%7E"
        )

    expected = "&".join(
        encode(name) + "=" + encode(value) for name, value in fields.items()
    )
    if (
        len(families) != 1
        or slots != set("abcdfz")
        or not isinstance(body, str)
        or len(body.encode()) > 256 * 1024
        or body != expected
    ):
        raise ValueError
    return fields


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
                "mode",
                "form",
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
        v["profile"] = validate_profile(v["profile"])
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
        validate_form_request(v, r)
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
    retryable = None
    error = {}
    request_id = safe_id(response.headers.get("X-Request-ID"), api_key)
    code = None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        error = body["error"]
        retryable = error.get("retryable") if type(error.get("retryable")) is bool else None
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
    domain = safe_domain(error.get("domain"), api_key)
    reason = error.get("reason")
    guidance = trusted_guidance(code, reason, domain) if isinstance(reason, str) and api_key not in reason else None
    billing = error.get("billing_status")
    return dict(
        reason=guidance["reason"] if guidance else None,
        action=guidance["action"] if guidance else None,
        domain=domain,
        field=safe_field(error.get("field"), api_key),
        billing_status=billing if isinstance(billing, str) and billing in {"not_charged", "pending", "unknown"} else None,
        retryable=retryable,
        status_code=response.status_code,
        request_id=request_id,
        retry_after=retry,
        code=code,
    )


def parse_result(body, metadata, api_key, mode="header"):
    try:
        v = json_copy(body)
        if (
            not isinstance(v, dict)
            or not {"request_id", "generation_ms", "profile_used"} <= v.keys()
        ):
            raise ValueError
        if (
            not safe_id(v["request_id"], api_key)
            or type(v["generation_ms"]) is not int
            or v["generation_ms"] < 0
            or not isinstance(v["profile_used"], dict)
        ):
            raise ValueError
        if mode == "form":
            if "headers" in v:
                raise ValueError
            fields = safe_form_fields(v.get("form_fields"), v.get("form_body"))
        elif mode == "header":
            if "form_fields" in v or "form_body" in v or "headers" not in v:
                raise ValueError
            headers = v["headers"]
            if not isinstance(headers, dict) or len(headers) not in (6, 7):
                raise ValueError
            families = []
            suffixes = []
            for name, value in headers.items():
                m = re.fullmatch(
                    r"([!#$%&'*+\-.^_`|~0-9A-Za-z]{1,128})-(a0|[abcdfz])",
                    name,
                    re.I | re.ASCII,
                )
                if (
                    not m
                    or not isinstance(value, str)
                    or any(not 33 <= ord(c) <= 126 for c in value)
                    or (m[2].lower() != "d" and not value.strip())
                ):
                    raise ValueError
                families.append(m[1].lower())
                suffixes.append(m[2].lower())
            if (
                len(set(families)) != 1
                or len(set(suffixes)) != len(suffixes)
                or not set("abcdfz") <= set(suffixes)
            ):
                raise ValueError
        else:
            raise ValueError
        ref = v.get("material_ref")
        expiry = v.get("material_expires_at")
        if ref is None or expiry is None:
            raise ValueError
        if ref is not None:
            if (
                not isinstance(ref, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", ref)
                or not isinstance(expiry, str)
                or len(expiry) > 64
                or datetime.fromisoformat(expiry.replace("Z", "+00:00")).utcoffset()
                is None
            ):
                raise ValueError
        if mode == "form":
            return FormShapeResult(
                fields,
                v["form_body"],
                v["request_id"],
                v["generation_ms"],
                v["profile_used"],
                ref,
                expiry,
            )
        return ShapeResult(
            headers, v["request_id"], v["generation_ms"], v["profile_used"], ref, expiry
        )
    except (ValueError, TypeError, RecursionError, OverflowError, UnicodeError):
        raise InvalidResponseError(
            "Rayon API returned an invalid shape response.", **metadata
        ) from None
