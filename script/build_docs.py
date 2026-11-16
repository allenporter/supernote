#!/usr/bin/env python3
"""Build or serve the multi-level pdoc documentation site for Supernote.

This script pushes pdoc beyond single-level Python module dumps by:
1. Synthesizing virtual `pdoc.doc.Module` objects (`supernote.guides.*`) from
   standalone Markdown guides in `docs/` and `supernote/server/ARCHITECTURE.md`
   without polluting the shipped Python package with dummy `.py` files.
2. Injecting a multi-level navigation structure (`nav_guide_sections`,
   `nav_api_packages`, `nav_page_titles`) into `pdoc.render.env.globals`.
3. Rewriting Markdown file links (`docs/foo.md`, `./README.md`, etc.) to their
   rendered pdoc HTML targets so links work identically on GitHub and in the
   generated documentation site.
"""

from __future__ import annotations

import argparse
import base64
import re
import shutil
import sys
import types
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any, cast

import pdoc.doc
import pdoc.extract
import pdoc.render
import pdoc.render_helpers
import pdoc.web
from jinja2.runtime import Context

ROOT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT_DIR / "docs" / "templates"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "docs"


@dataclass(frozen=True)
class GuideSpec:
    """Specification for a standalone Markdown guide rendered as a pdoc page."""

    slug: str
    title: str
    section: str
    path: Path

    @property
    def modulename(self) -> str:
        return f"supernote.guides.{self.slug}"


GUIDE_SPECS: list[GuideSpec] = [
    # Getting Started & Self-Hosting
    GuideSpec(
        slug="bootstrap_guide",
        title="Self-Hosting & Quickstart",
        section="Self-Hosting & Guides",
        path=ROOT_DIR / "docs" / "bootstrap_guide.md",
    ),
    GuideSpec(
        slug="configuration",
        title="Configuration Reference",
        section="Self-Hosting & Guides",
        path=ROOT_DIR / "docs" / "configuration.md",
    ),
    GuideSpec(
        slug="mcp",
        title="AI Pipeline, Prompts & MCP",
        section="Self-Hosting & Guides",
        path=ROOT_DIR / "docs" / "mcp.md",
    ),
    GuideSpec(
        slug="ocr_benchmarks",
        title="OCR Provider Benchmarks",
        section="Self-Hosting & Guides",
        path=ROOT_DIR / "evals" / "ocr" / "README.md",
    ),
    GuideSpec(
        slug="monitoring",
        title="Prometheus & Grafana Monitoring",
        section="Self-Hosting & Guides",
        path=ROOT_DIR / "docs" / "monitoring.md",
    ),
    GuideSpec(
        slug="webhooks_and_integrations",
        title="Webhooks, iCal & Integrations",
        section="Self-Hosting & Guides",
        path=ROOT_DIR / "docs" / "webhooks_and_integrations.md",
    ),
    GuideSpec(
        slug="cli_reference",
        title="CLI Reference",
        section="Self-Hosting & Guides",
        path=ROOT_DIR / "docs" / "cli_reference.md",
    ),
    # Architecture & Specifications
    GuideSpec(
        slug="architecture",
        title="Server & Sync Protocol",
        section="Architecture & Specs",
        path=ROOT_DIR / "supernote" / "server" / "ARCHITECTURE.md",
    ),
    GuideSpec(
        slug="note_processing_design",
        title="Async Note Processing Pipeline",
        section="Architecture & Specs",
        path=ROOT_DIR / "docs" / "note_processing_design.md",
    ),
    GuideSpec(
        slug="security",
        title="Security & Threat Model",
        section="Architecture & Specs",
        path=ROOT_DIR / "docs" / "security.md",
    ),
    GuideSpec(
        slug="notebook_spec",
        title="Binary .note Format Spec",
        section="Architecture & Specs",
        path=ROOT_DIR / "docs" / "notebook_spec.md",
    ),
    GuideSpec(
        slug="schedule_api",
        title="Schedule & Tasks API Spec",
        section="Architecture & Specs",
        path=ROOT_DIR / "docs" / "schedule_api.md",
    ),
    GuideSpec(
        slug="summary_api",
        title="Summary & OCR API Spec",
        section="Architecture & Specs",
        path=ROOT_DIR / "docs" / "summary_api.md",
    ),
    # Contributing & Maintenance
    GuideSpec(
        slug="roadmap",
        title="Roadmap & Priorities",
        section="Development",
        path=ROOT_DIR / "ROADMAP.md",
    ),
    GuideSpec(
        slug="contributing",
        title="Contributing & Local Dev",
        section="Development",
        path=ROOT_DIR / "docs" / "CONTRIBUTING.md",
    ),
    GuideSpec(
        slug="schema_migration_guide",
        title="Database Migrations (Alembic)",
        section="Development",
        path=ROOT_DIR / "docs" / "schema_migration_guide.md",
    ),
]

API_PACKAGES = [
    {
        "module": "supernote.server",
        "title": "Private Cloud Server",
        "short": "server",
    },
    {
        "module": "supernote.client",
        "title": "Async Cloud Client SDK",
        "short": "client",
    },
    {
        "module": "supernote.notebook",
        "title": "Notebook Parser & Converter",
        "short": "notebook",
    },
    {
        "module": "supernote.models",
        "title": "Protocol & API Data Models",
        "short": "models",
    },
    {
        "module": "supernote.cli",
        "title": "Command Line Interface",
        "short": "cli",
    },
]


class MarkdownGuideModule(pdoc.doc.Module):
    """A virtual pdoc.doc.Module backed directly by a Markdown file on disk."""

    def __init__(self, spec: GuideSpec) -> None:
        mod = types.ModuleType(spec.modulename)
        mod.__doc__ = spec.path.read_text(encoding="utf-8")
        super().__init__(mod)
        self._guide_spec = spec

    @cached_property
    def docstring(self) -> str:
        text = self._guide_spec.path.read_text(encoding="utf-8")
        if self._guide_spec.slug == "ocr_benchmarks":
            results_path = ROOT_DIR / "evals" / "ocr" / "RESULTS.md"
            if results_path.exists():
                results_body = results_path.read_text(encoding="utf-8")
                # Strip the top-level H1 from RESULTS.md before embedding into README.md
                results_body = re.sub(r"^#\s+[^\n]+\n+", "", results_body, count=1)
                target = (
                    "![OCR Quality vs. Latency Pareto Frontier](pareto_frontier.svg)"
                )
                if target in text:
                    text = text.replace(target, f"{target}\n\n{results_body.strip()}\n")
                else:
                    text = f"{text}\n\n{results_body}"
        return text.replace(r"$\rightarrow$", "→")

    @cached_property
    def source_file(self) -> Path | None:
        return self._guide_spec.path

    @cached_property
    def source(self) -> str:
        return ""

    @cached_property
    def members(self) -> dict[str, pdoc.doc.Doc]:
        return {}

    @cached_property
    def own_members(self) -> list[pdoc.doc.Doc]:
        return []

    @cached_property
    def submodules(self) -> list[pdoc.doc.Module]:
        return []


class GuideIndexModule(pdoc.doc.Module):
    """Virtual package index for `supernote.guides`."""

    def __init__(self, guide_modules: list[MarkdownGuideModule]) -> None:
        mod = types.ModuleType("supernote.guides")
        lines = [
            "# Guides & Technical Specifications\n",
            "Browse the user guides, deployment manuals, and protocol specifications below:\n",
        ]
        current_section = None
        for g in GUIDE_SPECS:
            if g.section != current_section:
                current_section = g.section
                lines.append(f"\n## {current_section}\n")
            lines.append(f"- **{g.title}**: `{g.modulename}`\n")
        mod.__doc__ = "".join(lines)
        super().__init__(mod)
        self._guide_modules = guide_modules

    @cached_property
    def is_package(self) -> bool:
        return True

    @cached_property
    def source(self) -> str:
        return ""

    @cached_property
    def members(self) -> dict[str, pdoc.doc.Doc]:
        return {}

    @cached_property
    def own_members(self) -> list[pdoc.doc.Doc]:
        return []

    @cached_property
    def submodules(self) -> list[pdoc.doc.Module]:
        return list(self._guide_modules)


def _clean_sidebar_toc(toc_html: str | None) -> str:
    """Unwrap redundant outer H1 bullet and strip H3/H4 nesting from sidebar TOC."""
    if not toc_html:
        return ""
    cleaned = toc_html.strip()
    # If the entire TOC is wrapped in a single top-level H1 <li><a>...</a><ul>...</ul></li>, unwrap it
    m = re.match(
        r"^\s*<ul>\s*<li>\s*<a\b[^>]*>.*?</a>\s*(<ul>.*</ul>)\s*</li>\s*</ul>\s*$",
        cleaned,
        flags=re.S,
    )
    if m:
        cleaned = m.group(1)
    # Remove nested <ul>...</ul> (H3/H4 levels) inside top-level <li> items
    inner = re.sub(r"^\s*<ul>\s*(.*?)\s*</ul>\s*$", r"\1", cleaned, flags=re.S)
    prev = None
    while prev != inner:
        prev = inner
        inner = re.sub(
            r"\s*<ul>\s*(?:<li>(?:(?!<ul\b).)*?</li>\s*)*</ul>",
            "",
            inner,
            flags=re.S,
        )
    if not re.search(r"<li\b", inner):
        return ""
    return f"<ul>\n{inner}\n</ul>"


def _install_markdown_link_rewriter() -> None:
    """Install a markdown pre-processor that rewrites relative .md links to pdoc HTML links."""
    # Map known markdown filenames to their target pdoc module names
    md_to_module: dict[str, str] = {
        "README.md": "supernote",
        "supernote/server/README.md": "supernote.server",
        "supernote/notebook/README.md": "supernote.notebook",
        "supernote/models/README.md": "supernote.models",
        "supernote/server/ARCHITECTURE.md": "supernote.guides.architecture",
        "docs/CONTRIBUTING.md": "supernote.guides.contributing",
        "evals/ocr/RESULTS.md": "supernote.guides.ocr_benchmarks",
        "evals/ocr/README.md": "supernote.guides.ocr_benchmarks",
        "RESULTS.md": "supernote.guides.ocr_benchmarks",
    }
    for spec in GUIDE_SPECS:
        rel = spec.path.relative_to(ROOT_DIR).as_posix()
        md_to_module[rel] = spec.modulename
        if spec.path.name != "README.md":
            md_to_module[spec.path.name] = spec.modulename

    def rewrite_links(context: Context, docstring: str) -> str:
        converted = pdoc.render_helpers.to_markdown_with_context(context, docstring)
        current_mod: pdoc.doc.Module | None = context.get("module")
        if current_mod is None:
            return converted

        def _replace_md_link(match: re.Match[str]) -> str:
            label = match.group("label")
            href = match.group("href")
            if href.startswith(("http://", "https://", "mailto:", "#", "data:")):
                return match.group(0)

            path_part, sep, fragment = href.partition("#")
            clean_path = path_part.strip()
            if not clean_path or clean_path.endswith(".html"):
                return match.group(0)

            # Resolve relative to source_file if possible
            target_mod: str | None = None
            resolved_rel: str | None = None
            base_dir = ROOT_DIR
            if current_mod.source_file is not None:
                if current_mod.modulename == "supernote":
                    base_dir = ROOT_DIR
                else:
                    base_dir = current_mod.source_file.parent

            try:
                resolved_path = (base_dir / clean_path).resolve()
                resolved = resolved_path.relative_to(ROOT_DIR).as_posix()
                if resolved_path.exists():
                    resolved_rel = resolved
                if resolved in md_to_module:
                    target_mod = md_to_module[resolved]
                elif resolved.startswith("supernote/") and resolved.endswith(".py"):
                    mod_path = resolved.removesuffix(".py").replace("/", ".")
                    if mod_path.endswith(".__init__"):
                        mod_path = mod_path.removesuffix(".__init__")
                    target_mod = mod_path
            except ValueError:
                pass

            if target_mod is None and (
                clean_path.endswith(".md") or ".py" in clean_path
            ):
                normalized = clean_path.lstrip("./")
                while normalized.startswith("../"):
                    normalized = normalized.removeprefix("../")
                target_mod = md_to_module.get(normalized) or md_to_module.get(
                    Path(normalized).name
                )

            if target_mod:
                rel_url = pdoc.render_helpers.relative_link(
                    current_mod.modulename, target_mod
                )
                if not rel_url:
                    rel_url = ""
                if sep and not clean_path.endswith(".py"):
                    return f"[{label}]({rel_url}#{fragment})"
                return f"[{label}]({rel_url})"

            if resolved_rel is not None:
                gh_url = (
                    f"https://github.com/allenporter/supernote/blob/main/{resolved_rel}"
                )
                if sep:
                    gh_url = f"{gh_url}#{fragment}"
                return f"[{label}]({gh_url})"

            return match.group(0)

        if current_mod.modulename == "supernote":
            converted = re.sub(
                r'(<img\s+[^>]*src=")(?P<src>(?:docs|evals)/[^"]+)(")',
                r"\g<1>../\g<src>\g<3>",
                converted,
            )

        return re.sub(
            r"\[(?P<label>[^\]]+)\]\((?P<href>[^)]+)\)",
            _replace_md_link,
            converted,
        )

    pdoc.render.env.filters["to_markdown"] = pdoc.render_helpers.pass_context(
        rewrite_links
    )

    orig_linkify = pdoc.render_helpers.linkify

    def short_linkify(
        context: Context, code: str, namespace: str = "", shorten: bool = True
    ) -> Any:
        # Protect <pre class="mermaid-pre">...</pre> blocks from linkify so pdoc
        # never injects <a href="..."> tags inside Mermaid diagram definitions.
        mermaid_blocks: list[str] = []

        def _stash_mermaid(m: re.Match[str]) -> str:
            idx = len(mermaid_blocks)
            mermaid_blocks.append(m.group(0).replace(r"\n", "<br/>"))
            return f"__MERMAID_BLOCK_{idx}__"

        protected = re.sub(
            r'<pre class="mermaid-pre">.*?</pre>',
            _stash_mermaid,
            code,
            flags=re.S,
        )
        result = str(
            orig_linkify(context, protected, namespace=namespace, shorten=shorten)
        )

        def _shorten_anchor(m: re.Match[str]) -> str:
            href = m.group("href")
            label = m.group("label")
            suffix = "()" if label.endswith("()") else ""
            raw = label.removesuffix("()")
            if not raw.startswith("supernote.") or raw.count(".") < 2:
                return m.group(0)
            if "#" in href:
                frag = href.split("#", 1)[1]
                short = frag + suffix if frag else raw.rsplit(".", 1)[-1] + suffix
            else:
                short = raw.rsplit(".", 1)[-1] + suffix
            return f'<a href="{href}" title="{label}">{short}</a>'

        shortened = re.sub(
            r'<a href="(?P<href>[^"]+)">(?P<label>supernote\.[A-Za-z0-9_.]+(?:\(\))?)</a>',
            _shorten_anchor,
            result,
        )
        for idx, block in enumerate(mermaid_blocks):
            shortened = shortened.replace(f"__MERMAID_BLOCK_{idx}__", block)
        return pdoc.render_helpers.Markup(shortened)

    pdoc.render.env.filters["linkify"] = pdoc.render_helpers.pass_context(short_linkify)


def get_child_modules(
    parent_name: str, all_modules: dict[str, pdoc.doc.Module]
) -> list[pdoc.doc.Module]:
    """Return all direct child modules of `parent_name` in `all_modules`."""
    prefix = parent_name + "."
    return [
        mod
        for name, mod in sorted(all_modules.items())
        if name.startswith(prefix)
        and "." not in name[len(prefix) :]
        and not name[len(prefix) :].startswith("_")
    ]


def configure_pdoc() -> None:
    """Configure pdoc templates, globals, and navigation metadata."""
    favicon_path = ROOT_DIR / "supernote" / "server" / "static" / "favicon.ico"
    if favicon_path.exists():
        favicon_b64 = base64.b64encode(favicon_path.read_bytes()).decode("ascii")
        favicon_uri = f"data:image/x-icon;base64,{favicon_b64}"
    else:
        favicon_uri = "https://raw.githubusercontent.com/allenporter/supernote/main/supernote/server/static/favicon.ico"

    pdoc.render.configure(
        docformat="google",
        include_undocumented=True,
        edit_url_map={
            "supernote": "https://github.com/allenporter/supernote/blob/main/supernote/",
        },
        favicon=favicon_uri,
        footer_text="Open Private Cloud for Supernote & Python SDK",
        math=False,
        mermaid=True,
        search=True,
        show_source=True,
        template_directory=TEMPLATE_DIR,
    )

    sections_order: list[str] = []
    sections_map: dict[str, list[dict[str, str]]] = {}
    page_titles: dict[str, str] = {
        "supernote": "Overview & Quick Start",
        "supernote.guides": "Guides & Specifications",
    }
    edit_urls: dict[str, str] = {
        "supernote": "https://github.com/allenporter/supernote/blob/main/README.md",
        "supernote.server": "https://github.com/allenporter/supernote/blob/main/supernote/server/README.md",
        "supernote.notebook": "https://github.com/allenporter/supernote/blob/main/supernote/notebook/README.md",
        "supernote.models": "https://github.com/allenporter/supernote/blob/main/supernote/models/README.md",
    }

    for spec in GUIDE_SPECS:
        if not spec.path.exists():
            continue
        if spec.section not in sections_map:
            sections_order.append(spec.section)
            sections_map[spec.section] = []
        sections_map[spec.section].append(
            {"module": spec.modulename, "title": spec.title}
        )
        page_titles[spec.modulename] = spec.title
        rel_path = spec.path.relative_to(ROOT_DIR).as_posix()
        edit_urls[spec.modulename] = (
            f"https://github.com/allenporter/supernote/blob/main/{rel_path}"
        )

    for pkg in API_PACKAGES:
        page_titles[pkg["module"]] = pkg["title"]

    nav_guide_sections = [
        {"title": sec, "items": sections_map[sec]} for sec in sections_order
    ]

    env_globals = cast(dict[str, Any], pdoc.render.env.globals)
    env_globals["docformat"] = "google,numpy"
    env_globals["nav_guide_sections"] = nav_guide_sections
    env_globals["nav_api_packages"] = API_PACKAGES
    env_globals["nav_page_titles"] = page_titles
    env_globals["nav_edit_urls"] = edit_urls
    env_globals["get_child_modules"] = get_child_modules
    pdoc.render.env.filters["clean_sidebar_toc"] = _clean_sidebar_toc

    _install_markdown_link_rewriter()


def load_all_modules() -> dict[str, pdoc.doc.Module]:
    """Load all Python modules in `supernote` plus virtual Markdown guide modules."""
    all_modules: dict[str, pdoc.doc.Module] = {}
    specs = [
        str(ROOT_DIR / "supernote"),
        *[
            f"supernote.notebook.{p.stem}"
            for p in sorted((ROOT_DIR / "supernote" / "notebook").glob("*.py"))
            if p.stem not in ("__init__", "exceptions", "schema")
        ],
        "supernote.client.api",
        "supernote.client.client",
        "!supernote.alembic",
        "!supernote.testing",
        "!supernote.notebook.resources",
    ]
    for mod_name in pdoc.extract.walk_specs(specs):
        all_modules[mod_name] = pdoc.doc.Module.from_name(mod_name)

    guide_modules: list[MarkdownGuideModule] = []
    for spec in GUIDE_SPECS:
        if spec.path.exists():
            gmod = MarkdownGuideModule(spec)
            guide_modules.append(gmod)

    if guide_modules:
        all_modules["supernote.guides"] = GuideIndexModule(guide_modules)
        for gmod in guide_modules:
            all_modules[gmod.modulename] = gmod

    for mod_name, mod in all_modules.items():
        if not mod_name.startswith("supernote.guides") and mod_name != "supernote":
            mod.__dict__["submodules"] = get_child_modules(mod_name, all_modules)

    return all_modules


def build_site(output_dir: Path) -> None:
    """Render the complete documentation site to `output_dir`."""
    configure_pdoc()
    all_modules = load_all_modules()

    output_dir.mkdir(parents=True, exist_ok=True)

    for module in all_modules.values():
        out = pdoc.render.html_module(module, all_modules)
        outfile = output_dir / f"{module.fullname.replace('.', '/')}.html"
        outfile.parent.mkdir(parents=True, exist_ok=True)
        outfile.write_bytes(out.encode("utf-8"))

    index = pdoc.render.html_index(all_modules)
    if index:
        (output_dir / "index.html").write_bytes(index.encode("utf-8"))

    search = pdoc.render.search_index(all_modules)
    if search:
        (output_dir / "search.js").write_bytes(search.encode("utf-8"))

    favicon_src = ROOT_DIR / "supernote" / "server" / "static" / "favicon.ico"
    if favicon_src.exists():
        shutil.copy2(favicon_src, output_dir / "favicon.ico")

    # If building to an external directory (e.g. site/), copy static assets if needed
    for asset_dir_name in ("static-assets", "images"):
        src_assets = ROOT_DIR / "docs" / asset_dir_name
        dst_assets = output_dir / asset_dir_name
        if src_assets.exists() and src_assets.resolve() != dst_assets.resolve():
            if dst_assets.exists():
                shutil.rmtree(dst_assets)
            shutil.copytree(src_assets, dst_assets)

    display_dir = (
        output_dir.relative_to(ROOT_DIR)
        if output_dir.is_relative_to(ROOT_DIR)
        else output_dir
    )
    print(f"Built {len(all_modules)} documentation pages in {display_dir}/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Supernote pdoc documentation.")
    parser.add_argument(
        "-o",
        "--output-directory",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for rendered HTML files (default: docs/)",
    )
    args = parser.parse_args()
    build_site(args.output_directory.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
