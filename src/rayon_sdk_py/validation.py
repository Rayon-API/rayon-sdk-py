import json
import math
import re
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urlsplit

from .errors import InvalidResponseError, ValidationError
from .models import SolveResult


def response_metadata(response, api_key):
    request_id = response.headers.get("X-Request-ID")
    if (
        not isinstance(request_id, str)
        or api_key in request_id
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", request_id)
    ):
        request_id = None
    retry_after = response.headers.get("Retry-After")
    if (
        not isinstance(retry_after, str)
        or api_key in retry_after
        or len(retry_after) > 128
    ):
        retry_after = None
    elif not re.fullmatch(r"[0-9]{1,10}", retry_after):
        try:
            parsed = parsedate_to_datetime(retry_after)
            if format_datetime(parsed, usegmt=True) != retry_after:
                retry_after = None
        except (ValueError, TypeError, OverflowError):
            retry_after = None
    return {
        "status_code": response.status_code,
        "request_id": request_id,
        "retry_after": retry_after,
    }


def _json_value(value, seen=None):
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if not isinstance(value, (dict, list)):
        return False
    seen = set() if seen is None else seen
    if id(value) in seen:
        return False
    seen.add(id(value))
    try:
        if isinstance(value, dict):
            return all(
                isinstance(k, str) and _json_value(v, seen) for k, v in value.items()
            )
        return all(_json_value(item, seen) for item in value)
    finally:
        seen.remove(id(value))


def _valid_url(value: str, *, base=False):
    if not isinstance(value, str) or not value or len(value) > 8192:
        return False
    if any(ord(char) <= 32 or ord(char) == 127 for char in value) or "\\" in value:
        return False
    try:
        parts = urlsplit(value)
        port = parts.port
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or "#" in value
        ):
            return False
        if base and (
            "?" in value
            or (
                parts.scheme == "http"
                and parts.hostname not in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            return False
        return port is None or 0 < port <= 65535
    except ValueError:
        return False


def validate_request(target_url, api_key, profile, base_url, timeout):
    if not _valid_url(target_url):
        raise ValidationError(
            "target_url must be an HTTP(S) URL without credentials or a fragment."
        )
    if (
        not isinstance(api_key, str)
        or not api_key
        or any(not 33 <= ord(char) <= 126 for char in api_key)
    ):
        raise ValidationError(
            "api_key must be a nonempty ASCII token without whitespace."
        )
    if not _valid_url(base_url, base=True):
        raise ValidationError(
            "base_url must be HTTPS (or local HTTP) without credentials, query, or fragment."
        )
    try:
        valid_timeout = (
            isinstance(timeout, (int, float))
            and not isinstance(timeout, bool)
            and math.isfinite(timeout)
            and timeout > 0
        )
    except OverflowError:
        valid_timeout = False
    if not valid_timeout:
        raise ValidationError("timeout must be a finite positive number of seconds.")
    try:
        if profile is not None and (
            not isinstance(profile, dict)
            or not _json_value(profile)
            or ("profile" in profile and not isinstance(profile["profile"], dict))
        ):
            raise ValueError
        return (
            None
            if profile is None
            else json.loads(json.dumps(profile, allow_nan=False))
        )
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise ValidationError(
            "profile must be a JSON object with finite values and string keys."
        ) from None


def parse_result(body, target_url, metadata):
    required = {
        "status",
        "method",
        "target_url",
        "duration_ms",
        "headers",
        "cookies",
        "profile_used",
        "errors",
    }
    valid = isinstance(body, dict) and required <= body.keys()
    if valid:
        valid = (
            body["status"] in ("accepted", "failed", "rejected")
            and body["method"] in ("v8_sandbox", "playwright")
            and body["target_url"] == target_url
            and type(body["duration_ms"]) is int
            and body["duration_ms"] >= 0
            and isinstance(body["headers"], dict)
            and isinstance(body["cookies"], list)
            and isinstance(body["profile_used"], dict)
            and isinstance(body["errors"], list)
            and all(isinstance(error, str) for error in body["errors"])
        )
    if valid:
        try:
            valid = _json_value(body["profile_used"]) and all(
                isinstance(cookie, dict)
                and {"name", "value", "domain", "path"} <= cookie.keys()
                and all(
                    isinstance(cookie[field], str)
                    for field in ("name", "value", "domain", "path")
                )
                and _json_value(cookie)
                for cookie in body["cookies"]
            )
        except RecursionError:
            valid = False
    if valid:
        headers = body["headers"]
        valid = all(
            isinstance(name, str)
            and name.isascii()
            and isinstance(value, str)
            and not any(
                ord(char) < 32 or ord(char) == 127 or ord(char) > 255 for char in value
            )
            for name, value in headers.items()
        )
        if valid and body["status"] == "accepted":
            families = []
            suffixes = []
            for name, value in headers.items():
                match = re.fullmatch(
                    r"([!#$%&'*+\-.^_`|~0-9A-Za-z]+)-([abcdfz])", name, re.IGNORECASE
                )
                if not match or (match[2].lower() != "d" and not value.strip()):
                    valid = False
                    break
                families.append(match[1].lower())
                suffixes.append(match[2].lower())
            valid = (
                valid
                and len(headers) == 6
                and len(set(families)) == 1
                and set(suffixes) == set("abcdfz")
            )
    if not valid:
        raise InvalidResponseError(
            "Rayon API returned an invalid solve response.", **metadata
        )
    return SolveResult(**{field: body[field] for field in required})
