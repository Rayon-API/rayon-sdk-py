"""Synchronous client for the public Rayon API."""

from .client import solve
from .models import SolveResult
from .errors import (
    HTTPError, InvalidResponseError, RayonError, RedirectError,
    SolveFailedError, TransportError, ValidationError,
)

__version__ = "0.1.0"
__all__ = [
    "solve", "SolveResult", "RayonError", "ValidationError", "TransportError",
    "HTTPError", "RedirectError", "InvalidResponseError", "SolveFailedError",
]
