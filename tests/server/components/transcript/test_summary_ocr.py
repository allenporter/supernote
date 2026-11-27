"""Tests for background handwriting OCR on Supernote Digest annotations (`SummaryOcrRunner`)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from supernote.models.summary import AddSummaryDTO, UpdateSummaryDTO
from supernote.server.ai.models.ocr import OcrModel
from supernote.server.components.ai import OCR_MODEL_KEY
from supernote.server.components.fake_ai.ocr import FakeOcrModel
from supernote.server.components.summary import SUMMARY_SERVICE_KEY
from supernote.server.components.transcript import TRANSCRIPT_SERVICE_KEY
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.core import ServerCore
from supernote.server.services.blob import BlobStorage
from tests.fixtures.server import TEST_USERNAME
from tests.server.components.conftest import LoadComponents

DIGEST_MARK = "schaefer-dev/garmin_connect_20260016.pdf.mark"
TWO_PAGE_MARK = "philips/blank-a6x-3.26.40-two-pages.note"
FAKE_OCR_CONFIG = {
    "ai": {
        "ocr": {
            "provider": "fake_ai",
            "model": "fake-ocr-v1",
        }
    }
}


def _unwrap_fake_ocr(model: OcrModel | None) -> FakeOcrModel:
    """Unwrap telemetry/concurrency wrappers around the registered `FakeOcrModel`."""
    current: object = model
    while hasattr(current, "_model"):
        current = current._model
    assert isinstance(current, FakeOcrModel)
    return current


class _BlockingOcrModel(OcrModel):
    """Test OCR model that signals entry and waits until cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    @property
    def provider(self) -> str:
        return "fake"

    @property
    def model_id(self) -> str:
        return "blocking-ocr-v1"

    async def extract_text(self, png_data: bytes, prompt: str) -> str:
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return ""


async def test_summary_create_same_md5_noop_and_update_reocr(
    component_core: ServerCore,
    load_components: LoadComponents,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    """Verify create triggers OCR, same md5 is a no-op, and updated md5 re-runs OCR."""
    await load_components("summary", "transcript", "fake_ai", configs=FAKE_OCR_CONFIG)
    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]
    fake_ocr = _unwrap_fake_ocr(component_core.app[OCR_MODEL_KEY])

    mark_bytes = (test_data_dir / DIGEST_MARK).read_bytes()
    await blob_storage.put(USER_DATA_BUCKET, "digest_v1.mark", mark_bytes)
    await blob_storage.put(USER_DATA_BUCKET, "digest_v2.mark", mark_bytes)

    # 1. Creating a digest with handwriting triggers background OCR and persists transcript.
    created = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-ocr-1",
            content="Highlighted excerpt",
            source_path="/Document/Garmin_Connect.pdf",
            handwrite_inner_name="digest_v1.mark",
            handwrite_md5="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
        ),
    )
    assert created.id is not None
    await component_core.event_bus.wait_idle()

    transcript_v1 = await transcript_service.get_summary_transcript(
        test_user_id, created.id
    )
    assert transcript_v1 is not None
    assert transcript_v1.summary_id == created.id
    assert transcript_v1.handwrite_md5 == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
    assert transcript_v1.model_id == "fake-ocr-v1"
    assert transcript_v1.text.startswith("Transcribed (")
    assert len(fake_ocr.calls) == 1
    png_bytes, prompt = fake_ocr.calls[0]
    assert png_bytes.startswith(b"\x89PNG")
    assert "Garmin_Connect.pdf" in prompt

    # 2. Re-triggering with the same handwrite_md5 is a no-op (not re-OCR'd).
    updated_same = await summary_service.update_summary(
        TEST_USERNAME,
        UpdateSummaryDTO(
            id=created.id,
            comment_str="Edited text comment only",
            handwrite_inner_name="digest_v1.mark",
            handwrite_md5="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
        ),
    )
    assert updated_same is True
    await component_core.event_bus.wait_idle()

    assert len(fake_ocr.calls) == 1
    transcript_after_noop = await transcript_service.get_summary_transcript(
        test_user_id, created.id
    )
    assert transcript_after_noop == transcript_v1

    # 3. Updating handwrite_md5 re-runs OCR and updates the stored transcript.
    updated_new = await summary_service.update_summary(
        TEST_USERNAME,
        UpdateSummaryDTO(
            id=created.id,
            handwrite_inner_name="digest_v2.mark",
            handwrite_md5="f6e5d4c3b2a1f6e5d4c3b2a1f6e5d4c3",
        ),
    )
    assert updated_new is True
    await component_core.event_bus.wait_idle()

    assert len(fake_ocr.calls) == 2
    transcript_v2 = await transcript_service.get_summary_transcript(
        test_user_id, created.id
    )
    assert transcript_v2 is not None
    assert transcript_v2.handwrite_md5 == "f6e5d4c3b2a1f6e5d4c3b2a1f6e5d4c3"
    assert transcript_v2.model_id == "fake-ocr-v1"
    assert transcript_v2.text.startswith("Transcribed (")


async def test_summary_ocr_noop_when_ocr_model_not_configured(
    component_core: ServerCore,
    load_components: LoadComponents,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    """Verify no transcript is created when no OCR model is configured."""
    await load_components("summary", "transcript")
    assert component_core.app[OCR_MODEL_KEY] is None

    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    await blob_storage.put(
        USER_DATA_BUCKET,
        "digest_no_ocr.mark",
        (test_data_dir / DIGEST_MARK).read_bytes(),
    )
    created = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-no-ocr-1",
            content="Highlighted excerpt",
            handwrite_inner_name="digest_no_ocr.mark",
            handwrite_md5="11111111111111111111111111111111",
        ),
    )
    assert created.id is not None
    await component_core.event_bus.wait_idle()

    assert (
        await transcript_service.get_summary_transcript(test_user_id, created.id)
        is None
    )


async def test_summary_ocr_noop_without_handwriting_or_missing_blob(
    component_core: ServerCore,
    load_components: LoadComponents,
    test_user_id: int,
) -> None:
    """Verify summaries without handwriting or with missing `.mark` blobs are handled safely."""
    await load_components("summary", "transcript", "fake_ai", configs=FAKE_OCR_CONFIG)
    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]
    fake_ocr = _unwrap_fake_ocr(component_core.app[OCR_MODEL_KEY])

    text_only = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-text-only-1",
            content="Text-only digest without handwriting",
        ),
    )
    missing_blob = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-missing-blob-1",
            content="Digest referencing an unuploaded mark blob",
            handwrite_inner_name="does_not_exist.mark",
            handwrite_md5="22222222222222222222222222222222",
        ),
    )
    assert text_only.id is not None
    assert missing_blob.id is not None
    await component_core.event_bus.wait_idle()

    assert fake_ocr.calls == []
    assert (
        await transcript_service.get_summary_transcript(test_user_id, text_only.id)
        is None
    )
    assert (
        await transcript_service.get_summary_transcript(test_user_id, missing_blob.id)
        is None
    )


async def test_summary_ocr_nonblocking_and_cancelled_on_stop(
    component_core: ServerCore,
    load_components: LoadComponents,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    """Verify summary creation does not block on OCR and `async_stop` cancels in-flight OCR."""
    loader = await load_components("summary", "transcript")
    blocking_ocr = _BlockingOcrModel()
    component_core.app[OCR_MODEL_KEY] = blocking_ocr

    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]

    await blob_storage.put(
        USER_DATA_BUCKET,
        "digest_blocking.mark",
        (test_data_dir / DIGEST_MARK).read_bytes(),
    )

    # Summary creation returns immediately even while OCR blocks.
    created = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-blocking-1",
            content="Non-blocking check",
            handwrite_inner_name="digest_blocking.mark",
            handwrite_md5="33333333333333333333333333333333",
        ),
    )
    assert created.id is not None

    await asyncio.wait_for(blocking_ocr.started.wait(), timeout=5.0)
    await loader.async_stop_all(component_core)

    assert blocking_ocr.cancelled is True
    assert (
        await transcript_service.get_summary_transcript(test_user_id, created.id)
        is None
    )


async def test_summary_ocr_joins_multiple_pages(
    component_core: ServerCore,
    load_components: LoadComponents,
    blob_storage: BlobStorage,
    test_user_id: int,
    test_data_dir: Path,
) -> None:
    """Verify multi-page handwriting annotations OCR each page and join text cleanly."""
    await load_components("summary", "transcript", "fake_ai", configs=FAKE_OCR_CONFIG)
    summary_service = component_core.app[SUMMARY_SERVICE_KEY]
    transcript_service = component_core.app[TRANSCRIPT_SERVICE_KEY]
    fake_ocr = _unwrap_fake_ocr(component_core.app[OCR_MODEL_KEY])

    await blob_storage.put(
        USER_DATA_BUCKET,
        "digest_two_pages.mark",
        (test_data_dir / TWO_PAGE_MARK).read_bytes(),
    )
    created = await summary_service.add_summary(
        TEST_USERNAME,
        AddSummaryDTO(
            unique_identifier="digest-multipage-1",
            content="Multi-page annotation",
            handwrite_inner_name="digest_two_pages.mark",
            handwrite_md5="44444444444444444444444444444444",
        ),
    )
    assert created.id is not None
    await component_core.event_bus.wait_idle()

    assert len(fake_ocr.calls) == 2
    transcript = await transcript_service.get_summary_transcript(
        test_user_id, created.id
    )
    assert transcript is not None
    expected = "\n\n".join(
        f"Transcribed ({len(png)} bytes)" for png, _ in fake_ocr.calls
    )
    assert transcript.text == expected
