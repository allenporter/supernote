# Release Notes Authoring Guide

Release notes are written for **Supernote owners, self-hosters, and integrators**—not contributors reading git history.

Follow the voice and accuracy standards in `.agent/rules/documentation-style.md` (friendly human voice, active tense, no SaaS buzzwords or AI writing tells, grounded in verified code).

---

## Core Principles

1. **Lead with user outcomes, not PR mechanics**
   - Describe what a user or operator can now do, not how internal classes were refactored.
   - Omit internal refactors, test-suite reorganizations, CI tweaks, and routine dependency bumps unless they fix a user-visible bug or change runtime behavior.

2. **Pass the 30-second scan test**
   - Open with a short 2–3 sentence overview summarizing the theme of the release.
   - Group changes by user-facing capability (e.g., *LLM Wiki*, *Search & OCR*, *Web UI*, *Authentication & OAuth*, *Configuration & Operations*, *MCP & Integrations*, *Bug Fixes*). Only include sections that have real entries.
   - Prefer short paragraphs, `###` subheadings, or plain bullets over walls of `- **Catchy Label**: ...` bullets.

3. **Be explicit about opt-in vs. default**
   - Clearly distinguish capabilities that work out of the box (including zero-AI setups) from opt-in features.
   - Link to the relevant guide in `docs/guides/` or `docs/reference/` on GitHub instead of pasting full YAML schemas into release notes.

4. **Always include "Breaking Changes & Upgrade Notes"**
   - Even when there are none, state **"No breaking changes."** explicitly.
   - List every automatic Alembic migration by revision ID and briefly explain what it adds or transforms (and whether existing data/sessions stay intact).
   - Call out any renamed/deprecated config keys, changed webhook event names or payloads, or manual steps operators should take.

5. **100% verified against `origin/main`**
   - Verify every CLI flag, YAML key, environment variable, URL hash (`#/wiki`, `#/digests`, etc.), MCP tool name, and Alembic revision ID against the actual code at release time.

6. **Credit & traceability**
   - Credit external contributors (`by @username`).
   - Reference PR numbers (`#123`) for notable features and fixes.
   - End with the GitHub compare link:
     `**Full Changelog**: https://github.com/allenporter/supernote/compare/<prev-tag>...<new-tag>`

---

## Recommended Template

```markdown
<2–3 sentence summary of what this release brings for Supernote owners and self-hosters.>

## Highlights

### <User-Facing Area 1>
- Short, concrete description of the capability and how to access or enable it (#PR).

### <User-Facing Area 2>
- ...

### Bug Fixes
- Concrete fix description (#PR).

## Breaking Changes & Upgrade Notes

- **No breaking changes.** *(or list breaking changes clearly with migration steps)*
- Automatic database migrations run on startup:
  - `<rev_id>`: brief summary of schema change and impact on existing data.
- *(Optional)* Any config, webhook event, or operational notes for upgrading from `<prev-tag>`.

**Full Changelog**: https://github.com/allenporter/supernote/compare/<prev-tag>...<new-tag>
```
