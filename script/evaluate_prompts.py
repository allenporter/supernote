#!/usr/bin/env python3
"""Evaluate Gemini OCR and Summary prompts on a Supernote notebook."""

import argparse
import asyncio
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path so we can import supernote
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.genai import types
from mashumaro.jsonschema import build_json_schema

from supernote.notebook import Notebook, PngConverter, load_notebook
from supernote.server.config import ServerConfig
from supernote.server.services.gemini import GeminiService
from supernote.server.services.processor_modules.summary import SummaryResponse
from supernote.server.utils.note_content import format_page_metadata
from supernote.server.utils.prompt_loader import PromptId, PromptLoader


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Gemini OCR and Summary prompts on a Supernote notebook."
    )
    parser.add_argument(
        "--notebook", type=str, required=True, help="Path to the .note file."
    )
    parser.add_argument(
        "--prompt-dir",
        type=str,
        default=None,
        help="Custom prompts directory to load templates from.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="storage/eval_results",
        help="Directory to save evaluation results.",
    )
    parser.add_argument(
        "--run-name",
        type=str,
        default=None,
        help="Name for this run (defaults to timestamp).",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Gemini API Key (overrides env SUPERNOTE_GEMINI_API_KEY).",
    )
    parser.add_argument(
        "--ocr-model", type=str, default=None, help="OCR model override."
    )
    parser.add_argument(
        "--summary-model", type=str, default=None, help="Summary model override."
    )
    parser.add_argument(
        "--custom-type",
        type=str,
        default=None,
        help="Custom prompt type (e.g. daily, weekly, monthly). Defaults to notebook file name stem.",
    )
    parser.add_argument(
        "--pages",
        type=str,
        default="all",
        help="Pages to process: 'all', single index (e.g. '0'), comma-separated (e.g. '0,1,2'), range (e.g. '40-42'), or negative (e.g. '-5' for last 5 pages). 0-indexed.",
    )
    return parser.parse_args()


async def run_ocr_for_page(
    gemini_service: GeminiService,
    model: str,
    page_idx: int,
    notebook: Notebook,
    notebook_path: Path,
    ocr_prompt_template: str,
    out_dir: Path,
) -> tuple[str, str]:
    """Runs OCR on a single page, saves the extracted PNG and individual txt transcript."""
    page = notebook.get_page(page_idx)
    page_id = page.get_pageid() or f"page_{page_idx}"

    # Convert page to PNG bytes
    converter = PngConverter(notebook)
    img = converter.convert(page_idx)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_data = buf.getvalue()

    # Save page image
    png_filename = f"page_{page_idx + 1:02d}_{page_id}.png"
    png_out_path = out_dir / png_filename
    png_out_path.write_bytes(png_data)

    # Format metadata block
    metadata_block = format_page_metadata(
        page_index=page_idx,
        page_id=page_id,
        file_name=notebook_path.name,
        notebook_create_time=None,  # No DB record for local notebook file
        include_section_divider=True,
    )

    full_ocr_prompt = f"{metadata_block}\n\n{ocr_prompt_template}"

    print(f"Running OCR on Page {page_idx + 1} (ID: {page_id})...")

    parts = [
        types.Part.from_text(text=full_ocr_prompt),
        types.Part.from_bytes(data=png_data, mime_type="image/png"),
    ]

    response = await gemini_service.generate_content(
        model=model,
        contents=[types.Content(parts=parts)],
        config={"media_resolution": types.MediaResolution.MEDIA_RESOLUTION_HIGH},
    )

    text_content = response.text if response.text else ""
    formatted_page_transcript = f"{metadata_block}\n{text_content}"

    # Save individual page transcript
    txt_filename = f"page_{page_idx + 1:02d}_{page_id}_ocr.txt"
    (out_dir / txt_filename).write_text(text_content, encoding="utf-8")

    relative_img_path = str(png_out_path.relative_to(out_dir.parent.parent))
    return formatted_page_transcript, relative_img_path


async def run_ocr_pipeline(
    gemini_service: GeminiService,
    model: str,
    notebook: Notebook,
    notebook_path: Path,
    prompt_loader: PromptLoader,
    custom_type: str,
    out_dir: Path,
    page_indices: list[int],
) -> tuple[str, list[str], str]:
    """Extracts specified pages, runs OCR, and saves the aggregated transcript."""
    # Get OCR prompts
    try:
        ocr_prompt_template = prompt_loader.get_prompt(
            PromptId.OCR_TRANSCRIPTION, custom_type=custom_type
        )
    except Exception as e:
        print(f"Warning: failed to load OCR prompt for '{custom_type}': {e}")
        ocr_prompt_template = prompt_loader.get_prompt(
            PromptId.OCR_TRANSCRIPTION, custom_type=None
        )

    ocr_transcripts = []
    page_files = []

    for page_idx in page_indices:
        page_transcript, rel_img_path = await run_ocr_for_page(
            gemini_service=gemini_service,
            model=model,
            page_idx=page_idx,
            notebook=notebook,
            notebook_path=notebook_path,
            ocr_prompt_template=ocr_prompt_template,
            out_dir=out_dir,
        )
        ocr_transcripts.append(page_transcript)
        page_files.append(rel_img_path)

    full_transcript = "\n\n".join(ocr_transcripts)
    (out_dir / "ocr_transcript.txt").write_text(full_transcript, encoding="utf-8")
    print("Completed OCR for all pages. Full transcript saved.")

    return full_transcript, page_files, ocr_prompt_template


async def run_summary_pipeline(
    gemini_service: GeminiService,
    model: str,
    full_transcript: str,
    prompt_loader: PromptLoader,
    custom_type: str,
    out_dir: Path,
) -> tuple[str, str]:
    """Runs summarization on the transcript, saves raw JSON and formatted Markdown."""
    try:
        summary_prompt_template = prompt_loader.get_prompt(
            PromptId.SUMMARY_GENERATION, custom_type=custom_type
        )
    except Exception as e:
        print(f"Warning: failed to load Summary prompt for '{custom_type}': {e}")
        summary_prompt_template = prompt_loader.get_prompt(
            PromptId.SUMMARY_GENERATION, custom_type=None
        )

    full_summary_prompt = f"{summary_prompt_template}\n\nTRANSCRIPT:\n{full_transcript}"

    print("Running Summary Generation...")
    schema = build_json_schema(SummaryResponse).to_dict()

    summary_response = await gemini_service.generate_content(
        model=model,
        contents=full_summary_prompt,
        config={
            "response_mime_type": "application/json",
            "response_json_schema": schema,
        },
    )

    summary_text = summary_response.text if summary_response.text else "{}"
    (out_dir / "summary_raw.json").write_text(summary_text, encoding="utf-8")

    # Format summary markdown
    ai_summary_md = "No summary generated."
    try:
        data = json.loads(summary_text)
        segments_data = data.get("segments", [])

        summary_parts = []
        for seg in segments_data:
            date_range = seg.get("date_range", "Unknown Date")
            text = seg.get("summary", "")
            page_refs = seg.get("page_refs", [])

            header = f"## {date_range}"
            if page_refs:
                pages_str = ", ".join(str(p) for p in page_refs)
                header += f" (Pages {pages_str})"

            summary_parts.append(f"{header}\n{text}")

        if summary_parts:
            ai_summary_md = "\n\n".join(summary_parts)
    except Exception as e:
        print(f"Error parsing summary JSON: {e}")
        ai_summary_md = f"Failed to parse JSON. Raw response:\n\n{summary_text}"

    (out_dir / "summary.md").write_text(ai_summary_md, encoding="utf-8")
    print("Completed Summary generation. Summary markdown saved.")

    return ai_summary_md, summary_prompt_template


def save_meta_info(
    out_dir: Path,
    notebook_path: Path,
    custom_type: str,
    ocr_model: str,
    summary_model: str,
    ocr_prompt: str,
    summary_prompt: str,
    page_files: list[str],
) -> None:
    """Saves run metadata for reproducibility."""
    meta_info = {
        "timestamp": datetime.now().isoformat(),
        "notebook": str(notebook_path),
        "custom_type": custom_type,
        "ocr_model": ocr_model,
        "summary_model": summary_model,
        "ocr_prompt": ocr_prompt,
        "summary_prompt": summary_prompt,
        "pages_extracted": page_files,
    }
    with open(out_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta_info, f, indent=2)


async def main_async() -> None:
    args = parse_args()

    # Initialize configuration
    config = ServerConfig.load()

    # Determine api key
    api_key = (
        args.api_key or os.getenv("SUPERNOTE_GEMINI_API_KEY") or config.gemini_api_key
    )
    if not api_key:
        print(
            "Error: Gemini API Key is required. Please set SUPERNOTE_GEMINI_API_KEY, use --api-key, or configure gemini_api_key in config/config.yaml.",
            file=sys.stderr,
        )
        sys.exit(1)

    ocr_model = args.ocr_model or config.gemini_ocr_model
    summary_model = args.summary_model or ocr_model

    print(f"OCR Model: {ocr_model}")
    print(f"Summary Model: {summary_model}")

    # Initialize Gemini service
    gemini_service = GeminiService(api_key=api_key)

    # Set up prompt loader
    if args.prompt_dir:
        prompt_dir_path = Path(args.prompt_dir).resolve()
        print(f"Loading custom prompts from: {prompt_dir_path}")
        prompt_loader = PromptLoader(resources_dir=prompt_dir_path)
    else:
        print("Loading default prompts from package resources.")
        prompt_loader = PromptLoader()

    # Load notebook
    notebook_path = Path(args.notebook)
    if not notebook_path.exists():
        print(
            f"Error: Notebook file not found at {notebook_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Loading notebook: {notebook_path}")
    notebook = load_notebook(str(notebook_path))
    total_pages = notebook.get_total_pages()
    print(f"Total pages in notebook: {total_pages}")

    # Parse pages argument
    page_indices = []
    if args.pages == "all":
        page_indices = list(range(total_pages))
    elif args.pages.startswith("-"):
        try:
            num = int(args.pages)
            start = max(0, total_pages + num)
            page_indices = list(range(start, total_pages))
        except ValueError:
            print(f"Error: Invalid pages format '{args.pages}'", file=sys.stderr)
            sys.exit(1)
    elif "-" in args.pages:
        try:
            parts = args.pages.split("-")
            start = int(parts[0])
            end = int(parts[1])  # inclusive
            page_indices = list(range(start, min(total_pages, end + 1)))
        except ValueError:
            print(f"Error: Invalid pages format '{args.pages}'", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            page_indices = [int(p.strip()) for p in args.pages.split(",") if p.strip()]
        except ValueError:
            print(f"Error: Invalid pages format '{args.pages}'", file=sys.stderr)
            sys.exit(1)

    print(f"Selected page indices for evaluation: {page_indices}")

    # Determine run name and output directory
    run_name = args.run_name or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) / run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Saving outputs to {out_dir}")

    # Determine custom type
    custom_type = args.custom_type or notebook_path.stem.lower()
    print(f"Using custom prompt type (stem): '{custom_type}'")

    # Run OCR pipeline
    full_transcript, page_files, ocr_prompt = await run_ocr_pipeline(
        gemini_service=gemini_service,
        model=ocr_model,
        notebook=notebook,
        notebook_path=notebook_path,
        prompt_loader=prompt_loader,
        custom_type=custom_type,
        out_dir=out_dir,
        page_indices=page_indices,
    )

    # Run Summary pipeline
    _, summary_prompt = await run_summary_pipeline(
        gemini_service=gemini_service,
        model=summary_model,
        full_transcript=full_transcript,
        prompt_loader=prompt_loader,
        custom_type=custom_type,
        out_dir=out_dir,
    )

    # Save meta information
    save_meta_info(
        out_dir=out_dir,
        notebook_path=notebook_path,
        custom_type=custom_type,
        ocr_model=ocr_model,
        summary_model=summary_model,
        ocr_prompt=ocr_prompt,
        summary_prompt=summary_prompt,
        page_files=page_files,
    )

    print(f"\nEvaluation finished successfully. Results saved in: {out_dir}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
