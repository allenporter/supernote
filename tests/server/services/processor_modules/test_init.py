import asyncio

import pytest
from prometheus_client import REGISTRY

from supernote.models.base import ProcessingStatus, TaskType
from supernote.server.components.transcript.processor import OcrModule
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.metrics import PIPELINE_DURATION_BUCKETS
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules import (
    DuplicateTaskError,
    MissingTaskDependencyError,
    ProcessorModule,
    TaskDependencyCycleError,
    TaskGraph,
    TaskScope,
)
from supernote.server.utils.tasks import get_task


class _StubModule(ProcessorModule):
    def __init__(
        self,
        *,
        module_name: str,
        enabled: bool = True,
        version: str | None = "v1",
        error: BaseException | None = None,
    ) -> None:
        self._module_name = module_name
        self._enabled = enabled
        self._version = version
        self._error = error
        self.process_calls = 0

    @property
    def name(self) -> str:
        return self._module_name

    @property
    def task_type(self) -> TaskType:
        return TaskType.PAGE_HASHING

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def version(self) -> str | None:
        return self._version

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        self.process_calls += 1
        if self._error is not None:
            raise self._error


def _task_count(module: str, status: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "supernote_processor_tasks_total",
            {"module": module, "status": status},
        )
        or 0.0
    )


def _duration_count(module: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "supernote_processor_task_duration_seconds_count",
            {"module": module},
        )
        or 0.0
    )


async def test_processor_module_success_and_skipped_metrics(
    session_manager: DatabaseSessionManager,
) -> None:
    """Completed tasks record `skipped` on repeat runs without polluting duration histograms."""
    module_name = "TestSuccessAndSkipModule"
    module = _StubModule(module_name=module_name, version="v1")

    before_ok = _task_count(module_name, "success")
    before_skip = _task_count(module_name, "skipped")
    before_dur = _duration_count(module_name)

    # First run executes process(), marks COMPLETED, and observes duration.
    assert await module.run(101, session_manager, page_id="p1") is True
    assert module.process_calls == 1
    assert _task_count(module_name, "success") == before_ok + 1.0
    assert _task_count(module_name, "skipped") == before_skip
    assert _duration_count(module_name) == before_dur + 1.0

    for bucket in PIPELINE_DURATION_BUCKETS:
        bucket_val = REGISTRY.get_sample_value(
            "supernote_processor_task_duration_seconds_bucket",
            {"module": module_name, "le": str(bucket)},
        )
        assert bucket_val is not None

    task = await get_task(session_manager, 101, TaskType.PAGE_HASHING, "page_p1")
    assert task is not None
    assert task.status == ProcessingStatus.COMPLETED
    assert task.data == "v1"

    # Second run sees COMPLETED checkpoint at matching version -> status="skipped", no 0s duration.
    assert await module.run(101, session_manager, page_id="p1") is True
    assert module.process_calls == 1
    assert _task_count(module_name, "success") == before_ok + 1.0
    assert _task_count(module_name, "skipped") == before_skip + 1.0
    assert _duration_count(module_name) == before_dur + 1.0


async def test_processor_module_disabled_emits_no_metrics(
    session_manager: DatabaseSessionManager,
    file_service: FileService,
) -> None:
    """Disabled modules return True immediately without emitting `skipped` counter noise."""
    stub_name = "TestDisabledModule"
    disabled_stub = _StubModule(module_name=stub_name, enabled=False)

    assert await disabled_stub.run(202, session_manager, page_id="p1") is True
    assert disabled_stub.process_calls == 0
    for status in ("success", "failure", "skipped", "cancelled"):
        assert (
            REGISTRY.get_sample_value(
                "supernote_processor_tasks_total",
                {"module": stub_name, "status": status},
            )
            is None
        )
    assert _duration_count(stub_name) == 0.0

    # Also verify a real disabled AI module (`OcrModule` with `ocr_model=None`) does not emit `skipped`.
    disabled_ocr = OcrModule(file_service=file_service, ocr_model=None)
    before_ocr_skip = _task_count(disabled_ocr.name, "skipped")
    before_ocr_dur = _duration_count(disabled_ocr.name)

    assert (
        await disabled_ocr.run(202, session_manager, page_index=0, page_id="p1") is True
    )
    assert _task_count(disabled_ocr.name, "skipped") == before_ocr_skip
    assert _duration_count(disabled_ocr.name) == before_ocr_dur


async def test_processor_module_failure_and_cancellation_metrics(
    session_manager: DatabaseSessionManager,
) -> None:
    """Exceptions record `failure` + duration; `CancelledError` records `cancelled` without duration."""
    fail_name = "TestFailureModule"
    fail_module = _StubModule(
        module_name=fail_name,
        error=RuntimeError("boom"),
    )

    assert await fail_module.run(303, session_manager) is False
    assert _task_count(fail_name, "failure") == 1.0
    assert _duration_count(fail_name) == 1.0

    failed_task = await get_task(session_manager, 303, TaskType.PAGE_HASHING, "global")
    assert failed_task is not None
    assert failed_task.status == ProcessingStatus.FAILED
    assert failed_task.last_error == "RuntimeError: boom"

    cancel_name = "TestCancelledModule"
    cancel_module = _StubModule(
        module_name=cancel_name,
        error=asyncio.CancelledError(),
    )

    with pytest.raises(asyncio.CancelledError):
        await cancel_module.run(304, session_manager)

    assert _task_count(cancel_name, "cancelled") == 1.0
    assert _task_count(cancel_name, "failure") == 0.0
    assert _duration_count(cancel_name) == 0.0

    assert await cancel_module.cleanup_file(304, 1, session_manager) is None


class _GraphModule(ProcessorModule):
    def __init__(
        self,
        task_type: str,
        *,
        scope: TaskScope = TaskScope.FILE,
        depends_on: tuple[str, ...] = (),
        enabled: bool = True,
    ) -> None:
        self._task_type = task_type
        self._scope = scope
        self._depends_on = depends_on
        self._enabled = enabled

    @property
    def name(self) -> str:
        return f"Mod_{self._task_type}"

    @property
    def task_type(self) -> str:
        return self._task_type

    @property
    def scope(self) -> TaskScope:
        return self._scope

    @property
    def depends_on(self) -> tuple[str, ...]:
        return self._depends_on

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: int | None = None,
        page_id: str | None = None,
        **kwargs: object,
    ) -> None:
        return None


def test_task_graph_build_order_ancestors_descendants_and_subset() -> None:
    """TaskGraph topologically sorts modules, tracks ancestry, and computes subsets."""
    # Register in reverse/mixed order to verify topological sorting + tie-breaking.
    summary = _GraphModule(
        TaskType.SUMMARY_GENERATION,
        scope=TaskScope.FILE,
        depends_on=(TaskType.OCR_EXTRACTION,),
    )
    embedding = _GraphModule(
        TaskType.EMBEDDING_GENERATION,
        scope=TaskScope.PAGE,
        depends_on=(TaskType.OCR_EXTRACTION,),
    )
    ocr = _GraphModule(
        TaskType.OCR_EXTRACTION,
        scope=TaskScope.PAGE,
        depends_on=(TaskType.PNG_CONVERSION,),
    )
    png = _GraphModule(
        TaskType.PNG_CONVERSION,
        scope=TaskScope.PAGE,
        depends_on=(TaskType.PAGE_HASHING,),
    )
    hashing = _GraphModule(TaskType.PAGE_HASHING, scope=TaskScope.FILE)

    graph = TaskGraph.build([summary, embedding, ocr, png, hashing])
    assert [m.task_type for m in graph.modules] == [
        TaskType.PAGE_HASHING,
        TaskType.PNG_CONVERSION,
        TaskType.OCR_EXTRACTION,
        TaskType.SUMMARY_GENERATION,
        TaskType.EMBEDDING_GENERATION,
    ]
    assert graph.ancestors(TaskType.SUMMARY_GENERATION) == frozenset(
        {"HASHING", "PNG_CONVERSION", "OCR_EXTRACTION"}
    )
    assert graph.has_page_ancestor(TaskType.SUMMARY_GENERATION) is True
    assert graph.has_page_ancestor(TaskType.PAGE_HASHING) is False

    # Subset automatically pulls in transitive ancestors.
    png_sub = graph.subset({TaskType.PNG_CONVERSION})
    assert [m.task_type for m in png_sub.modules] == [
        TaskType.PAGE_HASHING,
        TaskType.PNG_CONVERSION,
    ]

    # Excluding page-dependent FILE tasks drops SUMMARY and any downstream PAGE wave cleanly.
    w1 = _GraphModule("W1", scope=TaskScope.FILE)
    w2 = _GraphModule("W2", scope=TaskScope.PAGE, depends_on=("W1",))
    w3 = _GraphModule("W3", scope=TaskScope.FILE, depends_on=("W2",))
    w4 = _GraphModule("W4", scope=TaskScope.PAGE, depends_on=("W3",))
    multi = TaskGraph.build([w1, w2, w3, w4])
    page_only = multi.subset(
        [m.task_type for m in multi.modules],
        exclude_page_dependent_file_tasks=True,
    )
    assert [m.task_type for m in page_only.modules] == ["W1", "W2"]


def test_task_graph_validation_and_effective_enabled() -> None:
    """TaskGraph rejects duplicates, missing deps, and cycles, and propagates disabled upstream."""
    with pytest.raises(DuplicateTaskError):
        TaskGraph.build([_GraphModule("A"), _GraphModule("A")])

    with pytest.raises(MissingTaskDependencyError) as missing_exc:
        TaskGraph.build([_GraphModule("B", depends_on=("A",))])
    assert missing_exc.value.task_type == "B"
    assert missing_exc.value.dependency == "A"

    with pytest.raises(TaskDependencyCycleError):
        TaskGraph.build([_GraphModule("A", depends_on=("A",))])

    with pytest.raises(TaskDependencyCycleError):
        TaskGraph.build(
            [
                _GraphModule("A", depends_on=("B",)),
                _GraphModule("B", depends_on=("A",)),
            ]
        )

    graph = TaskGraph.build(
        [
            _GraphModule("A", enabled=True),
            _GraphModule("B", depends_on=("A",), enabled=False),
            _GraphModule("C", depends_on=("B",), enabled=True),
        ]
    )
    assert graph.is_effectively_enabled("A") is True
    assert graph.is_effectively_enabled("B") is False
    assert graph.is_effectively_enabled("C") is False
