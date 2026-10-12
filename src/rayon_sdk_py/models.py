from dataclasses import dataclass, field
from typing import Any, TypedDict


class ScriptMaterial(TypedDict):
    url: str
    source: str


class ScreenProfile(TypedDict, total=False):
    width: int
    height: int
    availWidth: int
    availHeight: int
    colorDepth: int
    pixelDepth: int


class WindowProfile(TypedDict, total=False):
    innerWidth: int
    innerHeight: int
    outerWidth: int
    outerHeight: int
    screenX: int
    screenY: int
    screenLeft: int
    screenTop: int
    pageXOffset: int
    pageYOffset: int
    devicePixelRatio: float


class WebGLProfile(TypedDict, total=False):
    renderer: str
    vendor: str


class CanvasProfile(TypedDict, total=False):
    data_url: str


class NavigatorProfile(TypedDict, total=False):
    userAgent: str
    platform: str
    vendor: str
    appVersion: str
    appCodeName: str
    appName: str
    product: str
    language: str
    languages: list[str]
    hardwareConcurrency: int
    maxTouchPoints: int
    webdriver: bool
    cookieEnabled: bool
    doNotTrack: str | None


class BrowserProfile(TypedDict, total=False):
    user_agent: str
    platform: str
    language: str
    languages: list[str]
    screen: ScreenProfile
    window: WindowProfile
    webgl: WebGLProfile
    canvas: CanvasProfile
    navigator: NavigatorProfile


class TargetRequest(TypedDict):
    url: str
    method: str
    content_type: str | None
    body: str | None


class _ShapeRequired(TypedDict):
    source_url: str
    profile: BrowserProfile
    request: TargetRequest


class ShapeRequest(_ShapeRequired, total=False):
    """Provide exactly one of scripts and material_ref."""

    scripts: list[ScriptMaterial]
    material_ref: str
    document_cookie: str


@dataclass(frozen=True)
class ShapeResult:
    headers: dict[str, str] = field(repr=False)
    request_id: str
    generation_ms: int
    profile_used: dict[str, Any] = field(repr=False)
    material_ref: str | None = field(default=None, repr=False)
    material_expires_at: str | None = None
