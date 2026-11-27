/**
 * Pure Mermaid fence extraction and lazy, sanitized SVG rendering utilities.
 */

import DOMPurify from 'dompurify';

const MERMAID_FENCE_RE = /```mermaid[ \t]*\r?\n([\s\S]*?)\r?\n```/gi;

const SVG_SANITIZE_OPTIONS = {
    USE_PROFILES: { svg: true, svgFilters: true },
    FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'foreignObject'],
};

/** @typedef {{ type: 'text' | 'mermaid', content: string }} TranscriptSegment */
/** @typedef {{ ok: true, svg: string } | { ok: false, error: string }} MermaidRenderResult */
/** @typedef {() => Promise<import('mermaid').MermaidApi>} MermaidLoader */

/** @type {Promise<import('mermaid').MermaidApi> | null} */
let cachedMermaidPromise = null;
/** @type {WeakSet<object>} */
const initializedInstances = new WeakSet();
let renderCounter = 0;

/**
 * Split raw transcript text into ordered plain-text and fenced Mermaid segments.
 *
 * Plain-text segments preserve exact whitespace and Rapid Logging indentation.
 * Empty Mermaid fences are left untouched as plain text.
 *
 * @param {string | null | undefined} raw
 * @returns {TranscriptSegment[]}
 */
export function splitMermaidSegments(raw) {
    if (!raw) return [];
    const text = String(raw);
    /** @type {TranscriptSegment[]} */
    const segments = [];
    let lastIndex = 0;

    MERMAID_FENCE_RE.lastIndex = 0;
    let match = MERMAID_FENCE_RE.exec(text);
    while (match !== null) {
        const diagramCode = (match[1] || '').trim();
        if (!diagramCode) {
            match = MERMAID_FENCE_RE.exec(text);
            continue;
        }
        const before = text.slice(lastIndex, match.index);
        if (before.trim()) {
            segments.push({
                type: 'text',
                content: before.replace(/^(?:\r?\n)+|(?:\r?\n)+$/g, ''),
            });
        }
        segments.push({ type: 'mermaid', content: diagramCode });
        lastIndex = match.index + match[0].length;
        match = MERMAID_FENCE_RE.exec(text);
    }

    const tail = text.slice(lastIndex);
    if (segments.length === 0) {
        return text ? [{ type: 'text', content: text }] : [];
    }
    if (tail.trim()) {
        segments.push({
            type: 'text',
            content: tail.replace(/^(?:\r?\n)+|(?:\r?\n)+$/g, ''),
        });
    }
    return segments;
}

/**
 * Lazily import the Mermaid ESM bundle from the browser importmap.
 *
 * @returns {Promise<import('mermaid').MermaidApi>}
 */
function loadDefaultMermaid() {
    if (!cachedMermaidPromise) {
        cachedMermaidPromise = import('mermaid')
            .then((mod) => mod.default)
            .catch((err) => {
                cachedMermaidPromise = null;
                throw err;
            });
    }
    return cachedMermaidPromise;
}

/**
 * Render a Mermaid diagram definition into sanitized SVG markup.
 *
 * Never throws: syntax errors or offline module-load failures resolve to
 * `{ ok: false, error }` so callers can fall back to the raw source block.
 *
 * @param {string} code
 * @param {{ loader?: MermaidLoader }} [options]
 * @returns {Promise<MermaidRenderResult>}
 */
export async function renderMermaidSvg(code, { loader } = {}) {
    const trimmed = String(code || '').trim();
    if (!trimmed) {
        return { ok: false, error: 'Empty Mermaid diagram' };
    }

    try {
        const mermaid = await (loader ? loader() : loadDefaultMermaid());
        if (!initializedInstances.has(mermaid)) {
            mermaid.initialize({
                startOnLoad: false,
                securityLevel: 'strict',
                theme: 'neutral',
                suppressErrorRendering: true,
                htmlLabels: false,
                flowchart: { htmlLabels: false },
            });
            initializedInstances.add(mermaid);
        }
        renderCounter += 1;
        const { svg } = await mermaid.render(`sn-mermaid-${renderCounter}`, trimmed);
        const sanitized = DOMPurify.sanitize(String(svg || ''), SVG_SANITIZE_OPTIONS).trim();
        if (!sanitized) {
            return { ok: false, error: 'Mermaid returned empty SVG' };
        }
        return { ok: true, svg: sanitized };
    } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        return { ok: false, error: message || 'Failed to render Mermaid diagram' };
    }
}
