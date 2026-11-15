"""Tests for `supernote.server.ai.models.apple.ocr`."""

from __future__ import annotations

import sys

import pytest
from prometheus_client import REGISTRY

from supernote.server.ai.base import AIError
from supernote.server.ai.models.apple.backend import AppleVisionBackend
from supernote.server.ai.models.apple.ocr import (
    SUPPORTED_APPLE_OCR_MODELS,
    AppleOcrModel,
    create_ocr_model,
)
from supernote.server.ai.models.ocr import InstrumentedOcrModel
from supernote.server.config import AiConfig, ModelConfig, ServerConfig

from .conftest import FakeNSError, FakeObjCModule, FakeVisionModule


async def test_apple_ocr_model(
    apple_backend: AppleVisionBackend,
    fake_vision: FakeVisionModule,
) -> None:
    accurate_model = InstrumentedOcrModel(
        AppleOcrModel(apple_backend, "vision-accurate")
    )
    fast_model = InstrumentedOcrModel(AppleOcrModel(apple_backend, "vision-fast"))

    accurate_labels = {
        "provider": "apple",
        "model": "vision-accurate",
        "stage": "ocr",
        "status": "success",
    }
    fast_labels = {
        "provider": "apple",
        "model": "vision-fast",
        "stage": "ocr",
        "status": "success",
    }
    accurate_before = (
        REGISTRY.get_sample_value("supernote_ai_requests_total", accurate_labels) or 0.0
    )
    fast_before = (
        REGISTRY.get_sample_value("supernote_ai_requests_total", fast_labels) or 0.0
    )

    text = await accurate_model.extract_text(b"png-bytes", "Ignored VLM prompt")
    await fast_model.extract_text(b"png-fast-bytes", "Ignored VLM prompt")

    assert accurate_model.provider == "apple"
    assert accurate_model.model_id == "vision-accurate"
    assert fast_model.model_id == "vision-fast"
    assert text == "Daily Log\n- Ship local Vision OCR"
    assert len(fake_vision.calls) == 2
    assert (
        fake_vision.calls[0].recognition_level
        == fake_vision.VNRequestTextRecognitionLevelAccurate
    )
    assert (
        fake_vision.calls[1].recognition_level
        == fake_vision.VNRequestTextRecognitionLevelFast
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", accurate_labels)
        == accurate_before + 1.0
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", fast_labels)
        == fast_before + 1.0
    )

    fail_labels = {
        "provider": "apple",
        "model": "vision-accurate",
        "stage": "ocr",
        "status": "failure",
    }
    fail_before = (
        REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels) or 0.0
    )
    fake_vision.perform_success = False
    fake_vision.perform_error = FakeNSError("corrupt image")
    with pytest.raises(AIError, match="corrupt image"):
        await accurate_model.extract_text(b"bad-png", "Ignored")
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", fail_labels)
        == fail_before + 1.0
    )


@pytest.mark.parametrize(
    "invalid_model",
    [
        "accurate",
        "fast",
        "vision",
        " VISION-ACCURATE ",
        "VISION-ACCURATE",
        "unsupported-vision-model",
    ],
)
def test_create_ocr_model_rejects_non_canonical_names(invalid_model: str) -> None:
    invalid_config = ServerConfig(
        ai=AiConfig(
            ocr=ModelConfig(provider="apple", model=invalid_model),
        )
    )
    with pytest.raises(ValueError, match="Unsupported Apple OCR model"):
        create_ocr_model(invalid_config)


def test_create_ocr_model_startup_validation(
    monkeypatch: pytest.MonkeyPatch,
    fake_objc: FakeObjCModule,
    fake_vision: FakeVisionModule,
) -> None:
    assert create_ocr_model(ServerConfig()) is None
    assert SUPPORTED_APPLE_OCR_MODELS == ("vision-accurate", "vision-fast")

    monkeypatch.setitem(sys.modules, "objc", fake_objc)  # type: ignore[arg-type]
    monkeypatch.setitem(sys.modules, "Vision", fake_vision)  # type: ignore[arg-type]

    for model_name in SUPPORTED_APPLE_OCR_MODELS:
        config = ServerConfig(
            ai=AiConfig(
                ocr=ModelConfig(provider="apple", model=model_name),
            )
        )
        model = create_ocr_model(config)
        assert isinstance(model, AppleOcrModel)
        assert model.model_id == model_name

    monkeypatch.setitem(sys.modules, "Vision", None)
    missing_dep_config = ServerConfig(
        ai=AiConfig(
            ocr=ModelConfig(provider="apple", model="vision-accurate"),
        )
    )
    with pytest.raises(AIError, match="supernote\\[apple\\]"):
        create_ocr_model(missing_dep_config)
