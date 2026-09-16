import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from supernote.server.config import ServerConfig
from supernote.server.services.hermes_summary import (
    DEFAULT_UNCERTAINTY_FOOTER,
    HermesSummaryProcessError,
    HermesSummaryService,
    HermesSummaryTimeoutError,
)


def make_mock_process(
    stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0, hang: bool = False
) -> AsyncMock:
    process = AsyncMock()
    process.returncode = returncode

    async def communicate(_input: bytes | None = None) -> tuple[bytes, bytes]:
        if hang:
            await asyncio.sleep(999)
        return stdout, stderr

    process.communicate = communicate
    # `Process.kill()` is a synchronous method on asyncio's subprocess API;
    # `Process.wait()` is the coroutine that reaps it.
    process.kill = MagicMock()
    process.wait = AsyncMock()
    return process


def make_service(
    language: str | None = None,
    timeout_seconds: int | float = 180,
    command: str = "hermes chat -q",
    model: str | None = None,
    workdir: str | None = None,
) -> HermesSummaryService:
    return HermesSummaryService(
        command=command,
        timeout_seconds=timeout_seconds,
        model=model,
        workdir=workdir,
        language=language,
    )


async def test_prompt_contains_file_name_and_transcript() -> None:
    service = make_service()
    transcript = "This is the OCR transcript, with some garbled text."
    prompt = service._build_prompt(
        file_name="notebook-2026-01-01.note",
        transcript=transcript,
        page_count=3,
        existing_context_hint=None,
    )

    assert "notebook-2026-01-01.note" in prompt
    assert transcript in prompt


async def test_prompt_contains_all_requirements() -> None:
    service = make_service()
    prompt = service._build_prompt(
        file_name="f.note",
        transcript="hello world",
        page_count=1,
        existing_context_hint=None,
    )

    assert "Markdown only" in prompt
    assert "primary evidence" in prompt
    assert "memory" in prompt.lower()
    assert "uncertain" in prompt.lower()
    assert "not invent facts" in prompt.lower() or "invent facts" in prompt.lower()
    assert "open questions" in prompt.lower()
    assert "uncertainty-disclosure" in prompt.lower() or "uncertainty" in prompt.lower()


async def test_prompt_requests_configured_language_when_set() -> None:
    service = make_service(language="Finnish")
    prompt = service._build_prompt(
        file_name="f.note",
        transcript="hello",
        page_count=1,
        existing_context_hint=None,
    )

    assert "Respond in Finnish" in prompt


async def test_prompt_infers_language_when_unset() -> None:
    service = make_service(language=None)
    prompt = service._build_prompt(
        file_name="f.note",
        transcript="hello",
        page_count=1,
        existing_context_hint=None,
    )

    assert "same language as the OCR transcript" in prompt
    assert "infer" in prompt.lower()


async def test_prompt_includes_existing_context_hint_when_provided() -> None:
    service = make_service()
    prompt = service._build_prompt(
        file_name="f.note",
        transcript="hello",
        page_count=1,
        existing_context_hint="User is tracking a recipe project.",
    )

    assert "User is tracking a recipe project." in prompt


async def test_generate_interpretation_calls_subprocess_not_real_binary() -> None:
    service = make_service()
    stdout = f"# Summary\n\nSome interpreted content.\n\n{DEFAULT_UNCERTAINTY_FOOTER}".encode()
    mock_process = make_mock_process(stdout=stdout, returncode=0)

    with patch(
        "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)
    ) as mock_exec:
        result = await service.generate_interpretation(
            file_id=1,
            file_name="f.note",
            transcript="hello world",
            page_count=2,
        )

    mock_exec.assert_called_once()
    args, kwargs = mock_exec.call_args
    assert args[0] == "hermes"
    assert "chat" in args
    assert "-q" in args
    assert kwargs["stdin"] is not None
    assert "Summary" in result


async def test_generate_interpretation_passes_prompt_via_stdin_not_shell_string() -> (
    None
):
    service = make_service()
    mock_process = make_mock_process(stdout=b"ok", returncode=0)

    captured_input: dict[str, bytes | None] = {}

    async def communicate(input: bytes | None = None) -> tuple[bytes, bytes]:
        captured_input["input"] = input
        return b"ok", b""

    mock_process.communicate = communicate

    dangerous_transcript = "hello; rm -rf / #`whoami`$(echo pwned)"

    with patch(
        "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)
    ) as mock_exec:
        await service.generate_interpretation(
            file_id=1,
            file_name="f.note",
            transcript=dangerous_transcript,
            page_count=1,
        )

    # The command is executed via argv (create_subprocess_exec, not a shell string),
    # and the dangerous transcript content is sent over stdin, never appended to argv.
    mock_exec.assert_called_once()
    args, _kwargs = mock_exec.call_args
    for arg in args:
        assert dangerous_transcript not in arg
    sent_stdin = captured_input["input"]
    assert sent_stdin is not None
    assert dangerous_transcript.encode() in sent_stdin


async def test_generate_interpretation_raises_on_timeout() -> None:
    service = make_service(timeout_seconds=0.01)
    mock_process = make_mock_process(hang=True)

    with patch(
        "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)
    ):
        with pytest.raises(HermesSummaryTimeoutError):
            await service.generate_interpretation(
                file_id=1,
                file_name="f.note",
                transcript="hello",
                page_count=1,
            )

    mock_process.kill.assert_called_once()


async def test_generate_interpretation_raises_on_nonzero_exit() -> None:
    service = make_service()
    mock_process = make_mock_process(
        stdout=b"", stderr=b"hermes: model not found", returncode=1
    )

    with patch(
        "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)
    ):
        with pytest.raises(HermesSummaryProcessError):
            await service.generate_interpretation(
                file_id=1,
                file_name="f.note",
                transcript="hello",
                page_count=1,
            )


async def test_uncertainty_footer_appended_when_missing_from_cli_output() -> None:
    service = make_service()
    mock_process = make_mock_process(stdout=b"# Summary\n\nSome content.", returncode=0)

    with patch(
        "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)
    ):
        result = await service.generate_interpretation(
            file_id=1,
            file_name="f.note",
            transcript="hello",
            page_count=1,
        )

    assert DEFAULT_UNCERTAINTY_FOOTER in result


async def test_uncertainty_footer_not_duplicated_when_cli_already_includes_one() -> (
    None
):
    service = make_service()
    stdout = f"# Summary\n\nSome content.\n\n{DEFAULT_UNCERTAINTY_FOOTER}".encode()
    mock_process = make_mock_process(stdout=stdout, returncode=0)

    with patch(
        "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)
    ):
        result = await service.generate_interpretation(
            file_id=1,
            file_name="f.note",
            transcript="hello",
            page_count=1,
        )

    assert result.count(DEFAULT_UNCERTAINTY_FOOTER) == 1


async def test_generate_interpretation_uses_configured_workdir() -> None:
    service = make_service(workdir="/some/hermes/workdir")
    mock_process = make_mock_process(stdout=b"ok", returncode=0)

    with patch(
        "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)
    ) as mock_exec:
        await service.generate_interpretation(
            file_id=1,
            file_name="f.note",
            transcript="hello",
            page_count=1,
        )

    _args, kwargs = mock_exec.call_args
    assert kwargs["cwd"] == "/some/hermes/workdir"


async def test_generate_interpretation_appends_model_flag_when_configured() -> None:
    service = make_service(model="hermes-3-large")
    mock_process = make_mock_process(stdout=b"ok", returncode=0)

    with patch(
        "asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)
    ) as mock_exec:
        await service.generate_interpretation(
            file_id=1,
            file_name="f.note",
            transcript="hello",
            page_count=1,
        )

    args, _kwargs = mock_exec.call_args
    assert "--model" in args
    assert "hermes-3-large" in args


def test_hermes_summary_config_fields_are_readable() -> None:
    config = ServerConfig()
    assert config.hermes_summary_enabled is False
    assert config.hermes_summary_command == "hermes chat -q"
    assert config.hermes_summary_timeout_seconds == 180
    assert config.hermes_summary_model is None
    assert config.hermes_summary_workdir is None
    assert config.hermes_summary_language is None

    config.hermes_summary_enabled = True
    assert config.hermes_summary_enabled is True
