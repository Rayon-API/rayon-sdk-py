from .models import SolveResult


class RayonError(Exception):
    """Base class for all SDK failures; messages never include API response bodies."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
        retry_after: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
        self.retry_after = retry_after


class ValidationError(RayonError, ValueError):
    """A request argument is invalid; no API request was sent."""


class TransportError(RayonError):
    """The API request could not be completed."""


class HTTPError(RayonError):
    """The API returned an unsuccessful HTTP status."""


class RedirectError(HTTPError):
    """The API returned a redirect, which the SDK did not follow."""


class InvalidResponseError(RayonError):
    """The API response was not valid JSON or did not match the contract."""


class SolveFailedError(RayonError):
    """The API returned a valid failed or rejected solve result."""

    def __init__(self, result: SolveResult, **metadata):
        super().__init__("Rayon solve was not accepted.", **metadata)
        self.result = result
