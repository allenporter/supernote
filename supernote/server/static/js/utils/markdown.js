/**
 * Safe CommonMark + GFM Markdown renderer backed by marked and DOMPurify.
 */

import DOMPurify from 'dompurify';
import { Marked } from 'marked';

const SANITIZE_OPTIONS = {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['form', 'input', 'button', 'textarea', 'select', 'style', 'img'],
    ADD_ATTR: ['data-wiki-link'],
};

const WIKILINK_RE = /\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g;
const SAFE_SLUG_RE = /^[a-z0-9][a-z0-9._-]*(?:\/[a-z0-9][a-z0-9._-]*)*$/;

const markdownParser = new Marked({
    gfm: true,
    breaks: true,
    renderer: {
        checkbox({ checked }) {
            const stateClass = checked ? 'md-task-box is-checked' : 'md-task-box';
            const mark = checked ? '✓' : '';
            return `<span class="${stateClass}" role="checkbox" aria-checked="${checked ? 'true' : 'false'}">${mark}</span> `;
        },
        listitem(item) {
            const inner = this.parser.parse(item.tokens);
            if (item.task) {
                return `<li class="md-task-item">${inner}</li>\n`;
            }
            return `<li>${inner}</li>\n`;
        },
    },
});

/**
 * Normalize a raw wikilink target into a safe canonical slug, or null if invalid.
 *
 * @param {string} raw
 * @returns {string | null}
 */
function normalizeSafeWikiSlug(raw) {
    const cleaned = raw
        .trim()
        .replace(/^\/+|\/+$/g, '')
        .toLowerCase();
    if (!cleaned || cleaned.includes('..') || !SAFE_SLUG_RE.test(cleaned)) {
        return null;
    }
    return cleaned;
}

/**
 * Escape HTML special characters for inline text nodes.
 *
 * @param {string} text
 * @returns {string}
 */
function escapeHtml(text) {
    return text
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;');
}

/**
 * Render Markdown text to sanitized HTML with safe external link attributes.
 *
 * @param {string|null|undefined} raw
 * @param {{ enableWikilinks?: boolean }} [options]
 * @returns {string}
 */
export function renderMarkdown(raw, { enableWikilinks = false } = {}) {
    if (raw === null || raw === undefined) return '';
    let normalized = String(raw).replaceAll('\\n', '\n').trim();
    if (!normalized) return '';

    if (enableWikilinks) {
        // Mask fenced code blocks and inline code spans before rewriting [[wikilinks]].
        /** @type {string[]} */
        const codePlaceholders = [];
        normalized = normalized.replace(/(```[\s\S]*?```|`[^`\n]+`)/g, (code) => {
            const idx = codePlaceholders.length;
            codePlaceholders.push(code);
            return `@@WIKI_CODE_${idx}@@`;
        });
        normalized = normalized.replace(WIKILINK_RE, (_match, rawTarget, rawLabel) => {
            const slug = normalizeSafeWikiSlug(String(rawTarget || ''));
            if (!slug) {
                return escapeHtml(String(rawLabel || rawTarget || ''));
            }
            const label = escapeHtml(String(rawLabel || slug).trim());
            return `<a href="#/wiki/${slug}" data-wiki-link="${slug}">${label}</a>`;
        });
        normalized = normalized.replace(/@@WIKI_CODE_(\d+)@@/g, (_m, idx) => {
            return codePlaceholders[Number(idx)] ?? '';
        });
    }

    const rawHtml = markdownParser.parse(normalized);
    const sanitized = DOMPurify.sanitize(String(rawHtml), SANITIZE_OPTIONS);

    if (typeof document !== 'undefined') {
        const tpl = document.createElement('template');
        tpl.innerHTML = sanitized;
        for (const anchor of tpl.content.querySelectorAll('a')) {
            if (anchor.hasAttribute?.('data-wiki-link')) {
                const rawSlug = anchor.getAttribute?.('data-wiki-link') || '';
                const safeSlug = normalizeSafeWikiSlug(rawSlug);
                if (!safeSlug) {
                    anchor.removeAttribute?.('data-wiki-link');
                } else {
                    anchor.setAttribute('data-wiki-link', safeSlug);
                }
            }
            if (!anchor.hasAttribute('href')) {
                anchor.replaceWith(...anchor.childNodes);
                continue;
            }
            const href = anchor.getAttribute?.('href') || '';
            if (enableWikilinks && href.startsWith('#/')) {
                anchor.removeAttribute?.('target');
                anchor.removeAttribute?.('rel');
            } else {
                anchor.setAttribute('target', '_blank');
                anchor.setAttribute('rel', 'noopener noreferrer');
            }
        }
        return tpl.innerHTML;
    }

    return sanitized;
}

/**
 * Render Wiki Markdown with safe `[[wikilink]]` resolution and in-app `#/` links.
 *
 * @param {string|null|undefined} raw
 * @returns {string}
 */
export function renderWikiMarkdown(raw) {
    return renderMarkdown(raw, { enableWikilinks: true });
}
