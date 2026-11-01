"""Reusable PyObjC Vision fakes for `supernote.server.ai.models.apple` tests."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

from supernote.server.ai.models.apple.backend import AppleVisionBackend


class FakeObjCError(Exception):
    """Simulates `objc.error` (inherits directly from `Exception`)."""


@dataclass
class FakeObjCModule:
    """Fake `objc` module tracking `autorelease_pool()` usage."""

    error: type[BaseException] | None = FakeObjCError
    pool_entries: int = 0
    active_pools: int = 0

    @contextmanager
    def autorelease_pool(self) -> Generator[None]:
        self.pool_entries += 1
        self.active_pools += 1
        try:
            yield
        finally:
            self.active_pools -= 1


@dataclass
class FakeNSError:
    """Fake Objective-C `NSError` exposing `localizedDescription()`."""

    message: str

    def localizedDescription(self) -> str:
        return self.message


@dataclass
class FakeCandidate:
    """Fake `VNRecognizedText` candidate."""

    text: str | None

    def string(self) -> str | None:
        return self.text


@dataclass
class FakeObservation:
    """Fake `VNRecognizedTextObservation`."""

    candidates: list[FakeCandidate]

    def topCandidates_(self, max_candidates: int) -> list[FakeCandidate]:
        return self.candidates[:max_candidates]


@dataclass
class FakeRecognizeTextRequest:
    """Fake `VNRecognizeTextRequest`."""

    recognition_level: int | None = None
    uses_language_correction: bool | None = None
    auto_detects_language: bool | None = None
    observations: list[FakeObservation] | None = field(default_factory=list)

    def init(self) -> FakeRecognizeTextRequest:
        return self

    def setRecognitionLevel_(self, level: int) -> None:
        self.recognition_level = level

    def setUsesLanguageCorrection_(self, flag: bool) -> None:
        self.uses_language_correction = flag

    def setAutomaticallyDetectsLanguage_(self, flag: bool) -> None:
        self.auto_detects_language = flag

    def results(self) -> list[FakeObservation] | None:
        return self.observations


@dataclass
class RecordedVisionCall:
    """Captured arguments from a single Vision OCR invocation."""

    png_data: bytes
    options: Any
    recognition_level: int | None
    uses_language_correction: bool | None
    auto_detects_language: bool | None


@dataclass
class FakeVisionModule:
    """Fake `Vision` framework module matching PyObjC's selector surface."""

    VNRequestTextRecognitionLevelAccurate: int = 0
    VNRequestTextRecognitionLevelFast: int = 1

    lines: list[str | None] = field(
        default_factory=lambda: ["Daily Log", "- Ship local Vision OCR"]
    )
    include_empty_observation: bool = False
    return_none_results: bool = False
    return_nil_handler: bool = False
    perform_success: bool = True
    perform_error: Any = None
    raise_on_perform: BaseException | None = None
    calls: list[RecordedVisionCall] = field(default_factory=list)

    @property
    def VNImageRequestHandler(self) -> Any:
        vision = self

        class _HandlerAllocator:
            @staticmethod
            def alloc() -> _HandlerAllocator:
                return _HandlerAllocator()

            def initWithData_options_(
                self, data: bytes, options: Any
            ) -> _Handler | None:
                if vision.return_nil_handler:
                    return None
                return _Handler(data, options)

        class _Handler:
            def __init__(self, data: bytes, options: Any) -> None:
                self._data = data
                self._options = options

            def performRequests_error_(
                self, requests: list[Any], error_out: Any
            ) -> tuple[bool, Any]:
                if vision.raise_on_perform is not None:
                    raise vision.raise_on_perform

                req = requests[0]
                vision.calls.append(
                    RecordedVisionCall(
                        png_data=self._data,
                        options=self._options,
                        recognition_level=req.recognition_level,
                        uses_language_correction=req.uses_language_correction,
                        auto_detects_language=req.auto_detects_language,
                    )
                )
                if not vision.perform_success:
                    return False, vision.perform_error

                if vision.return_none_results:
                    req.observations = None
                else:
                    observations = [
                        FakeObservation([FakeCandidate(line)]) for line in vision.lines
                    ]
                    if vision.include_empty_observation:
                        observations.insert(0, FakeObservation([]))
                    req.observations = observations
                return True, None

        return _HandlerAllocator

    @property
    def VNRecognizeTextRequest(self) -> Any:
        class _RequestAllocator:
            @staticmethod
            def alloc() -> FakeRecognizeTextRequest:
                return FakeRecognizeTextRequest()

        return _RequestAllocator


@pytest.fixture
def fake_objc() -> FakeObjCModule:
    return FakeObjCModule()


@pytest.fixture
def fake_vision() -> FakeVisionModule:
    return FakeVisionModule()


@pytest.fixture
def apple_backend(
    fake_objc: FakeObjCModule,
    fake_vision: FakeVisionModule,
) -> AppleVisionBackend:
    return AppleVisionBackend(vision_loader=lambda: (fake_objc, fake_vision))
