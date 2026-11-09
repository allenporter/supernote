"""macOS Vision framework wrapper with error translation.

Imports `pyobjc-framework-Vision` only when an `AppleVisionBackend` is
constructed so Linux installations and containers do not require macOS
Objective-C bindings unless `provider: apple` is configured, while failing fast
at server startup if `provider: apple` is configured without `supernote[apple]`.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from supernote.server.ai.base import AIError

if TYPE_CHECKING:
    from supernote.server.config import ProviderConfig

__all__ = [
    "AppleVisionBackend",
    "RecognitionLevel",
    "create_apple_backend",
]

logger = logging.getLogger(__name__)

VisionLoader = Callable[[], tuple[Any, Any]]

_BASE_RUNTIME_ERRORS: tuple[type[BaseException], ...] = (
    RuntimeError,
    OSError,
    ValueError,
    TypeError,
    AttributeError,
)


class RecognitionLevel(StrEnum):
    """Canonical Apple Vision OCR model identifiers."""

    VISION_ACCURATE = "vision-accurate"
    VISION_FAST = "vision-fast"


def _load_vision_runtime() -> tuple[Any, Any]:
    """Import and return `(objc, Vision)` from PyObjC, or raise `AIError`."""
    try:
        objc_mod = importlib.import_module("objc")
        vision_mod = importlib.import_module("Vision")
    except ImportError as err:
        raise AIError(
            "Apple Vision framework is unavailable; install 'supernote[apple]' on macOS."
        ) from err
    return objc_mod, vision_mod


def _format_vision_error(error: Any) -> str:
    """Format an `NSError` or Python error value returned by Vision."""
    if error is None:
        return "unknown Vision error"
    localized = getattr(error, "localizedDescription", None)
    if callable(localized):
        return str(localized())
    return str(error)


class AppleVisionBackend:
    """On-device macOS Vision OCR backend with error translation."""

    def __init__(
        self,
        vision_loader: VisionLoader = _load_vision_runtime,
        provider: str = "apple",
    ) -> None:
        self._provider = provider
        self._objc, self._vision = vision_loader()
        objc_error = getattr(self._objc, "error", None)
        if isinstance(objc_error, type) and issubclass(objc_error, BaseException):
            self._handled_errors: tuple[type[BaseException], ...] = (
                *_BASE_RUNTIME_ERRORS,
                objc_error,
            )
        else:
            self._handled_errors = _BASE_RUNTIME_ERRORS

    @property
    def provider(self) -> str:
        return self._provider

    @contextmanager
    def _handle_vision_errors(self, operation: str) -> Generator[None]:
        try:
            yield
        except AIError as err:
            logger.error(f"Apple Vision error during {operation}: {err}")
            raise
        except self._handled_errors as err:
            logger.error(f"Unexpected Apple Vision error during {operation}: {err!r}")
            raise AIError(f"Apple Vision error during {operation}: {err}") from err

    def _recognize_text_sync(
        self,
        png_data: bytes,
        level: RecognitionLevel,
    ) -> str:
        if not png_data:
            raise AIError("Apple Vision text recognition failed: empty image data")

        with self._objc.autorelease_pool():
            handler = self._vision.VNImageRequestHandler.alloc().initWithData_options_(
                png_data, None
            )
            if handler is None:
                raise AIError("Apple Vision failed to initialize image request handler")

            request = self._vision.VNRecognizeTextRequest.alloc().init()
            vision_level = (
                self._vision.VNRequestTextRecognitionLevelFast
                if level == RecognitionLevel.VISION_FAST
                else self._vision.VNRequestTextRecognitionLevelAccurate
            )
            request.setRecognitionLevel_(vision_level)
            request.setUsesLanguageCorrection_(True)
            request.setAutomaticallyDetectsLanguage_(True)

            success, error = handler.performRequests_error_([request], None)
            if not success:
                detail = _format_vision_error(error)
                raise AIError(f"Apple Vision text recognition failed: {detail}")

            lines: list[str] = []
            for observation in request.results() or ():
                candidates = observation.topCandidates_(1)
                if not candidates:
                    continue
                raw_text = candidates[0].string()
                if raw_text is None:
                    continue
                text = str(raw_text).strip()
                if text:
                    lines.append(text)
            return "\n".join(lines)

    async def recognize_text(
        self,
        png_data: bytes,
        level: RecognitionLevel = RecognitionLevel.VISION_ACCURATE,
    ) -> str:
        """Run on-device Vision text recognition on `png_data` in a worker thread."""
        with self._handle_vision_errors("recognize_text"):
            return await asyncio.to_thread(self._recognize_text_sync, png_data, level)


def create_apple_backend(
    providers: Mapping[str, ProviderConfig],
    name: str = "apple",
) -> AppleVisionBackend:
    """Create an `AppleVisionBackend`, failing fast if Vision is unavailable."""
    return AppleVisionBackend(provider=name)
