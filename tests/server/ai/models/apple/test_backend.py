"""Tests for `supernote.server.ai.models.apple.backend`."""

from __future__ import annotations

import importlib.util
import io
import sys
from types import ModuleType

import pytest
from PIL import Image, ImageDraw, ImageFont

from supernote.server.ai.base import AIError
from supernote.server.ai.models.apple.backend import (
    AppleVisionBackend,
    RecognitionLevel,
    _load_vision_runtime,
    create_apple_backend,
)

from .conftest import FakeNSError, FakeObjCError, FakeObjCModule, FakeVisionModule


def test_create_apple_backend_and_eager_runtime_check(
    monkeypatch: pytest.MonkeyPatch,
    fake_objc: FakeObjCModule,
    fake_vision: FakeVisionModule,
) -> None:
    monkeypatch.setitem(sys.modules, "objc", fake_objc)  # type: ignore[arg-type]
    monkeypatch.setitem(sys.modules, "Vision", fake_vision)  # type: ignore[arg-type]

    backend = create_apple_backend({}, "apple")
    assert isinstance(backend, AppleVisionBackend)
    assert backend.provider == "apple"

    named_backend = create_apple_backend({}, "mac_vision")
    assert isinstance(named_backend, AppleVisionBackend)
    assert named_backend.provider == "mac_vision"

    # Also handles an objc module without an `error` exception class attribute
    no_error_objc = FakeObjCModule(error=None)
    plain_backend = AppleVisionBackend(
        provider="apple",
        vision_loader=lambda: (no_error_objc, fake_vision),
    )
    assert isinstance(plain_backend, AppleVisionBackend)

    monkeypatch.setitem(sys.modules, "Vision", None)
    with pytest.raises(AIError, match="supernote\\[apple\\]"):
        create_apple_backend({}, "apple")


def test_load_vision_runtime_missing_and_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_objc_mod = ModuleType("objc")
    fake_vision_mod = ModuleType("Vision")
    monkeypatch.setitem(sys.modules, "objc", fake_objc_mod)
    monkeypatch.setitem(sys.modules, "Vision", fake_vision_mod)

    loaded_objc, loaded_vision = _load_vision_runtime()
    assert loaded_objc is fake_objc_mod
    assert loaded_vision is fake_vision_mod

    monkeypatch.setitem(sys.modules, "Vision", None)
    with pytest.raises(AIError, match="supernote\\[apple\\]"):
        _load_vision_runtime()


async def test_recognize_text_accurate_and_fast(
    apple_backend: AppleVisionBackend,
    fake_objc: FakeObjCModule,
    fake_vision: FakeVisionModule,
) -> None:
    fake_vision.include_empty_observation = True
    fake_vision.lines = ["  Daily Log  ", None, "   ", "", "- Ship local Vision OCR"]

    accurate_text = await apple_backend.recognize_text(
        b"png-accurate", level=RecognitionLevel.VISION_ACCURATE
    )
    fast_text = await apple_backend.recognize_text(
        b"png-fast", level=RecognitionLevel.VISION_FAST
    )

    assert accurate_text == "Daily Log\n- Ship local Vision OCR"
    assert fast_text == "Daily Log\n- Ship local Vision OCR"
    assert fake_objc.pool_entries == 2
    assert fake_objc.active_pools == 0
    assert len(fake_vision.calls) == 2

    first_call, second_call = fake_vision.calls
    assert first_call.png_data == b"png-accurate"
    assert (
        first_call.recognition_level
        == fake_vision.VNRequestTextRecognitionLevelAccurate
    )
    assert first_call.uses_language_correction is True
    assert first_call.auto_detects_language is True

    assert second_call.png_data == b"png-fast"
    assert (
        second_call.recognition_level == fake_vision.VNRequestTextRecognitionLevelFast
    )


async def test_recognize_text_none_results(
    apple_backend: AppleVisionBackend,
    fake_vision: FakeVisionModule,
) -> None:
    fake_vision.return_none_results = True

    text = await apple_backend.recognize_text(b"png-bytes")
    assert text == ""


async def test_recognize_text_empty_data_and_nil_handler_raise_ai_error(
    apple_backend: AppleVisionBackend,
    fake_vision: FakeVisionModule,
) -> None:
    with pytest.raises(AIError, match="empty image data"):
        await apple_backend.recognize_text(b"")

    fake_vision.return_nil_handler = True
    with pytest.raises(AIError, match="failed to initialize image request handler"):
        await apple_backend.recognize_text(b"png-bytes")


async def test_recognize_text_vision_errors_raise_ai_error(
    apple_backend: AppleVisionBackend,
    fake_vision: FakeVisionModule,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_vision.perform_success = False
    fake_vision.perform_error = FakeNSError("corrupt PNG buffer")
    with caplog.at_level("ERROR"):
        with pytest.raises(AIError, match="corrupt PNG buffer"):
            await apple_backend.recognize_text(b"bad-png")
    assert "corrupt PNG buffer" in caplog.text

    fake_vision.perform_error = None
    with pytest.raises(AIError, match="unknown Vision error"):
        await apple_backend.recognize_text(b"bad-png")

    fake_vision.perform_error = "plain error string"
    with pytest.raises(AIError, match="plain error string"):
        await apple_backend.recognize_text(b"bad-png")


async def test_recognize_text_objc_and_runtime_exceptions_raise_ai_error(
    apple_backend: AppleVisionBackend,
    fake_vision: FakeVisionModule,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_vision.raise_on_perform = FakeObjCError("NSInvalidArgumentException")
    with caplog.at_level("ERROR"):
        with pytest.raises(
            AIError,
            match="^Apple Vision error during recognize_text: NSInvalidArgumentException$",
        ):
            await apple_backend.recognize_text(b"png-bytes")
    assert "Apple Vision Objective-C error" not in caplog.text

    fake_vision.raise_on_perform = RuntimeError("unexpected bridge failure")
    with pytest.raises(AIError, match="unexpected bridge failure"):
        await apple_backend.recognize_text(b"png-bytes")


@pytest.mark.skipif(
    sys.platform != "darwin" or importlib.util.find_spec("Vision") is None,
    reason="Requires macOS with pyobjc-framework-Vision ('supernote[apple]') installed",
)
async def test_recognize_text_live_macos_vision() -> None:
    image = Image.new("RGB", (900, 260), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=42)
    draw.text((40, 40), "Supernote Local OCR", fill="black", font=font)
    draw.text((40, 120), "Apple Vision Engine", fill="black", font=font)

    buf = io.BytesIO()
    image.save(buf, format="PNG")

    backend = create_apple_backend({}, "apple")
    extracted = await backend.recognize_text(
        buf.getvalue(), level=RecognitionLevel.VISION_ACCURATE
    )

    assert "Supernote Local OCR" in extracted
    assert "Apple Vision Engine" in extracted
