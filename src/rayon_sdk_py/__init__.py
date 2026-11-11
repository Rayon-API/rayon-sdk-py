"""Synchronous and asynchronous Rayon API clients."""

from .client import Client, AsyncClient, generate
from .validation import validate_profile
from .models import (
    PreparationRequest, FormPreparationRequest,
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

__version__ = "3.0.0"
__all__ = [
    "Preparation", "ReadyMaterial", "PreparationError", "PreparationCancelledError",
    "Client",
    "AsyncClient",
    "generate",
    "validate_profile",
    "PreparationRequest", "FormPreparationRequest",
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

from .preparation import Preparation, ReadyMaterial, PreparationError, PreparationCancelledError
