#!/usr/bin/env python3
"""Repeatable CLI for evaluating LLM Wiki backfill quality on real or fake models."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evals.wiki import (  # noqa: E402
    DeterministicFakeWikiModel,
    format_markdown_report,
    load_wiki_eval_dataset,
    run_wiki_eval,
)
from supernote.server.ai.models.text import TextGenerationModel  # noqa: E402
from supernote.server.components.gemini.text import (  # noqa: E402
    create_text_model as create_gemini_text_model,
)
from supernote.server.components.openai.text import (  # noqa: E402
    create_text_model as create_openai_text_model,
)
from supernote.server.config import (  # noqa: E402
    AiConfig,
    ModelConfig,
    ProviderConfig,
    ServerConfig,
)

DEFAULT_DATASET = REPO_ROOT / "evals/wiki/dataset.yaml"
DEFAULT_TARGET = "gemini:gemini-2.5-flash"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run repeatable multi-batch LLM Wiki backfill evaluations against a "
            "declarative notebook/task dataset and inspect synthesized wiki quality."
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
            f"Text generation target '<provider>:<model>' (default: {DEFAULT_TARGET!r}, "
            "or 'fake:deterministic' for offline smoke runs)."
        ),
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
        "--max-files-per-batch",
        type=int,
        default=5,
        help="Notebooks processed per backfill batch (default: 5).",
    )
    parser.add_argument(
        "--max-pages-per-batch",
        type=int,
        default=5,
        help="Max wiki pages updated per compile turn (default: 5).",
    )
    parser.add_argument(
        "--run-lint",
        action="store_true",
        help="Also run LLM semantic lint after backfill completes.",
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=None,
        help="Directory to export compiled Markdown vault + report.md + report.json.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to write the JSON report.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def _build_text_model(args: argparse.Namespace) -> TextGenerationModel:
    if ":" not in args.target:
        raise SystemExit(
            f"Invalid --target {args.target!r}; expected '<provider>:<model>' "
            "(e.g. 'gemini:gemini-2.5-flash' or 'fake:deterministic')."
        )
    provider, model_name = args.target.split(":", maxsplit=1)
    provider = provider.strip().lower()
    model_name = model_name.strip()

    if provider in ("fake", "fake_ai"):
        return DeterministicFakeWikiModel()

    cfg = ServerConfig.load(str(args.config)) if args.config else ServerConfig()
    providers = dict(cfg.ai.providers)

    if provider == "gemini":
        if args.gemini_api_key:
            providers["gemini"] = ProviderConfig(
                type="gemini", api_key=args.gemini_api_key
            )
        cfg.ai = AiConfig(
            providers=providers,
            text=ModelConfig(provider="gemini", model=model_name),
        )
        model = create_gemini_text_model(cfg)
        if model is None:
            raise SystemExit(
                "Gemini text model could not be initialized. Set GEMINI_API_KEY "
                "(or pass --gemini-api-key / --config)."
            )
        return model

    if provider in ("openai", "ollama"):
        if provider == "ollama":
            providers["ollama"] = ProviderConfig(
                type="openai",
                api_key=args.openai_api_key or "ollama",
                base_url=args.ollama_base_url,
            )
        elif args.openai_api_key or args.openai_base_url:
            providers["openai"] = ProviderConfig(
                type="openai",
                api_key=args.openai_api_key,
                base_url=args.openai_base_url,
            )
        cfg.ai = AiConfig(
            providers=providers,
            text=ModelConfig(provider=provider, model=model_name),
        )
        model = create_openai_text_model(cfg)
        if model is None:
            raise SystemExit(
                f"{provider} text model could not be initialized. Check API key / base URL."
            )
        return model

    raise SystemExit(
        f"Unsupported provider {provider!r}; use 'fake', 'gemini', 'openai', or 'ollama'."
    )


async def _async_main(args: argparse.Namespace) -> int:
    dataset = load_wiki_eval_dataset(args.dataset)
    text_model = _build_text_model(args)
    report = await run_wiki_eval(
        dataset,
        text_model,
        target_label=args.target,
        max_files_per_batch=args.max_files_per_batch,
        max_pages_per_batch=args.max_pages_per_batch,
        run_semantic_lint=args.run_lint,
        export_dir=args.export_dir,
    )

    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(report.to_dict(), indent=2), encoding="utf-8"
        )

    print(format_markdown_report(report))
    if args.export_dir is not None:
        print(f"Exported compiled vault and reports to: {args.export_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
