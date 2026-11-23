"""Tests for `supernote.server.components.apple.backend` via the `apple` component."""

from __future__ import annotations

import importlib.util
import io
import sys

import pytest
from PIL import Image, ImageDraw, ImageFont

from supernote.server.ai.base import AIError
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.config import AiConfig, ModelConfig, ProviderConfig
from supernote.server.core import ServerCore
from supernote.server.keys import OCR_MODEL_KEY
from tests.server.components.conftest import LoadComponents

from .conftest import (
    FakeNSError,
    FakeObjCError,
    FakeObjCModule,
    FakeVisionModule,
    LoadAppleOcr,
)


async def test_apple_named_provider_routes_correctly(
    load_apple_ocr: LoadAppleOcr,
    fake_vision: FakeVisionModule,
) -> None:
    named_model = await load_apple_ocr(
        "vision-accurate",
        provider="mac_vision",
        providers={"mac_vision": ProviderConfig(type="apple")},
    )
    assert named_model.provider == "mac_vision"
    assert await named_model.extract_text(b"png", "prompt") == (
        "Daily Log\n- Ship local Vision OCR"
    )
    assert len(fake_vision.calls) == 1


async def test_apple_handles_objc_without_error_attr(
    monkeypatch: pytest.MonkeyPatch,
    component_core: ServerCore,
    load_components: LoadComponents,
    fake_vision: FakeVisionModule,
) -> None:
    monkeypatch.setitem(sys.modules, "objc", FakeObjCModule(error=None))  # type: ignore[arg-type]
    monkeypatch.setitem(sys.modules, "Vision", fake_vision)  # type: ignore[arg-type]
    component_core.config.ai = AiConfig(
        ocr=ModelConfig(provider="apple", model="vision-accurate"),
    )
    await load_components("ai", "apple")
    model = component_core.app[OCR_MODEL_KEY]
    assert model is not None
    assert await model.extract_text(b"png", "prompt") == (
        "Daily Log\n- Ship local Vision OCR"
    )


async def test_recognize_text_filters_empty_lines_and_manages_autorelease_pool(
    apple_ocr_model: OcrModel,
    fake_objc: FakeObjCModule,
    fake_vision: FakeVisionModule,
) -> None:
    fake_vision.include_empty_observation = True
    fake_vision.lines = ["  Daily Log  ", None, "   ", "", "- Ship local Vision OCR"]

    text = await apple_ocr_model.extract_text(b"png-accurate", "prompt")

    assert text == "Daily Log\n- Ship local Vision OCR"
    assert fake_objc.pool_entries == 1
    assert fake_objc.active_pools == 0
    assert len(fake_vision.calls) == 1

    call = fake_vision.calls[0]
    assert call.png_data == b"png-accurate"
    assert call.recognition_level == fake_vision.VNRequestTextRecognitionLevelAccurate
    assert call.uses_language_correction is True
    assert call.auto_detects_language is True


async def test_recognize_text_none_results(
    apple_ocr_model: OcrModel,
    fake_vision: FakeVisionModule,
) -> None:
    fake_vision.return_none_results = True

    text = await apple_ocr_model.extract_text(b"png-bytes", "prompt")
    assert text == ""


async def test_recognize_text_empty_data_and_nil_handler_raise_ai_error(
    apple_ocr_model: OcrModel,
    fake_vision: FakeVisionModule,
) -> None:
    with pytest.raises(AIError, match="empty image data"):
        await apple_ocr_model.extract_text(b"", "prompt")

    fake_vision.return_nil_handler = True
    with pytest.raises(AIError, match="failed to initialize image request handler"):
        await apple_ocr_model.extract_text(b"png-bytes", "prompt")


async def test_recognize_text_vision_errors_raise_ai_error(
    apple_ocr_model: OcrModel,
    fake_vision: FakeVisionModule,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_vision.perform_success = False
    fake_vision.perform_error = FakeNSError("corrupt PNG buffer")
    with caplog.at_level("ERROR"):
        with pytest.raises(AIError, match="corrupt PNG buffer"):
            await apple_ocr_model.extract_text(b"bad-png", "prompt")
    assert "corrupt PNG buffer" in caplog.text

    fake_vision.perform_error = None
    with pytest.raises(AIError, match="unknown Vision error"):
        await apple_ocr_model.extract_text(b"bad-png", "prompt")

    fake_vision.perform_error = "plain error string"
    with pytest.raises(AIError, match="plain error string"):
        await apple_ocr_model.extract_text(b"bad-png", "prompt")


async def test_recognize_text_objc_and_runtime_exceptions_raise_ai_error(
    apple_ocr_model: OcrModel,
    fake_vision: FakeVisionModule,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_vision.raise_on_perform = FakeObjCError("NSInvalidArgumentException")
    with caplog.at_level("ERROR"):
        with pytest.raises(
            AIError,
            match="^Apple Vision error during recognize_text: NSInvalidArgumentException$",
        ):
            await apple_ocr_model.extract_text(b"png-bytes", "prompt")
    assert "Apple Vision Objective-C error" not in caplog.text

    fake_vision.raise_on_perform = RuntimeError("unexpected bridge failure")
    with pytest.raises(AIError, match="unexpected bridge failure"):
        await apple_ocr_model.extract_text(b"png-bytes", "prompt")


@pytest.mark.skipif(
    sys.platform != "darwin" or importlib.util.find_spec("Vision") is None,
    reason="Requires macOS with pyobjc-framework-Vision ('supernote[apple]') installed",
)
async def test_recognize_text_live_macos_vision(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    image = Image.new("RGB", (900, 260), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=42)
    draw.text((40, 40), "Supernote Local OCR", fill="black", font=font)
    draw.text((40, 120), "Apple Vision Engine", fill="black", font=font)

    buf = io.BytesIO()
    image.save(buf, format="PNG")

    component_core.config.ai = AiConfig(
        ocr=ModelConfig(provider="apple", model="vision-accurate"),
    )
    await load_components("ai", "apple")
    ocr_model = component_core.app[OCR_MODEL_KEY]
    assert ocr_model is not None

    extracted = await ocr_model.extract_text(buf.getvalue(), "prompt")
    assert "Supernote Local OCR" in extracted
    assert "Apple Vision Engine" in extracted
