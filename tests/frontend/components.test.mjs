import assert from 'node:assert/strict';
import test from 'node:test';
import { logout, setToken } from '../../supernote/server/static/js/api/http.js';
import { compareItems } from '../../supernote/server/static/js/components/FileBrowserPanel.js';
import SearchModal from '../../supernote/server/static/js/components/SearchModal.js';
import SystemPanel from '../../supernote/server/static/js/components/SystemPanel.js';
import {
    parseLocalDateInputToEpochMs,
    toLocalDateInputValue,
} from '../../supernote/server/static/js/components/tasks/TaskEditorModal.js';
import { getDueMeta } from '../../supernote/server/static/js/components/tasks/TaskRow.js';
import {
    buildDisplayTranscriptPages,
    formatContent,
    formatLinkLabel,
    formatPageStyle,
    hasCopyablePageText,
    normalizeTranscriptPages,
    parseSafeHttpUrl,
    resolveFileCategory,
    resolveFileExt,
} from '../../supernote/server/static/js/components/viewer/noteMeta.js';
import ViewerSidePanel from '../../supernote/server/static/js/components/viewer/ViewerSidePanel.js';
import {
    loadServerFeatures,
    resetServerFeatures,
} from '../../supernote/server/static/js/composables/useServerFeatures.js';
import { mountComposable } from './helpers/vue_test_scope.mjs';

test('noteMeta.js: parseSafeHttpUrl, categories, page styles, link labels, and merged transcript pages', () => {
    assert.equal(
        parseSafeHttpUrl('https://supernote.com/docs?q=1'),
        'https://supernote.com/docs?q=1',
    );
    assert.equal(parseSafeHttpUrl('  http://localhost:8080/test  '), 'http://localhost:8080/test');
    assert.equal(parseSafeHttpUrl('javascript:alert(1)'), null);
    assert.equal(parseSafeHttpUrl('data:text/html,<script>alert(1)</script>'), null);
    assert.equal(parseSafeHttpUrl('file:///etc/passwd'), null);
    assert.equal(parseSafeHttpUrl('not a url'), null);
    assert.equal(parseSafeHttpUrl(''), null);
    assert.equal(parseSafeHttpUrl(null), null);

    assert.equal(resolveFileExt({ name: 'Sketch.NOTE' }), 'note');
    assert.equal(resolveFileCategory('note'), 'note');
    assert.equal(resolveFileCategory('png'), 'image');
    assert.equal(resolveFileCategory('pdf'), 'pdf');
    assert.equal(resolveFileCategory('md'), 'text');
    assert.equal(resolveFileCategory('epub'), 'unsupported');

    assert.equal(formatPageStyle('white'), null);
    assert.equal(formatPageStyle('8mm_ruled_line'), '8mm ruled');
    assert.equal(
        formatLinkLabel({ targetFileId: '2', target: '/Note/Ref.note', targetPageIndex: 4 }, '1'),
        'Ref.note · p.5',
    );

    const norm = normalizeTranscriptPages([{ page_index: 1, page_id: 'p-1', text: 'hello' }]);
    const merged = buildDisplayTranscriptPages(
        norm,
        { pages: [{ pageIndex: 0, pageId: 'meta-0', date: '2026-03-01', keywords: ['todo'] }] },
        new Map([[0, { pageIndex: 0, date: '2026-03-01', keywords: ['todo'] }]]),
        new Map(),
    );
    assert.deepEqual(merged, [
        {
            pageIndex: 0,
            pageId: 'meta-0',
            text: '',
            date: '2026-03-01',
            hasTranscript: false,
        },
        {
            pageIndex: 1,
            pageId: 'p-1',
            text: 'hello',
            date: null,
            hasTranscript: true,
        },
    ]);

    assert.equal(formatContent('Line 1\\nLine 2'), 'Line 1\nLine 2');
    assert.equal(hasCopyablePageText({ hasTranscript: true, text: 'OCR text' }), true);
    assert.equal(hasCopyablePageText({ hasTranscript: true, text: '   ' }), false);
    assert.equal(hasCopyablePageText({ hasTranscript: false, text: 'OCR text' }), false);
});

test('TaskEditorModal.js & TaskRow.js: local calendar date round-trip and due badge metadata', () => {
    for (const dateStr of ['2026-01-01', '2026-06-18', '2026-12-31']) {
        const epochMs = parseLocalDateInputToEpochMs(dateStr);
        assert.ok(epochMs > 0);
        const d = new Date(epochMs);
        assert.equal(d.getHours(), 12);
        assert.equal(toLocalDateInputValue(d), dateStr);
    }
    assert.equal(parseLocalDateInputToEpochMs('2026-02-30'), 0);
    assert.equal(parseLocalDateInputToEpochMs('invalid'), 0);
    assert.equal(parseLocalDateInputToEpochMs(''), 0);

    const now = new Date();
    const todayNoon = new Date(
        now.getFullYear(),
        now.getMonth(),
        now.getDate(),
        12,
        0,
        0,
    ).getTime();
    assert.equal(getDueMeta({ dueTime: todayNoon, status: 'needsAction' })?.label, 'Due Today');
    const pastMs = new Date(2020, 0, 2, 12, 0, 0).getTime();
    assert.match(getDueMeta({ dueTime: pastMs, status: 'needsAction' })?.label || '', /^Overdue/);
});

test('FileBrowserPanel.js: compareItems groups folders first across name, size, and updatedAt sorts', () => {
    const items = [
        { id: '1', name: 'Note 10.note', isDirectory: false, size: 500, updatedAt: 2000 },
        { id: '2', name: 'Archive', isDirectory: true, size: 0, updatedAt: 1000 },
        { id: '3', name: 'Note 2.note', isDirectory: false, size: 1200, updatedAt: 3000 },
    ];

    assert.deepEqual(
        [...items].sort((a, b) => compareItems(a, b, 'name', 'asc')).map((i) => i.name),
        ['Archive', 'Note 2.note', 'Note 10.note'],
    );
    assert.deepEqual(
        [...items].sort((a, b) => compareItems(a, b, 'size', 'desc')).map((i) => i.name),
        ['Archive', 'Note 2.note', 'Note 10.note'],
    );
    assert.deepEqual(
        [...items].sort((a, b) => compareItems(a, b, 'updatedAt', 'asc')).map((i) => i.name),
        ['Archive', 'Note 10.note', 'Note 2.note'],
    );
});

test('ViewerSidePanel.js: renders standalone image OCR & scene description as sanitized Markdown without notebook tabs', async () => {
    const scope = await mountComposable(() =>
        ViewerSidePanel.setup(
            {
                fileId: '42',
                fileCategory: 'image',
                isOpenMobile: false,
                activeTab: 'transcription',
                activePageIndex: 0,
                hasCanvasPages: false,
                isLoadingTranscript: false,
                transcriptPages: [
                    {
                        pageIndex: 0,
                        pageId: 'img',
                        text: '## Whiteboard\\n\\n- **Scene**: Sunlit office whiteboard\\n- Action item',
                    },
                ],
                displayTranscriptPages: [],
                pageMetaByIndex: new Map(),
                linksByPageIndex: new Map(),
                summaries: [],
                aiStatus: { ocrEnabled: true, model: 'gemini-3.5-flash-lite' },
            },
            {
                expose() {},
                emit() {},
            },
        ),
    );

    try {
        assert.equal(scope.result.isStandaloneImage.value, true);
        assert.equal(scope.result.primaryImagePage.value?.pageId, 'img');
        assert.match(scope.result.primaryImageHtml.value, /<h2>Whiteboard<\/h2>/);
        assert.match(scope.result.primaryImageHtml.value, /Sunlit office whiteboard/);
    } finally {
        scope.unmount();
    }
});

test('ViewerSidePanel.js: hides image HTML on whitespace-only text and keeps notebook mode for note files', async () => {
    const emptyImage = await mountComposable(() =>
        ViewerSidePanel.setup(
            {
                fileId: '43',
                fileCategory: 'image',
                isOpenMobile: false,
                activeTab: 'transcription',
                activePageIndex: 0,
                hasCanvasPages: false,
                isLoadingTranscript: false,
                transcriptPages: [{ pageIndex: 0, pageId: 'img', text: '   \n  ' }],
                displayTranscriptPages: [],
                pageMetaByIndex: new Map(),
                linksByPageIndex: new Map(),
                summaries: [],
                aiStatus: null,
            },
            { expose() {}, emit() {} },
        ),
    );
    try {
        assert.equal(emptyImage.result.isStandaloneImage.value, true);
        assert.equal(emptyImage.result.primaryImageHtml.value, '');
    } finally {
        emptyImage.unmount();
    }

    const notebook = await mountComposable(() =>
        ViewerSidePanel.setup(
            {
                fileId: '44',
                fileCategory: 'note',
                isOpenMobile: false,
                activeTab: 'transcription',
                activePageIndex: 0,
                hasCanvasPages: true,
                isLoadingTranscript: false,
                transcriptPages: [{ pageIndex: 0, pageId: 'p1', text: 'Hello' }],
                displayTranscriptPages: [],
                pageMetaByIndex: new Map(),
                linksByPageIndex: new Map(),
                summaries: [],
                aiStatus: null,
            },
            { expose() {}, emit() {} },
        ),
    );
    try {
        assert.equal(notebook.result.isStandaloneImage.value, false);
    } finally {
        notebook.unmount();
    }
});

test('ViewerSidePanel.js: explains transcript gaps by disabled component, OCR setup, or pending processing', async () => {
    /** @param {Record<string, unknown>} overrides */
    const mountPanel = (overrides) =>
        mountComposable(() =>
            ViewerSidePanel.setup(
                {
                    fileId: '45',
                    fileCategory: 'note',
                    isOpenMobile: false,
                    activeTab: 'transcription',
                    activePageIndex: 0,
                    hasCanvasPages: true,
                    isLoadingTranscript: false,
                    transcriptPages: [],
                    displayTranscriptPages: [],
                    pageMetaByIndex: new Map(),
                    linksByPageIndex: new Map(),
                    summaries: [],
                    aiStatus: { ocrEnabled: false },
                    transcriptEnabled: true,
                    summariesEnabled: true,
                    ...overrides,
                },
                { expose() {}, emit() {} },
            ),
        );

    const cases = [
        [{ transcriptEnabled: false }, 'Handwriting transcription is disabled on this server.'],
        [
            {},
            'OCR is not enabled on this server. Configure an AI provider to automatically transcribe handwritten pages.',
        ],
        [
            { aiStatus: { ocrEnabled: true } },
            'No OCR transcript available for this notebook yet. Background processing may still be running.',
        ],
    ];
    for (const [overrides, expected] of cases) {
        const panel = await mountPanel(overrides);
        try {
            assert.equal(panel.result.transcriptEmptyMessage.value, expected);
        } finally {
            panel.unmount();
        }
    }
});

test('SystemPanel.js: loads read-only system components, active counts, and config summaries', async () => {
    const origFetch = globalThis.fetch;
    const initialComponents = [
        {
            domain: 'webhooks',
            enabled: true,
            running: true,
            source: 'database',
            readOnly: false,
            runtimeConfigurable: true,
            restartRequired: false,
            config: { enabled: true, endpoints: [{ url: 'http://127.0.0.1:9999/hook' }] },
            fields: [
                { name: 'enabled', type: 'boolean', default: false },
                { name: 'endpoints', type: 'array', default: [] },
            ],
        },
        {
            domain: 'wiki',
            enabled: false,
            running: false,
            source: 'env',
            readOnly: true,
            runtimeConfigurable: false,
            restartRequired: false,
            config: { enabled: false, debounce_seconds: 60 },
            fields: [
                { name: 'enabled', type: 'boolean', default: false },
                { name: 'debounce_seconds', type: 'number', default: 60 },
            ],
        },
    ];

    try {
        setToken('admin-tok');
        globalThis.fetch = async (url) => {
            if (url === '/api/extended/system/tasks') {
                return new Response(
                    JSON.stringify({
                        tasks: [],
                        paused: false,
                        queueSize: 0,
                        processingFileIds: [],
                    }),
                );
            }
            if (url === '/api/file/capacity/query') {
                return new Response(JSON.stringify({ usedCapacity: 1024, totalCapacity: 1048576 }));
            }
            if (url === '/api/extended/ai/status') {
                return new Response(JSON.stringify({ ocrEnabled: true, model: 'gemini' }));
            }
            if (url === '/api/extended/system/components') {
                return new Response(
                    JSON.stringify({ success: true, components: initialComponents }),
                );
            }
            if (url === '/api/extended/system/components/webhooks') {
                return new Response(
                    JSON.stringify({
                        success: true,
                        component: {
                            ...initialComponents[0],
                            enabled: false,
                            running: false,
                            config: { ...initialComponents[0].config, enabled: false },
                        },
                    }),
                );
            }
            return new Response(JSON.stringify({ success: true }));
        };

        globalThis.window = /** @type {any} */ ({
            addEventListener() {},
            removeEventListener() {},
        });
        const scope = await mountComposable(() => SystemPanel.setup());
        try {
            await scope.result.loadData();
            assert.equal(scope.result.systemComponents.value.length, 2);
            assert.equal(scope.result.activeComponentCount.value, 1);
            assert.equal(scope.result.formatComponentSource('env'), 'ENV');
            assert.deepEqual(scope.result.componentConfigSummary(initialComponents[0]), [
                'endpoints: 1',
            ]);
            assert.deepEqual(scope.result.componentConfigSummary(initialComponents[1]), [
                'debounce_seconds: 60',
            ]);

            await scope.result.handleToggleComponent(scope.result.systemComponents.value[0]);
            assert.equal(scope.result.systemComponents.value[0].enabled, false);
        } finally {
            scope.unmount();
            delete (/** @type {any} */ (globalThis).window);
        }
    } finally {
        resetServerFeatures();
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('SystemPanel.js: skips queue and AI status requests when processor and ai are disabled', async () => {
    const origFetch = globalThis.fetch;
    /** @type {string[]} */
    const requestedUrls = [];

    try {
        setToken('sys-disabled-tok');
        globalThis.fetch = async (url) => {
            const urlStr = String(url);
            requestedUrls.push(urlStr);
            if (urlStr === '/api/extended/system/features') {
                return new Response(
                    JSON.stringify({
                        success: true,
                        runningComponents: ['config', 'http', 'web_ui'],
                    }),
                );
            }
            if (urlStr === '/api/file/capacity/query') {
                return new Response(
                    JSON.stringify({ success: true, usedCapacity: 512, totalCapacity: 2048 }),
                );
            }
            if (urlStr === '/api/extended/system/components') {
                return new Response(JSON.stringify({ success: true, components: [] }));
            }
            return new Response('Not Found', { status: 404 });
        };

        await loadServerFeatures();
        requestedUrls.length = 0;

        globalThis.window = /** @type {any} */ ({
            addEventListener() {},
            removeEventListener() {},
        });
        const scope = await mountComposable(() => SystemPanel.setup());
        try {
            await scope.result.loadData();
            assert.equal(scope.result.processorEnabled.value, false);
            assert.equal(scope.result.aiEnabled.value, false);
            assert.equal(scope.result.error.value, null);
            assert.equal(scope.result.queueBadgeLabel.value, 'DISABLED');
            assert.equal(scope.result.queueHeadline.value, 'Background processing is disabled');
            assert.equal(scope.result.aiStatus.value, null);
            assert.equal(scope.result.capacity.value?.usedCapacity, 512);
            assert.ok(!requestedUrls.includes('/api/extended/system/tasks'));
            assert.ok(!requestedUrls.includes('/api/extended/ai/status'));
        } finally {
            scope.unmount();
            delete (/** @type {any} */ (globalThis).window);
        }
    } finally {
        resetServerFeatures();
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('SearchModal.js: skips semantic and task requests when search and schedule are disabled', async () => {
    const origFetch = globalThis.fetch;
    /** @type {string[]} */
    const requestedUrls = [];

    try {
        setToken('search-disabled-tok');
        globalThis.fetch = async (url) => {
            const urlStr = String(url);
            requestedUrls.push(urlStr);
            if (urlStr === '/api/extended/system/features') {
                return new Response(
                    JSON.stringify({ success: true, runningComponents: ['http', 'web_ui'] }),
                );
            }
            if (urlStr === '/api/file/label/list/search') {
                return new Response(
                    JSON.stringify({
                        success: true,
                        entries: [{ id: '1', fileName: 'Stroller.note', isFolder: 'N' }],
                    }),
                );
            }
            return new Response('Not Found', { status: 404 });
        };

        await loadServerFeatures();
        requestedUrls.length = 0;

        globalThis.window = /** @type {any} */ ({
            addEventListener() {},
            removeEventListener() {},
        });
        const scope = await mountComposable(() =>
            SearchModal.setup({ initialQuery: 'stroller' }, { emit() {} }),
        );
        try {
            await new Promise((resolve) => setImmediate(resolve));
            assert.equal(scope.result.results.value.length, 1);
            assert.deepEqual(scope.result.semanticResults.value, []);
            assert.deepEqual(scope.result.taskResults.value, []);
            assert.deepEqual(requestedUrls, ['/api/file/label/list/search']);
        } finally {
            scope.unmount();
            delete (/** @type {any} */ (globalThis).window);
        }
    } finally {
        resetServerFeatures();
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});
