import assert from 'node:assert/strict';
import test from 'node:test';

import {
    renderMermaidSvg,
    splitMermaidSegments,
} from '../../supernote/server/static/js/utils/mermaid.js';

test('splitMermaidSegments: handles empty, null, and plain text without fences', () => {
    assert.deepEqual(splitMermaidSegments(''), []);
    assert.deepEqual(splitMermaidSegments(null), []);
    assert.deepEqual(splitMermaidSegments(undefined), []);

    const plain = '• Task one\n  - Indented note';
    assert.deepEqual(splitMermaidSegments(plain), [{ type: 'text', content: plain }]);
});

test('splitMermaidSegments: extracts fenced mermaid blocks while preserving surrounding text', () => {
    const raw = [
        'Auth Flow Architecture',
        '',
        '```mermaid',
        'flowchart TD',
        '    A[Client] --> B[Gateway]',
        '```',
        '',
        'Notes:',
        '  - Keep WAL enabled',
    ].join('\n');

    assert.deepEqual(splitMermaidSegments(raw), [
        { type: 'text', content: 'Auth Flow Architecture' },
        { type: 'mermaid', content: 'flowchart TD\n    A[Client] --> B[Gateway]' },
        { type: 'text', content: 'Notes:\n  - Keep WAL enabled' },
    ]);
});

test('splitMermaidSegments: handles multiple blocks, CRLF, and ignores empty fences', () => {
    const raw =
        '```MERMAID\r\ngraph LR\r\n  A --> B\r\n```\r\n\r\n```mermaid\n   \n```\n\n```mermaid\nsequenceDiagram\n  A->>B: hi\n```';
    assert.deepEqual(splitMermaidSegments(raw), [
        { type: 'mermaid', content: 'graph LR\r\n  A --> B' },
        { type: 'text', content: '```mermaid\n   \n```' },
        { type: 'mermaid', content: 'sequenceDiagram\n  A->>B: hi' },
    ]);
});

test('renderMermaidSvg: initializes mermaid once with strict security and sanitizes returned SVG', async () => {
    let initCount = 0;
    /** @type {Record<string, unknown> | null} */
    let initCfg = null;
    const fakeMermaid = {
        initialize(cfg) {
            initCount += 1;
            initCfg = cfg;
        },
        async render(_id, def) {
            return { svg: `<svg><g>${def}</g><script>alert(1)</script></svg>` };
        },
    };

    const first = await renderMermaidSvg('flowchart TD\n  A --> B', {
        loader: async () => fakeMermaid,
    });
    const second = await renderMermaidSvg('graph LR\n  C --> D', {
        loader: async () => fakeMermaid,
    });

    assert.equal(initCount, 1);
    assert.deepEqual(initCfg, {
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'neutral',
        suppressErrorRendering: true,
        htmlLabels: false,
        flowchart: { htmlLabels: false },
    });
    assert.equal(first.ok, true);
    if (first.ok) {
        assert.match(first.svg, /<svg>/);
        assert.doesNotMatch(first.svg, /<script>/i);
    }
    assert.equal(second.ok, true);
});

test('renderMermaidSvg: returns ok=false on empty input, syntax error, or loader failure', async () => {
    const emptyRes = await renderMermaidSvg('   ');
    assert.equal(emptyRes.ok, false);

    const syntaxErr = await renderMermaidSvg('invalid mermaid', {
        loader: async () => ({
            initialize() {},
            async render() {
                throw new Error('Parse error on line 1');
            },
        }),
    });
    assert.deepEqual(syntaxErr, { ok: false, error: 'Parse error on line 1' });

    const loadErr = await renderMermaidSvg('flowchart TD\n  A --> B', {
        loader: async () => {
            throw new Error('Network offline');
        },
    });
    assert.deepEqual(loadErr, { ok: false, error: 'Network offline' });
});
