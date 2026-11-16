import assert from 'node:assert/strict';
import test from 'node:test';

import { renderMarkdown } from '../../supernote/server/static/js/utils/markdown.js';

test('markdown.js: renders GFM task checkboxes and bullet lists while stripping forbidden tags', () => {
    assert.equal(renderMarkdown(''), '');
    assert.equal(renderMarkdown(null), '');

    const rendered = renderMarkdown(
        '## 2026-06-18\\n\\n- [x] **Done**\\n- [ ] Pending\\n- Plain bullet<script>evil()</script><form><input></form><img src="x">',
    );
    assert.match(rendered, /<h2>2026-06-18<\/h2>/);
    assert.match(rendered, /class="md-task-box is-checked" role="checkbox" aria-checked="true"/);
    assert.match(rendered, /class="md-task-box" role="checkbox" aria-checked="false"/);
    assert.match(rendered, /<li>Plain bullet<\/li>/);
    assert.doesNotMatch(rendered, /<(script|form|input|img)\b/i);
});

test('markdown.js: adds target/_blank + noopener noreferrer on href anchors and unwraps empty anchors in DOM mode', () => {
    const originalDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');

    try {
        Object.defineProperty(globalThis, 'document', {
            value: {
                createElement(tag) {
                    assert.equal(tag, 'template');
                    let html = '';
                    /** @type {Array<{ hasHref: boolean, href: string, label: string, attrs: Record<string, string>, unwrapped: boolean }>} */
                    let anchors = [];
                    return {
                        get innerHTML() {
                            return anchors.reduce((acc, a) => {
                                const orig = a.hasHref
                                    ? `<a href="${a.href}">${a.label}</a>`
                                    : `<a>${a.label}</a>`;
                                if (a.unwrapped) return acc.replace(orig, a.label);
                                const extra = Object.entries(a.attrs)
                                    .map(([k, v]) => ` ${k}="${v}"`)
                                    .join('');
                                return acc.replace(
                                    orig,
                                    `<a href="${a.href}"${extra}>${a.label}</a>`,
                                );
                            }, html);
                        },
                        set innerHTML(val) {
                            html = String(val);
                            anchors = [];
                            const re = /<a(?:\s+href="([^"]*)")?>([^<]*)<\/a>/g;
                            for (const m of html.matchAll(re)) {
                                const hasHref = m[1] !== undefined;
                                const record = {
                                    hasHref,
                                    href: m[1] || '',
                                    label: m[2],
                                    attrs: /** @type {Record<string, string>} */ ({}),
                                    unwrapped: false,
                                };
                                anchors.push(record);
                            }
                        },
                        content: {
                            querySelectorAll(sel) {
                                assert.equal(sel, 'a');
                                return anchors.map((a) => ({
                                    childNodes: [a.label],
                                    hasAttribute(attr) {
                                        return attr === 'href' && a.hasHref;
                                    },
                                    setAttribute(k, v) {
                                        a.attrs[k] = v;
                                    },
                                    replaceWith() {
                                        a.unwrapped = true;
                                    },
                                }));
                            },
                        },
                    };
                },
            },
            configurable: true,
        });

        const rendered = renderMarkdown('See [Spec](https://example.com) and [Unlinked]()');
        assert.equal(
            rendered,
            '<p>See <a href="https://example.com" target="_blank" rel="noopener noreferrer">Spec</a> and Unlinked</p>',
        );
    } finally {
        if (originalDocument) {
            Object.defineProperty(globalThis, 'document', originalDocument);
        } else {
            delete globalThis.document;
        }
    }
});
