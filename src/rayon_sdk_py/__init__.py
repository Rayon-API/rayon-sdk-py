"""Material-only Rayon API clients."""

from .client import Client, AsyncClient, generate
from .validation import validate_profile
from .models import (
    ShapeRequest,
    BrowserProfile,
    ShapeResult,
    FormShapeResult,
    FormShapeRequest,
    FormMetadata,
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

__version__ = "1.1.1"
__all__ = [
    "Client",
    "AsyncClient",
    "generate",
    "validate_profile",
    "ShapeRequest",
    "BrowserProfile",
    "ShapeResult",
    "FormShapeResult",
    "FormShapeRequest",
    "FormMetadata",
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
