import assert from 'node:assert/strict';
import test from 'node:test';

import {
    renderMarkdown,
    renderWikiMarkdown,
} from '../../supernote/server/static/js/utils/markdown.js';

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

test('renderWikiMarkdown converts safe [[wikilinks]], skips code, and rejects XSS/traversal', () => {
    const html = renderWikiMarkdown(
        'See [[entities/Alice|Alice]] and [[../bad]] and [[a/./b]] and `[[projects/in-code]]` and [[entities/bob|<script>alert(1)</script>]].',
    );
    assert.ok(html.includes('href="#/wiki/entities/alice"'));
    assert.ok(html.includes('data-wiki-link="entities/alice"'));
    assert.ok(!html.includes('../bad"'));
    assert.ok(!html.includes('a/./b"'));
    assert.ok(html.includes('[[projects/in-code]]'));
    assert.ok(!html.includes('data-wiki-link="projects/in-code"'));
    assert.ok(!html.includes('<script>'));
});

test('renderWikiMarkdown strips unsafe raw data-wiki-link attributes in DOM mode', () => {
    const originalDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
    try {
        Object.defineProperty(globalThis, 'document', {
            value: {
                createElement() {
                    let html = '';
                    return {
                        set innerHTML(value) {
                            html = String(value);
                        },
                        get innerHTML() {
                            return html;
                        },
                        content: {
                            querySelectorAll() {
                                const anchors = [...html.matchAll(/<a\b([^>]*)>(.*?)<\/a>/g)];
                                return anchors.map((match) => {
                                    let attrs = match[1];
                                    const full = match[0];
                                    let current = full;
                                    const update = (nextAttrs) => {
                                        const next = `<a${nextAttrs}>${match[2]}</a>`;
                                        html = html.replace(current, next);
                                        current = next;
                                        attrs = nextAttrs;
                                    };
                                    return {
                                        hasAttribute: (name) =>
                                            new RegExp(`\\b${name}=`).test(attrs),
                                        getAttribute: (name) =>
                                            attrs.match(new RegExp(`\\b${name}="([^"]*)"`))?.[1] ??
                                            null,
                                        setAttribute: (name, value) => {
                                            if (new RegExp(`\\b${name}="[^"]*"`).test(attrs)) {
                                                update(
                                                    attrs.replace(
                                                        new RegExp(`\\b${name}="[^"]*"`),
                                                        `${name}="${value}"`,
                                                    ),
                                                );
                                            } else {
                                                update(`${attrs} ${name}="${value}"`);
                                            }
                                        },
                                        removeAttribute: (name) => {
                                            update(
                                                attrs.replace(
                                                    new RegExp(`\\s*\\b${name}="[^"]*"`),
                                                    '',
                                                ),
                                            );
                                        },
                                        replaceWith: () => {},
                                        childNodes: [],
                                    };
                                });
                            },
                        },
                    };
                },
            },
            configurable: true,
        });

        const html = renderWikiMarkdown(
            'Raw <a href="#/wiki/ok" data-wiki-link="../../secret">Trap</a> and [[projects/ok]]',
        );
        assert.ok(!html.includes('data-wiki-link="../../secret"'));
        assert.ok(html.includes('data-wiki-link="projects/ok"'));
        assert.ok(!html.includes('target="_blank"'));
    } finally {
        if (originalDocument) {
            Object.defineProperty(globalThis, 'document', originalDocument);
        } else {
            delete globalThis.document;
        }
    }
});
