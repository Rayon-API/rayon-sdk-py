"""Material-only Rayon API clients."""

from .client import Client, AsyncClient, generate
from .models import (
    ShapeRequest,
    BrowserProfile,
    ShapeResult,
    ScriptMaterial,
    TargetRequest,
)
from .errors import (
    RayonError,
    ValidationError,
    TransportError,
    HTTPError,
    RedirectError,
    MigrationError,
    InvalidResponseError,
)

__version__ = "1.0.0"
__all__ = [
    "Client",
    "AsyncClient",
    "generate",
    "ShapeRequest",
    "BrowserProfile",
    "ShapeResult",
    "ScriptMaterial",
    "TargetRequest",
    "RayonError",
    "ValidationError",
    "TransportError",
    "HTTPError",
    "RedirectError",
    "MigrationError",
    "InvalidResponseError",
]
