#!/usr/bin/env python3
"""Provider-agnostic OCR benchmark CLI across `.note` and `.png` datasets."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from supernote.server.ai.eval import (  # noqa: E402
    OcrEvalDataset,
    OcrEvalTarget,
    evaluate_ocr_dataset,
    format_markdown_report,
)
from supernote.server.ai.models.ocr import create_ocr_model  # noqa: E402
from supernote.server.config import (  # noqa: E402
    AiConfig,
    ModelConfig,
    ProviderConfig,
    ServerConfig,
)

DEFAULT_DATASET = REPO_ROOT / "evals/ocr/dataset.yaml"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark OCR providers (apple, gemini, openai/Ollama, fake, etc.) "
            "against a declarative dataset manifest."
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
        help="Optional ServerConfig YAML providing `ai.providers` credentials/URLs.",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        metavar="PROVIDER:MODEL",
        help=(
            "Target spec '<provider>:<model>' (repeatable), e.g. "
            "'apple:vision-accurate', 'gemini:gemini-3.6-flash', or 'ollama:gemma3:27b'."
        ),
    )
    parser.add_argument(
        "--openai-base-url",
        type=str,
        default=os.getenv("OPENAI_BASE_URL"),
        help="Convenience base_url for the 'openai' provider (e.g. http://localhost:11434/v1).",
    )
    parser.add_argument(
        "--openai-api-key",
        type=str,
        default=os.getenv("OPENAI_API_KEY"),
        help="Convenience API key for the 'openai' provider (defaults to OPENAI_API_KEY).",
    )
    parser.add_argument(
        "--gemini-api-key",
        type=str,
        default=None,
        help="Convenience API key for the 'gemini' provider (defaults to SUPERNOTE_GEMINI_API_KEY).",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=2,
        help="Max concurrency per OCR model instance (default: 2).",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Include only cases in this category (repeatable).",
    )
    parser.add_argument(
        "--exclude-category",
        action="append",
        default=[],
        help="Exclude cases in this category (repeatable).",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Include only specific case IDs (repeatable).",
    )
    parser.add_argument(
        "--include-device-rtr",
        action="store_true",
        help="Also score embedded Supernote on-device RTR text on `.note` pages that have it.",
    )
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="Skip the single warmup call per target before timing.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Abort immediately if a provider raises AIError on any page.",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=None,
        help="Optional file path to write the Markdown summary report.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional file path to write full per-page JSON results and transcripts.",
    )
    return parser.parse_args(argv)


def _build_base_config(args: argparse.Namespace) -> ServerConfig:
    config = ServerConfig.load(args.config) if args.config else ServerConfig.load()
    providers = dict(config.ai.providers)

    if args.gemini_api_key:
        existing_gemini = providers.get("gemini", ProviderConfig())
        providers["gemini"] = dataclasses.replace(
            existing_gemini, api_key=args.gemini_api_key
        )

    if args.openai_base_url or args.openai_api_key:
        existing_openai = providers.get("openai", ProviderConfig())
        providers["openai"] = dataclasses.replace(
            existing_openai,
            base_url=args.openai_base_url or existing_openai.base_url,
            api_key=args.openai_api_key or existing_openai.api_key,
        )

    return dataclasses.replace(
        config, ai=dataclasses.replace(config.ai, providers=providers)
    )


def _resolve_targets(
    args: argparse.Namespace, base_config: ServerConfig
) -> list[OcrEvalTarget]:
    specs: list[str] = list(args.target)
    if not specs:
        if base_config.ai.ocr is not None:
            specs.append(f"{base_config.ai.ocr.provider}:{base_config.ai.ocr.model}")
        elif (
            sys.platform == "darwin" and importlib.util.find_spec("Vision") is not None
        ):
            specs.append("apple:vision-accurate")

    targets: list[OcrEvalTarget] = []
    for spec in specs:
        if ":" not in spec:
            raise ValueError(
                f"Invalid --target {spec!r}; expected '<provider>:<model>' "
                "(e.g. 'apple:vision-accurate' or 'openai:gemma3:27b')."
            )
        provider_name, model_name = spec.split(":", 1)
        target_cfg = dataclasses.replace(
            base_config,
            ai=AiConfig(
                providers=dict(base_config.ai.providers),
                ocr=ModelConfig(
                    provider=provider_name,
                    model=model_name,
                    max_concurrency=args.max_concurrency,
                ),
            ),
        )
        ocr_model = create_ocr_model(target_cfg)
        if ocr_model is None:
            raise ValueError(
                f"Target {spec!r} could not be initialized (missing provider credentials "
                "or base_url; pass --config, --gemini-api-key, or --openai-base-url)."
            )
        targets.append(OcrEvalTarget(name=spec, model=ocr_model))
    return targets


def _filter_dataset(
    dataset: OcrEvalDataset, args: argparse.Namespace
) -> OcrEvalDataset:
    cases = list(dataset.cases)
    if args.category:
        allowed_cats = set(args.category)
        cases = [c for c in cases if c.category in allowed_cats]
    if args.exclude_category:
        excluded_cats = set(args.exclude_category)
        cases = [c for c in cases if c.category not in excluded_cats]
    if args.case:
        allowed_ids = set(args.case)
        cases = [c for c in cases if c.id in allowed_ids]
    if not cases:
        raise ValueError("No evaluation cases matched the requested filters.")
    return OcrEvalDataset(name=dataset.name, cases=cases)


async def main_async(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = args.dataset.resolve()
    dataset = _filter_dataset(OcrEvalDataset.load(manifest_path), args)
    base_config = _build_base_config(args)
    targets = _resolve_targets(args, base_config)

    report = await evaluate_ocr_dataset(
        dataset=dataset,
        base_dir=manifest_path.parent,
        targets=targets,
        warmup=not args.no_warmup,
        include_device_rtr=args.include_device_rtr,
        fail_fast=args.fail_fast,
    )

    markdown = format_markdown_report(report)
    print(markdown)

    if args.markdown_out is not None:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown, encoding="utf-8")

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return 0


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
