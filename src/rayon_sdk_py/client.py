from curl_cffi import CurlOpt, requests
from curl_cffi.curl import CURL_WRITEFUNC_ERROR

from .errors import (
    HTTPError,
    InvalidResponseError,
    RedirectError,
    SolveFailedError,
    TransportError,
)
from .models import SolveResult
from .validation import parse_result, response_metadata, validate_request


_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def solve(
    target_url: str,
    api_key: str,
    *,
    profile: dict | None = None,
    base_url: str = "https://api.rayonapi.com",
    timeout: float = 150,
) -> SolveResult:
    """Capture a telemetry header family with one synchronous API request."""
    profile = validate_request(target_url, api_key, profile, base_url, timeout)
    body = {"target_url": target_url}
    if profile is not None:
        body["profile"] = profile
    content = bytearray()
    oversized = False

    def collect(chunk):
        nonlocal oversized
        if len(content) + len(chunk) > _MAX_RESPONSE_BYTES:
            oversized = True
            return CURL_WRITEFUNC_ERROR
        content.extend(chunk)
        return len(chunk)

    try:
        # Some curl_cffi versions leave libcurl's environment proxy lookup enabled.
        with requests.Session(
            impersonate="chrome", trust_env=False, curl_options={CurlOpt.PROXY: ""}
        ) as session:
            response = session.post(
                base_url.rstrip("/") + "/solve",
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
                allow_redirects=False,
                content_callback=collect,
            )
    except requests.exceptions.RequestException:
        if oversized:
            raise InvalidResponseError(
                "Rayon API response exceeded the 2 MiB limit."
            ) from None
        raise TransportError("Rayon API request could not be completed.") from None
    response.content = bytes(content)
    metadata = response_metadata(response, api_key)
    if 300 <= response.status_code < 400:
        raise RedirectError(
            "Rayon API returned a redirect; no redirect was followed.", **metadata
        )
    if response.status_code != 200:
        raise HTTPError("Rayon API returned an unsuccessful HTTP status.", **metadata)
    try:
        body = response.json()
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidResponseError(
            "Rayon API returned invalid JSON.", **metadata
        ) from None
    result = parse_result(body, target_url, metadata)
    if result.status != "accepted":
        raise SolveFailedError(result, **metadata)
    return result
