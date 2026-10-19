import re
import json
from importlib.resources import files

_ERROR_CATALOG = json.loads(files(__package__).joinpath("error_catalog.json").read_text(encoding="utf-8"))


HISTORY_ACTION = "Check request history before sending another request. Contact support with the request ID if it remains unclear."


def trusted_guidance(code, reason, domain=None, retryable=None, billing_status=None):
    entry = _ERROR_CATALOG.get(reason) if isinstance(reason, str) else None
    if not entry or code not in entry["codes"]:
        return None
    action = HISTORY_ACTION if entry["retryable"] and (safe_billing_status(billing_status) != "not_charged" or retryable is False) else entry["action"]
    return dict(reason=reason, message=entry["message"].replace("{domain}", safe_domain(domain) or "this domain"), action=action)


class RayonError(Exception):
    """Safe errors never retain server messages or transport exception causes."""

    def __init__(
        self, message, *, status_code=None, request_id=None, retry_after=None, code=None, retryable=None,
        reason=None, action=None, domain=None, field=None, billing_status=None
    ):
        guidance = trusted_guidance(code, reason, domain, retryable, billing_status)
        super().__init__(guidance["message"] if guidance else message)
        self.status_code = status_code
        self.request_id = request_id
        self.retry_after = retry_after
        self.code = code
        self.retryable = retryable if type(retryable) is bool else None
        self.reason = guidance["reason"] if guidance else None
        self.action = guidance["action"] if guidance else None
        self.domain = safe_domain(domain)
        self.field = safe_field(field)
        self.billing_status = safe_billing_status(billing_status)


class ValidationError(RayonError, ValueError):
    """Invalid request; no API request was sent."""


class TransportError(RayonError):
    """API transport failure."""


class HTTPError(RayonError):
    """Unsuccessful HTTP status. No billable request is automatically retried."""


class RedirectError(HTTPError):
    """Redirect refused."""


class MigrationError(HTTPError):
    """Compatibility subclass for HTTP errors."""


class InvalidResponseError(RayonError):
    """Malformed or oversized response."""

def safe_domain(value, api_key=None):
    """Keep hostnames only, excluding URLs, IP literals and credentials."""
    return value if (
        isinstance(value, str) and len(value) <= 253 and (api_key is None or api_key not in value)
        and re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?", value)
    ) else None


def safe_field(value, api_key=None):
    return value if (
        isinstance(value, str) and len(value) <= 96 and (api_key is None or api_key not in value)
        and re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*", value)
        and not {"__proto__", "constructor", "prototype"}.intersection(value.split("."))
    ) else None


def safe_billing_status(value):
    return value if isinstance(value, str) and value in {"not_charged", "pending", "unknown"} else None
