class RayonError(Exception):
    """Safe errors never retain server messages or transport exception causes."""

    def __init__(
        self, message, *, status_code=None, request_id=None, retry_after=None, code=None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
        self.retry_after = retry_after
        self.code = code


class ValidationError(RayonError, ValueError):
    """Invalid request; no API request was sent."""


class TransportError(RayonError):
    """API transport failure."""


class HTTPError(RayonError):
    """Unsuccessful HTTP status. No billable request is automatically retried."""


class RedirectError(HTTPError):
    """Redirect refused."""


class MigrationError(HTTPError):
    """HTTP 410: migrate to the material-only v1 API."""


class InvalidResponseError(RayonError):
    """Malformed or oversized response."""
