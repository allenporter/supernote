#!/usr/bin/env python3
"""Search retrieval evaluation CLI comparing random, keyword, vector, and hybrid modes."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evals.search import (  # noqa: E402
    ALL_MODES,
    DEFAULT_CUTOFFS,
    CachingEmbeddingModel,
    RetrievalMode,
    SearchEvalDataset,
    SearchEvalSuiteReport,
    evaluate_search_dataset,
    format_markdown_report,
    merge_suite_reports,
    rescore_suite_report,
)
from supernote.server.ai.models.embedding import EmbeddingModel  # noqa: E402
from supernote.server.components.ai import AiRegistrar  # noqa: E402
from supernote.server.components.ai.config import AiComponentConfig  # noqa: E402
from supernote.server.components.fake_ai.embedding import (  # noqa: E402
    FakeEmbeddingModel,
)
from supernote.server.components.gemini.backend import (  # noqa: E402
    create_gemini_backend,
)
from supernote.server.components.gemini.embedding import (  # noqa: E402
    GeminiEmbeddingModel,
)
from supernote.server.components.openai.backend import (  # noqa: E402
    create_openai_backend,
)
from supernote.server.components.openai.embedding import (  # noqa: E402
    OpenAIEmbeddingModel,
)
from supernote.server.config import (  # noqa: E402
    ModelConfig,
    ProviderConfig,
    ServerConfig,
)

DEFAULT_DATASET = REPO_ROOT / "evals/search/dataset.yaml"
DEFAULT_CACHE_DIR = REPO_ROOT / "storage/eval_search_cache"
DEFAULT_TARGET = "gemini:gemini-embedding-2"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark Supernote search retrieval modes (random, keyword_only, "
            "embedding_unfloored, embedding_floored, hybrid) against a declarative dataset."
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
        default=None,
        metavar="PROVIDER:MODEL",
        help=(
            f"Embedding target '<provider>:<model>' (default: {DEFAULT_TARGET!r}, "
            "or 'fake:blended' for offline smoke runs)."
        ),
    )
    parser.add_argument(
        "--gemini-api-key",
        type=str,
        default=os.getenv("SUPERNOTE_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY"),
        help="Gemini API key (defaults to SUPERNOTE_GEMINI_API_KEY or GEMINI_API_KEY).",
    )
    parser.add_argument(
        "--openai-base-url",
        type=str,
        default=os.getenv("OPENAI_BASE_URL"),
        help="Optional base_url for the 'openai' provider (e.g. http://localhost:11434/v1).",
    )
    parser.add_argument(
        "--openai-api-key",
        type=str,
        default=os.getenv("SUPERNOTE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY"),
        help="OpenAI API key (defaults to SUPERNOTE_OPENAI_API_KEY or OPENAI_API_KEY).",
    )
    parser.add_argument(
        "--ollama-base-url",
        type=str,
        default=os.getenv("OLLAMA_BASE_URL"),
        help="Optional OpenAI-compatible base_url for the 'ollama' provider (e.g. http://localhost:11434/v1).",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=5,
        help="Max concurrent embedding API calls (default: 5).",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=(
            "Directory for content-addressed embedding vector caches "
            f"(default: {DEFAULT_CACHE_DIR.relative_to(REPO_ROOT)})."
        ),
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable reading/writing the local disk embedding cache.",
    )
    parser.add_argument(
        "--mode",
        action="append",
        choices=list(ALL_MODES),
        default=[],
        help="Run only specific retrieval mode(s) (repeatable; defaults to all 5 modes).",
    )
    parser.add_argument(
        "--cutoff",
        action="append",
        type=int,
        default=[],
        help="Rank cutoff(s) top_n to evaluate (repeatable; defaults to 5 and 10).",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Include only queries in this category (repeatable).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for the `random` baseline mode (default: 42).",
    )
    parser.add_argument(
        "--from-json",
        nargs="+",
        action="extend",
        type=Path,
        default=[],
        metavar="JSON_PATH",
        help="Load and merge one or more saved JSON suite reports instead of running live embeddings.",
    )
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="Recompute metrics on `--from-json` against `--dataset` ground truth.",
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
        help="Optional file path to write the full JSON suite report.",
    )
    return parser.parse_args(argv)


def _build_embedding_model(args: argparse.Namespace) -> EmbeddingModel:
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
    if args.ollama_base_url or "ollama" not in providers:
        existing_ollama = providers.get("ollama", ProviderConfig(type="openai"))
        providers["ollama"] = dataclasses.replace(
            existing_ollama,
            base_url=args.ollama_base_url
            or existing_ollama.base_url
            or "http://localhost:11434/v1",
            api_key=existing_ollama.api_key or "ollama",
            type=existing_ollama.type or "openai",
        )

    spec = args.target
    if not spec:
        if config.ai.embedding is not None:
            spec = f"{config.ai.embedding.provider}:{config.ai.embedding.model}"
        else:
            spec = DEFAULT_TARGET

    if ":" not in spec:
        raise ValueError(
            f"Invalid --target {spec!r}; expected '<provider>:<model>' "
            f"(e.g. {DEFAULT_TARGET!r} or 'fake:blended')."
        )
    provider_name, model_name = spec.split(":", 1)

    if provider_name == "fake" and model_name == "blended":
        inner: EmbeddingModel | None = FakeEmbeddingModel(
            dimensions=256, model_id="blended", blended=True
        )
    else:
        target_cfg = AiComponentConfig(
            providers=providers,
            embedding=ModelConfig(
                provider=provider_name,
                model=model_name,
                max_concurrency=args.max_concurrency,
            ),
        )
        registrar = AiRegistrar()
        registrar.register_embedding(
            "fake",
            lambda p, m: FakeEmbeddingModel(model_id=m, provider=p),
        )
        registrar.register_embedding(
            "gemini",
            lambda p, m: (
                GeminiEmbeddingModel(b, m)
                if (b := create_gemini_backend(providers, p)) is not None
                else None
            ),
        )
        registrar.register_embedding(
            "openai",
            lambda p, m: (
                OpenAIEmbeddingModel(b, m)
                if (b := create_openai_backend(providers, p)) is not None
                else None
            ),
        )
        inner = registrar.create_embedding_model(target_cfg)

    if inner is None:
        raise ValueError(
            f"Target {spec!r} could not be initialized (missing provider credentials; "
            "pass --gemini-api-key, --openai-api-key, --ollama-base-url, or --config)."
        )

    cache_path = (
        None
        if args.no_cache
        else CachingEmbeddingModel.default_cache_path(args.cache_dir, inner)
    )
    return CachingEmbeddingModel(
        inner,
        cache_path=cache_path,
        max_concurrency=args.max_concurrency,
    )


async def main_async(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    args = parse_args(argv)

    dataset = SearchEvalDataset.load(args.dataset.resolve())
    if args.category:
        allowed = set(args.category)
        queries = [q for q in dataset.queries if q.category in allowed]
        if not queries:
            raise ValueError("No evaluation queries matched --category.")
        dataset = SearchEvalDataset(
            name=dataset.name,
            notebooks=dataset.notebooks,
            queries=queries,
        )

    if args.from_json:
        prior = [
            SearchEvalSuiteReport.from_json(p.read_text(encoding="utf-8"))
            for p in args.from_json
        ]
        if args.rescore:
            prior = [rescore_suite_report(r, dataset) for r in prior]
        report = merge_suite_reports(prior)
    else:
        modes: list[RetrievalMode] = list(args.mode) if args.mode else list(ALL_MODES)
        cutoffs = list(args.cutoff) if args.cutoff else list(DEFAULT_CUTOFFS)
        needs_embedding = any(m not in ("random", "keyword_only") for m in modes)
        embedding_model = _build_embedding_model(args) if needs_embedding else None
        report = await evaluate_search_dataset(
            dataset,
            embedding_model,
            modes=modes,
            cutoffs=cutoffs,
            seed=args.seed,
        )
        if isinstance(embedding_model, CachingEmbeddingModel):
            logging.info(
                "Embeddings (%s:%s): %d API calls, %d cache hits",
                embedding_model.provider,
                embedding_model.model_id,
                embedding_model.api_calls,
                embedding_model.cache_hits,
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
