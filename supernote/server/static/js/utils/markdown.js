/**
 * Safe CommonMark + GFM Markdown renderer backed by marked and DOMPurify.
 */

import DOMPurify from 'dompurify';
import { Marked } from 'marked';

const SANITIZE_OPTIONS = {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['form', 'input', 'button', 'textarea', 'select', 'style', 'img'],
};

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
 * Render Markdown text to sanitized HTML with safe external link attributes.
 *
 * @param {string|null|undefined} raw
 * @returns {string}
 */
export function renderMarkdown(raw) {
    if (raw === null || raw === undefined) return '';
    const normalized = String(raw).replaceAll('\\n', '\n').trim();
    if (!normalized) return '';

    const rawHtml = markdownParser.parse(normalized);
    const sanitized = DOMPurify.sanitize(String(rawHtml), SANITIZE_OPTIONS);

    if (typeof document !== 'undefined') {
        const tpl = document.createElement('template');
        tpl.innerHTML = sanitized;
        for (const anchor of tpl.content.querySelectorAll('a')) {
            if (anchor.hasAttribute('href')) {
                anchor.setAttribute('target', '_blank');
                anchor.setAttribute('rel', 'noopener noreferrer');
            } else {
                anchor.replaceWith(...anchor.childNodes);
            }
        }
        return tpl.innerHTML;
    }

    return sanitized;
}
