from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SolveResult:
    """Captured telemetry and the metadata needed to replay it."""

    status: str
    method: str
    target_url: str = field(repr=False)
    duration_ms: int
    headers: dict[str, str] = field(repr=False)
    cookies: list[dict[str, Any]] = field(repr=False)
    profile_used: dict[str, Any] = field(repr=False)
    errors: list[str] = field(repr=False)
