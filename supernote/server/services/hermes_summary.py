"""Transport-neutral client for generating Hermes-powered interpretation summaries.

This service turns an OCR transcript into an interpreted Markdown summary by
shelling out to the Hermes Agent CLI. It does not know anything about the
processor pipeline that will eventually call it (that wiring is a separate,
later change) -- it only knows how to build a prompt from the given inputs and
run the configured CLI command against it.
"""

import asyncio
import logging
import shlex

logger = logging.getLogger(__name__)


DEFAULT_UNCERTAINTY_FOOTER = (
    "This is an interpretation derived from OCR text and context; "
    "uncertain passages are marked separately."
)
"""Fallback uncertainty-disclosure footer appended when the CLI output doesn't
already contain one of its own."""

# A distinctive substring used to detect whether the CLI's own response already
# carries some form of uncertainty disclosure, so we don't append a duplicate.
_UNCERTAINTY_FOOTER_MARKER = "interpretation derived from ocr"


class HermesSummaryError(Exception):
    """Base class for errors raised by :class:`HermesSummaryService`."""


class HermesSummaryTimeoutError(HermesSummaryError, TimeoutError):
    """Raised when the Hermes CLI subprocess does not finish within the configured timeout."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Hermes summary CLI call timed out after {timeout_seconds} seconds"
        )


class HermesSummaryProcessError(HermesSummaryError):
    """Raised when the Hermes CLI subprocess exits with a non-zero status."""

    def __init__(self, return_code: int | None, stderr: str) -> None:
        self.return_code = return_code
        # Cap the amount of subprocess stderr we surface -- it's diagnostic
        # output, not a place to dump arbitrary/large content.
        self.stderr = stderr[:2000]
        super().__init__(
            f"Hermes summary CLI exited with code {return_code}: {self.stderr}"
        )


class HermesSummaryService:
    """Shared service for generating interpretation summaries via the Hermes Agent CLI."""

    def __init__(
        self,
        command: str,
        timeout_seconds: int | float,
        model: str | None = None,
        workdir: str | None = None,
        language: str | None = None,
    ) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.model = model
        self.workdir = workdir
        self.language = language

    def _build_argv(self) -> list[str]:
        """Split the configured command into argv, optionally adding a model flag.

        The command is executed directly (no shell), so arbitrary content passed
        on stdin later can never be shell-injected via the command itself.
        """
        argv = shlex.split(self.command)
        if self.model:
            argv.extend(["--model", self.model])
        return argv

    def _build_prompt(
        self,
        *,
        file_name: str,
        transcript: str,
        page_count: int,
        existing_context_hint: str | None,
    ) -> str:
        """Build the prompt sent to Hermes via stdin.

        Only OCR text and metadata are included -- notebook images are never
        sent, and any memory/session history Hermes has access to is explicitly
        scoped to vocabulary/OCR-mistake interpretation, not as a source of new
        facts.
        """
        if self.language:
            language_instruction = (
                f"Respond in {self.language}, regardless of the transcript's language."
            )
        else:
            language_instruction = (
                "Respond in the same language as the OCR transcript below "
                "(infer the language from the transcript)."
            )

        context_section = (
            existing_context_hint.strip()
            if existing_context_hint and existing_context_hint.strip()
            else "(none provided)"
        )

        return f"""You are producing an interpretation summary of a handwritten notebook page that has been run through OCR.

File name: {file_name}
Page count: {page_count}

Instructions:
- {language_instruction}
- Produce Markdown only. Do not wrap the response in a code fence.
- Use the OCR transcript below as the primary evidence for everything you write.
- You may use your memory/session history only to help interpret vocabulary and
  likely OCR mistakes (e.g. recognizing a misread word from prior context) --
  never as a source of new facts that aren't supported by the OCR transcript or
  the durable context hint below.
- Mark uncertain readings explicitly (for example, by wrapping them in
  brackets or noting "(uncertain)" next to them) wherever the OCR text is
  ambiguous, garbled, or could plausibly be a misrecognition.
- Do not invent facts that are not supported by the OCR transcript or the
  durable context hint below.
- Preserve open questions raised in the notebook page rather than resolving
  them with invented answers.
- End your response with a short uncertainty-disclosure note making clear that
  this is an interpretation derived from the OCR text and context, and that
  uncertain parts are marked separately.

Durable context hint (for interpreting vocabulary/likely OCR mistakes only,
not a source of new facts):
{context_section}

OCR transcript (primary evidence):
---
{transcript}
---
"""

    async def generate_interpretation(
        self,
        *,
        file_id: int,
        file_name: str,
        transcript: str,
        page_count: int,
        existing_context_hint: str | None = None,
    ) -> str:
        """Generate a Markdown interpretation summary for an OCR transcript.

        Shells out to the configured Hermes Agent CLI command, passing the
        prompt via stdin (never interpolated into a shell string). Raises
        :class:`HermesSummaryTimeoutError` if the call doesn't finish within
        `timeout_seconds`, and :class:`HermesSummaryProcessError` if the CLI
        exits with a non-zero status.
        """
        prompt = self._build_prompt(
            file_name=file_name,
            transcript=transcript,
            page_count=page_count,
            existing_context_hint=existing_context_hint,
        )
        argv = self._build_argv()

        logger.info(
            "Requesting Hermes interpretation summary for file_id=%s (%d pages)",
            file_id,
            page_count,
        )

        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.workdir,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8")),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            logger.warning(
                "Hermes summary CLI call for file_id=%s timed out after %s seconds",
                file_id,
                self.timeout_seconds,
            )
            raise HermesSummaryTimeoutError(self.timeout_seconds) from exc

        if process.returncode != 0:
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            logger.error(
                "Hermes summary CLI call for file_id=%s failed with code %s",
                file_id,
                process.returncode,
            )
            raise HermesSummaryProcessError(process.returncode, stderr_text)

        response = stdout_bytes.decode("utf-8", errors="replace").strip()
        return self._ensure_uncertainty_footer(response)

    def _ensure_uncertainty_footer(self, response: str) -> str:
        """Append the uncertainty-disclosure footer if the response doesn't have one."""
        if _UNCERTAINTY_FOOTER_MARKER in response.lower():
            return response
        return (
            f"{response}\n\n---\n{DEFAULT_UNCERTAINTY_FOOTER}"
            if response
            else DEFAULT_UNCERTAINTY_FOOTER
        )
