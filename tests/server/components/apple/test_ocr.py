"""Tests for `supernote.server.components.apple.ocr`."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from supernote.server.ai.base import AIError
from supernote.server.components.ai import OCR_MODEL_KEY
from supernote.server.components.apple.ocr import SUPPORTED_APPLE_OCR_MODELS
from supernote.server.config import AiConfig, ModelConfig
from supernote.server.core import ServerCore
from tests.server.components.conftest import LoadComponents

from .conftest import FakeNSError, FakeVisionModule, LoadAppleOcr


@pytest.mark.parametrize(
    ("model_name", "expected_level_attr"),
    [
        ("vision-accurate", "VNRequestTextRecognitionLevelAccurate"),
        ("vision-fast", "VNRequestTextRecognitionLevelFast"),
    ],
)
async def test_apple_ocr_model_success_and_metrics(
    load_apple_ocr: LoadAppleOcr,
    fake_vision: FakeVisionModule,
    model_name: str,
    expected_level_attr: str,
) -> None:
    model = await load_apple_ocr(model_name)
    labels = {
        "provider": "apple",
        "model": model_name,
        "stage": "ocr",
        "status": "success",
    }
    before = REGISTRY.get_sample_value("supernote_ai_requests_total", labels) or 0.0

    text = await model.extract_text(b"png-bytes", "Ignored VLM prompt")

    assert model.provider == "apple"
    assert model.model_id == model_name
    assert text == "Daily Log\n- Ship local Vision OCR"
    assert len(fake_vision.calls) == 1
    assert fake_vision.calls[0].recognition_level == getattr(
        fake_vision, expected_level_attr
    )
    assert (
        REGISTRY.get_sample_value("supernote_ai_requests_total", labels) == before + 1.0
    )


async def test_apple_ocr_model_failure_records_metric(
    load_apple_ocr: LoadAppleOcr,
    fake_vision: FakeVisionModule,
) -> None:
    model = await load_apple_ocr("vision-accurate")
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
        await model.extract_text(b"bad-png", "Ignored")

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
async def test_apple_ocr_rejects_non_canonical_names(
    load_apple_ocr: LoadAppleOcr,
    invalid_model: str,
) -> None:
    with pytest.raises(ValueError, match="Unsupported Apple OCR model"):
        await load_apple_ocr(invalid_model)


@pytest.mark.parametrize("fake_vision", [None])
async def test_apple_ocr_unconfigured_does_not_require_vision_runtime(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    assert SUPPORTED_APPLE_OCR_MODELS == ("vision-accurate", "vision-fast")
    await load_components("ai", "apple")
    assert component_core.app[OCR_MODEL_KEY] is None


@pytest.mark.parametrize("fake_vision", [None])
async def test_apple_ocr_missing_vision_runtime_fails_eagerly(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    component_core.config.ai = AiConfig(
        ocr=ModelConfig(provider="apple", model="vision-accurate"),
    )
    with pytest.raises(AIError, match="supernote\\[apple\\]"):
        await load_components("ai", "apple")
