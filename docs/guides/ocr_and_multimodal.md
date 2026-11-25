# Handwriting OCR & Multimodal Workflows

On-device handwriting recognition drains battery and often misses dense cursive, Bullet Journal symbols, tables, and hand-drawn diagrams. If you configure an optional Vision AI provider, Open Private Cloud runs a background pipeline that turns your synced `.note` notebooks and standalone images into searchable Markdown, rendered diagrams, summaries, and visual context for AI assistants.

Nothing in this pipeline is required. Unchanged and blank pages are skipped automatically, and if you leave AI unconfigured, your server still syncs files and renders notebook pages with no AI overhead.

<p align="center">
  <img src="../static-assets/web-notebook-viewer.png" alt="Handwritten Notebook Viewer side-by-side with AI Markdown OCR Transcript" width="840">
</p>

## Handwriting, Bullet Journals, and diagrams

When a `.note` file syncs, modified pages are transcribed into Markdown and shown side-by-side with your handwriting in the Web UI.

The default OCR prompt preserves Bullet Journal Rapid Logging symbols (`•`, `X`, `>`, `<`, `o`, `-`, `*`), nested indentation, and `~~strikethroughs~~`. It also handles tables and hand-drawn diagrams: tabular notes become GitHub-Flavored Markdown tables, and flowcharts or architecture sketches are transcribed as fenced ` ```mermaid ` blocks.

In the Web UI, those Mermaid blocks render directly as diagrams inside the transcript panel, with a toggle to view the raw source.

## Standalone images (screenshots, whiteboards, and photos)

You can also sync `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, and `.bmp` files into your cloud folders. The pipeline transcribes visible text, tables, and whiteboard diagrams (including Mermaid blocks), and writes a short scene description for photos and illustrations so they show up in natural-language search.

Opening a standalone image in the Web UI shows its OCR text and scene description in a side panel.

Image indexing is on by default whenever an OCR provider is configured, and it automatically skips Supernote system folders (`MyStyle/**` and `EXPORT/**`). You can change the folder filters or turn it off in `config/config.yaml`:

```yaml
enable_image_processing: true
image_include_patterns: []                    # Empty = index all non-excluded folders
image_exclude_patterns: ["MyStyle/**", "EXPORT/**"]
```

## Reading digests and handwritten annotations

Reading digests and handwritten margin notes synced from your tablet appear in the **Digests** tab. If you need a shareable or archival copy of a handwritten digest, the extended API can render and cache it as a PDF or PNG (`SummaryClient.summary_to_pdf` and `SummaryClient.summary_to_png`).

<p align="center">
  <img src="../static-assets/web-digests.png" alt="Digests and Annotations browser with categories, tags, and source links" width="840">
</p>

## Letting AI assistants see your pages (`get_page_image`)

Transcripts work well for text search, but sometimes an assistant needs to look at the actual drawing, floor plan, or whiteboard photo. When MCP is enabled, vision-capable clients like Claude Desktop and Cursor can call `get_page_image(file_id, page_index)` to fetch a normalized PNG of any notebook page or standalone image.

## Customizing prompts by filename or stationery

You can customize OCR or summary instructions for specific notebooks by dropping Markdown files into `prompts_dir` (`config/prompts` by default):

```text
config/prompts/
├── ocr/
│   ├── common/                    # Always prepended to every OCR prompt
│   ├── default/                   # Fallback when no filename or page-style folder matches
│   ├── daily/prompt.md            # Matches Daily.note, daily_log.note, etc.
│   └── cornell/prompt.md          # Matches pages using Cornell stationery (style_cornell)
├── summary/
│   ├── common/                    # Always prepended to every summary prompt
│   └── meeting_notes/prompt.md    # Custom summary format for meeting notebooks
└── image/
    └── default/prompt.md          # Custom prompt for standalone images
```

For each page, OCR prompts resolve in order: notebook filename stem (`Daily.note` -> `daily`), then normalized page stationery style (stripping `user_`/`style_` prefixes and device suffixes like `_a5x2`), and finally `default/`. Native Supernote page keywords (`PAGE_KEYWORDS`) are injected automatically so your custom prompts can use your device tags and headings.

> [!NOTE]
> When customizing `summary/` prompts, keep your instructions compatible with the structured JSON output schema (`segments` containing `date_range`, `summary`, `extracted_dates`, and `page_refs`).

## Picking a vision model

See [Choosing an AI Provider](./ai_providers.md) for the full OCR and search benchmarks, local Ollama/vLLM examples, and API data-retention policies. For full provider settings, see the [Configuration Reference](../reference/configuration.md); for agent setup, see the [MCP Guide](./mcp.md); and for internal queue details, see the [Async Note Processing Pipeline](../architecture/note_processing_design.md).
