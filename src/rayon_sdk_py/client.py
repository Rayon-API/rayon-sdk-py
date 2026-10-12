from curl_cffi import CurlOpt, requests

from .errors import HTTPError, InvalidResponseError, RedirectError, SolveFailedError, TransportError
from .models import SolveResult
from .validation import parse_result, validate_request


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
    try:
        # Some curl_cffi versions leave libcurl's environment proxy lookup enabled.
        with requests.Session(impersonate="chrome", trust_env=False, curl_options={CurlOpt.PROXY: ""}) as session:
            response = session.post(
                base_url.rstrip("/") + "/solve",
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
                allow_redirects=False,
            )
    except requests.exceptions.RequestException:
        raise TransportError("Rayon API request could not be completed.") from None
    metadata = {
        "status_code": response.status_code,
        "request_id": response.headers.get("X-Request-ID"),
        "retry_after": response.headers.get("Retry-After"),
    }
    if 300 <= response.status_code < 400:
        raise RedirectError("Rayon API returned a redirect; no redirect was followed.", **metadata)
    if response.status_code != 200:
        raise HTTPError("Rayon API returned an unsuccessful HTTP status.", **metadata)
    try:
        body = response.json()
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidResponseError("Rayon API returned invalid JSON.", **metadata) from None
    result = parse_result(body, target_url, metadata)
    if result.status != "accepted":
        raise SolveFailedError(result, **metadata)
    return result
