#!/usr/bin/env python3
"""Repeatable CLI for evaluating large-notebook summarization strategies."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evals.summary import (  # noqa: E402
    DeterministicFakeSummaryModel,
    format_markdown_report,
    load_summary_eval_dataset,
    run_summary_eval,
)
from supernote.server.ai.models.summary import SummaryModel  # noqa: E402
from supernote.server.components.gemini.backend import (  # noqa: E402
    create_gemini_backend,
)
from supernote.server.components.gemini.summary import (  # noqa: E402
    GeminiSummaryModel,
)
from supernote.server.components.openai.backend import (  # noqa: E402
    create_openai_backend,
)
from supernote.server.components.openai.summary import (  # noqa: E402
    OpenAISummaryModel,
)
from supernote.server.components.summary.config import SummaryConfig  # noqa: E402
from supernote.server.config import (  # noqa: E402
    ProviderConfig,
    ServerConfig,
)

DEFAULT_DATASET = REPO_ROOT / "evals/summary/dataset.yaml"
DEFAULT_TARGET = "gemini:gemini-3.5-flash-lite"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run repeatable large-notebook summarization evaluations against a "
            "declarative dataset and compare chunking strategies."
        )
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help=f"Path to dataset YAML manifest (default: {DEFAULT_DATASET.relative_to(REPO_ROOT)}).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional ServerConfig YAML providing `ai.providers` credentials.",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=DEFAULT_TARGET,
        metavar="PROVIDER:MODEL",
        help=(
            f"Summary target '<provider>:<model>' (default: {DEFAULT_TARGET!r}, "
            "or 'fake:deterministic' for offline smoke runs)."
        ),
    )
    parser.add_argument(
        "--notebook",
        action="append",
        default=None,
        help="Optional notebook filename filter (repeatable).",
    )
    parser.add_argument(
        "--gemini-api-key",
        type=str,
        default=os.getenv("SUPERNOTE_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY"),
        help="Gemini API key (defaults to SUPERNOTE_GEMINI_API_KEY or GEMINI_API_KEY).",
    )
    parser.add_argument(
        "--openai-api-key",
        type=str,
        default=os.getenv("SUPERNOTE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY"),
        help="OpenAI API key (defaults to SUPERNOTE_OPENAI_API_KEY or OPENAI_API_KEY).",
    )
    parser.add_argument(
        "--openai-base-url",
        type=str,
        default=os.getenv("OPENAI_BASE_URL"),
        help="Optional base_url for the 'openai' provider.",
    )
    parser.add_argument(
        "--ollama-base-url",
        type=str,
        default=os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434/v1",
        help="Base URL for the 'ollama' OpenAI-compatible provider.",
    )
    parser.add_argument(
        "--max-pages-per-chunk",
        type=int,
        default=8,
        help="SummaryConfig.max_pages_per_chunk (0 disables chunking / single-shot).",
    )
    parser.add_argument(
        "--max-chars-per-chunk",
        type=int,
        default=16_000,
        help="SummaryConfig.max_chars_per_chunk.",
    )
    parser.add_argument(
        "--no-incremental",
        action="store_true",
        help="Set SummaryConfig.incremental=False.",
    )
    parser.add_argument(
        "--no-carry-over",
        action="store_true",
        help="Set SummaryConfig.carry_over_context=False.",
    )
    parser.add_argument(
        "--skip-incremental-scenarios",
        action="store_true",
        help="Skip running append/mid-edit incremental update scenarios.",
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=None,
        help="Directory to write report.md, report.json, and rendered *.summary.md files.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable INFO logging.",
    )
    return parser.parse_args(argv)


def _resolve_model(args: argparse.Namespace) -> SummaryModel:
    provider, sep, model_name = args.target.partition(":")
    if not sep or not provider or not model_name:
        raise ValueError(
            f"Invalid --target {args.target!r}; expected '<provider>:<model>'."
        )

    if provider == "fake":
        return DeterministicFakeSummaryModel()

    providers: dict[str, ProviderConfig] = {}
    if args.config is not None:
        server_cfg = ServerConfig.load(args.config)
        providers = dict(server_cfg.ai.providers)

    if provider == "gemini":
        provider_cfg = providers.get(
            "gemini",
            ProviderConfig(type="gemini", api_key=args.gemini_api_key),
        )
        if args.gemini_api_key and not provider_cfg.api_key:
            provider_cfg = ProviderConfig(type="gemini", api_key=args.gemini_api_key)
        if not provider_cfg.api_key:
            raise ValueError(
                "Gemini API key required (--gemini-api-key or GEMINI_API_KEY)."
            )
        backend = create_gemini_backend({"gemini": provider_cfg}, "gemini")
        if backend is None:
            raise ValueError("Failed to initialize Gemini backend.")
        return GeminiSummaryModel(backend, model_name)

    if provider in ("openai", "ollama"):
        default_url = (
            args.ollama_base_url if provider == "ollama" else args.openai_base_url
        )
        default_key = "ollama" if provider == "ollama" else args.openai_api_key
        provider_cfg = providers.get(
            provider,
            ProviderConfig(type="openai", api_key=default_key, base_url=default_url),
        )
        backend = create_openai_backend({provider: provider_cfg}, provider)
        if backend is None:
            raise ValueError(f"Failed to initialize {provider} backend.")
        return OpenAISummaryModel(backend, model_name)

    raise ValueError(f"Unsupported provider {provider!r} in --target {args.target!r}.")


async def _async_main(args: argparse.Namespace) -> int:
    dataset = load_summary_eval_dataset(args.dataset)
    model = _resolve_model(args)
    summary_cfg = SummaryConfig(
        max_pages_per_chunk=args.max_pages_per_chunk,
        max_chars_per_chunk=args.max_chars_per_chunk,
        incremental=not args.no_incremental,
        carry_over_context=not args.no_carry_over,
    )
    report = await run_summary_eval(
        dataset,
        model,
        target_label=args.target,
        summary_config=summary_cfg,
        notebook_filter=set(args.notebook) if args.notebook else None,
        run_incremental=not args.skip_incremental_scenarios,
        export_dir=args.export_dir,
    )
    print(format_markdown_report(report))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
