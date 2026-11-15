import assert from 'node:assert/strict';
import test from 'node:test';

import { computeSocketSignature } from '../../supernote/server/static/js/api/client.js';
import { apiRequest, getToken, logout, onLogout, setToken } from '../../supernote/server/static/js/api/http.js';
import {
    fetchIcsFeed,
    fetchTasks,
    normalizeTaskImportance,
} from '../../supernote/server/static/js/api/schedule.js';
import { compareItems } from '../../supernote/server/static/js/components/FileBrowserPanel.js';
import { toLocalDateInputValue } from '../../supernote/server/static/js/components/tasks/TaskEditorModal.js';
import { getDueMeta } from '../../supernote/server/static/js/components/tasks/TaskRow.js';
import {
    buildDisplayTranscriptPages,
    formatContent,
    formatLinkLabel,
    formatPageStyle,
    hasCopyablePageText,
    normalizeTranscriptPages,
    resolveFileCategory,
    resolveFileExt,
} from '../../supernote/server/static/js/components/viewer/noteMeta.js';
import {
    buildCrumbsFromPathInfo,
    buildUrlHash,
    formatCrumbName,
    parseUrlHash,
} from '../../supernote/server/static/js/composables/useRouter.js';
import { copyTextToClipboard } from '../../supernote/server/static/js/utils/clipboard.js';
import { formatSize, normalizeEpochMs } from '../../supernote/server/static/js/utils/format.js';
import { renderMarkdown } from '../../supernote/server/static/js/utils/markdown.js';
import {
    describeRedirectTarget,
    describeScope,
    parseOAuthBridgeReturnTo,
} from '../../supernote/server/static/js/utils/oauth.js';

test('http.js: token lifecycle, headers, fallbackValue, and 401 logout teardown', async () => {
    const calls = [];
    const originalFetch = globalThis.fetch;
    try {
        setToken('tok-123');
        assert.equal(getToken(), 'tok-123');

        globalThis.fetch = async (url, init) => {
            calls.push({ url, init });
            if (url === '/api/ok') {
                return new Response(JSON.stringify({ ok: true }), { status: 200 });
            }
            if (url === '/api/text') {
                return new Response('BEGIN:VCALENDAR', { status: 200 });
            }
            if (url === '/api/missing') {
                return new Response('Not Found', { status: 404, statusText: 'Not Found' });
            }
            if (url === '/api/expired') {
                return new Response('Unauthorized', { status: 401 });
            }
            return new Response('{}', { status: 200 });
        };

        const jsonRes = await apiRequest('/api/ok', { body: { id: '1' } });
        assert.deepEqual(jsonRes, { ok: true });
        assert.equal(calls[0].init.headers['x-access-token'], 'tok-123');
        assert.equal(calls[0].init.headers['Content-Type'], 'application/json');

        const textRes = await apiRequest('/api/text', { method: 'GET', responseType: 'text' });
        assert.equal(textRes, 'BEGIN:VCALENDAR');

        const fallback = await apiRequest('/api/missing', { fallbackValue: [] });
        assert.deepEqual(fallback, []);

        let logoutNotified = 0;
        const unsubscribe = onLogout(() => {
            logoutNotified++;
        });
        await assert.rejects(() => apiRequest('/api/expired'), /Unauthorized/);
        assert.equal(getToken(), null);
        assert.equal(logoutNotified, 1);
        unsubscribe();

        await assert.rejects(() => apiRequest('/api/ok'), /Unauthorized/);
    } finally {
        await logout({ reload: false });
        globalThis.fetch = originalFetch;
    }
});

test('schedule.js: normalizeTaskImportance, fetchTasks mapping, and fetchIcsFeed URL', async () => {
    assert.equal(normalizeTaskImportance('1'), 'high');
    assert.equal(normalizeTaskImportance('HIGH'), 'high');
    assert.equal(normalizeTaskImportance('5'), 'medium');
    assert.equal(normalizeTaskImportance('normal'), 'medium');
    assert.equal(normalizeTaskImportance('9'), 'low');
    assert.equal(normalizeTaskImportance(null), 'low');

    const originalFetch = globalThis.fetch;
    try {
        setToken('sched-token');
        let lastUrl = '';
        globalThis.fetch = async (url) => {
            lastUrl = url;
            if (url.startsWith('/api/schedule/feed.ics')) {
                return new Response('BEGIN:VCALENDAR\nEND:VCALENDAR', { status: 200 });
            }
            return new Response(
                JSON.stringify({
                    scheduleTask: [
                        {
                            taskId: 99,
                            taskListId: 7,
                            title: 'Review notebook',
                            importance: '1',
                            isReminderOn: 'Y',
                        },
                    ],
                    nextPageToken: 'next-1',
                }),
                { status: 200 }
            );
        };

        const { tasks, nextPageToken } = await fetchTasks('7');
        assert.equal(nextPageToken, 'next-1');
        assert.equal(tasks.length, 1);
        assert.equal(tasks[0].id, '99');
        assert.equal(tasks[0].taskListId, '7');
        assert.equal(tasks[0].importance, 'high');
        assert.equal(tasks[0].isReminderOn, true);

        const ics = await fetchIcsFeed('list a/b');
        assert.match(ics, /BEGIN:VCALENDAR/);
        assert.equal(lastUrl, '/api/schedule/feed.ics?taskListId=list%20a%2Fb');
    } finally {
        await logout({ reload: false });
        globalThis.fetch = originalFetch;
    }
});

test('useRouter.js: parseUrlHash, buildUrlHash, and breadcrumb builders', () => {
    assert.deepEqual(parseUrlHash(''), {
        tab: 'files',
        view: 'grid',
        dirId: '0',
        showSystem: false,
    });
    assert.deepEqual(parseUrlHash('#/files/42'), {
        tab: 'files',
        view: 'grid',
        dirId: '42',
        showSystem: false,
    });
    assert.deepEqual(parseUrlHash('#/file/9001?page=3'), {
        tab: 'files',
        view: 'viewer',
        fileId: '9001',
        pageIndex: 2,
        showSystem: false,
    });
    assert.deepEqual(parseUrlHash('#/tasks'), {
        tab: 'tasks',
        view: 'grid',
        dirId: '0',
        showSystem: false,
    });
    assert.deepEqual(parseUrlHash('#/system'), {
        tab: 'system',
        view: 'grid',
        dirId: '0',
        showSystem: true,
    });

    assert.equal(buildUrlHash('files', '0', 'grid', null, false, null), '#/files');
    assert.equal(buildUrlHash('files', '42', 'grid', null, false, null), '#/files/42');
    assert.equal(buildUrlHash('files', '42', 'viewer', { id: '9001' }, false, 0), '#/file/9001');
    assert.equal(buildUrlHash('files', '42', 'viewer', { id: '9001' }, false, 2), '#/file/9001?page=3');
    assert.equal(buildUrlHash('tasks', '0', 'grid', null, false, null), '#/tasks');
    assert.equal(buildUrlHash('files', '0', 'grid', null, true, null), '#/system');

    assert.equal(formatCrumbName('INBOX', 0), 'Inbox');
    assert.equal(formatCrumbName('Projects', 1), 'Projects');
    assert.deepEqual(
        buildCrumbsFromPathInfo({ path: '/INBOX/Specs', idPath: '/10/20' }),
        [
            { id: '0', name: 'Cloud' },
            { id: '10', name: 'Inbox' },
            { id: '20', name: 'Specs' },
        ]
    );
});

test('format.js & oauth.js: epoch normalization, byte sizes, and OAuth /login-bridge safety', () => {
    assert.equal(normalizeEpochMs(1700000000), 1700000000000);
    assert.equal(normalizeEpochMs('1700000000000'), 1700000000000);
    assert.equal(normalizeEpochMs('2026-01-15T00:00:00Z'), Date.parse('2026-01-15T00:00:00Z'));
    assert.equal(normalizeEpochMs(0), null);
    assert.equal(normalizeEpochMs(''), null);

    assert.equal(formatSize(0, '—'), '—');
    assert.equal(formatSize(1536), '1.5 KB');

    assert.match(describeScope('supernote:all'), /Full access/);
    assert.equal(describeRedirectTarget('cursor://anysphere.cursor-mcp/cb').isCustomScheme, true);
    assert.equal(describeRedirectTarget('https://claude.ai/api/mcp/auth_callback').hostLabel, 'claude.ai');

    // Cross-origin return_to must be rejected
    assert.equal(
        parseOAuthBridgeReturnTo(
            '#/login?return_to=' + encodeURIComponent('https://evil.example/login-bridge?client_id=x&code_challenge=y'),
            'http://127.0.0.1:8080'
        ),
        null
    );

    const valid = parseOAuthBridgeReturnTo(
        '#/login?return_to=' +
            encodeURIComponent(
                '/login-bridge?client_id=https%3A%2F%2Fclaude.ai%2Fcb&code_challenge=abc123&state=s1'
            ),
        'http://127.0.0.1:8080'
    );
    assert.equal(valid?.isValid, true);
    assert.equal(valid?.state, 's1');
    assert.deepEqual(valid?.scopes, ['supernote:all']);
});

test('noteMeta.js & task helpers: file categories, merged transcript pages, and due badges', () => {
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
        'Ref.note · p.5'
    );

    const norm = normalizeTranscriptPages([{ page_index: 1, page_id: 'p-1', text: 'hello' }]);
    const merged = buildDisplayTranscriptPages(
        norm,
        { pages: [{ pageIndex: 0, keywords: ['todo'] }] },
        new Map([[0, { pageIndex: 0, date: '2026-03-01', keywords: ['todo'] }]]),
        new Map()
    );
    assert.deepEqual(
        merged.map((p) => ({ idx: p.pageIndex, hasTranscript: p.hasTranscript })),
        [
            { idx: 0, hasTranscript: false },
            { idx: 1, hasTranscript: true },
        ]
    );

    assert.equal(toLocalDateInputValue(new Date(2026, 0, 5)), '2026-01-05');
    const now = new Date();
    const todayNoon = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 12, 0, 0).getTime();
    assert.equal(getDueMeta({ dueTime: todayNoon, status: 'needsAction' })?.label, 'Due Today');
    const pastMs = new Date(2020, 0, 2, 12, 0, 0).getTime();
    assert.match(getDueMeta({ dueTime: pastMs, status: 'needsAction' })?.label || '', /^Overdue/);

    assert.equal(formatContent('Line 1\\nLine 2'), 'Line 1\nLine 2');
    assert.equal(hasCopyablePageText({ hasTranscript: true, text: 'OCR text' }), true);
    assert.equal(hasCopyablePageText({ hasTranscript: true, text: '   ' }), false);
    assert.equal(hasCopyablePageText({ hasTranscript: false, text: 'OCR text' }), false);
});

test('clipboard.js & markdown.js: clipboard write + plain-HTTP fallback and sanitized Markdown', async () => {
    assert.equal(await copyTextToClipboard(''), false);
    assert.equal(await copyTextToClipboard(null), false);

    const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
    const originalDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');

    try {
        // 1. Modern navigator.clipboard.writeText path
        let writtenText = null;
        Object.defineProperty(globalThis, 'navigator', {
            value: {
                clipboard: {
                    async writeText(val) {
                        writtenText = val;
                    },
                },
            },
            configurable: true,
        });
        assert.equal(await copyTextToClipboard('Page 1 transcript'), true);
        assert.equal(writtenText, 'Page 1 transcript');

        // 2. Fallback textarea + execCommand('copy') when clipboard API rejects (e.g. plain HTTP LAN)
        const appended = [];
        let copiedViaExec = false;
        Object.defineProperty(globalThis, 'navigator', {
            value: {
                clipboard: {
                    async writeText() {
                        throw new Error('Insecure context');
                    },
                },
            },
            configurable: true,
        });
        Object.defineProperty(globalThis, 'document', {
            value: {
                body: {
                    appendChild(el) {
                        appended.push(el);
                    },
                    removeChild(el) {
                        const idx = appended.indexOf(el);
                        if (idx !== -1) appended.splice(idx, 1);
                    },
                },
                createElement(tag) {
                    if (tag === 'textarea') {
                        return {
                            value: '',
                            style: {},
                            setAttribute() {},
                            focus() {},
                            select() {},
                            setSelectionRange() {},
                        };
                    }
                    return {
                        innerHTML: '',
                        content: { querySelectorAll: () => [] },
                    };
                },
                execCommand(cmd) {
                    if (cmd === 'copy') {
                        copiedViaExec = true;
                        return true;
                    }
                    return false;
                },
            },
            configurable: true,
        });

        assert.equal(await copyTextToClipboard('LAN fallback transcript'), true);
        assert.equal(copiedViaExec, true);
        assert.equal(appended.length, 0);
    } finally {
        if (originalNavigator) {
            Object.defineProperty(globalThis, 'navigator', originalNavigator);
        } else {
            delete globalThis.navigator;
        }
        if (originalDocument) {
            Object.defineProperty(globalThis, 'document', originalDocument);
        } else {
            delete globalThis.document;
        }
    }

    assert.equal(renderMarkdown(''), '');
    assert.equal(renderMarkdown(null), '');
    const rendered = renderMarkdown('## 2026-06-18\\n\\nSummary body<script>evil()</script>');
    assert.match(rendered, /<h2>2026-06-18<\/h2>/);
    assert.doesNotMatch(rendered, /<script>/);
});

test('FileBrowserPanel compareItems & client computeSocketSignature', async () => {
    const items = [
        { id: '1', name: 'Note 10.note', isDirectory: false, size: 500, updatedAt: 2000 },
        { id: '2', name: 'Archive', isDirectory: true, size: 0, updatedAt: 1000 },
        { id: '3', name: 'Note 2.note', isDirectory: false, size: 1200, updatedAt: 3000 },
    ];

    const byNameAsc = [...items].sort((a, b) => compareItems(a, b, 'name', 'asc'));
    assert.deepEqual(byNameAsc.map((i) => i.name), ['Archive', 'Note 2.note', 'Note 10.note']);

    const bySizeDesc = [...items].sort((a, b) => compareItems(a, b, 'size', 'desc'));
    assert.deepEqual(bySizeDesc.map((i) => i.name), ['Archive', 'Note 2.note', 'Note 10.note']);

    const byDateAsc = [...items].sort((a, b) => compareItems(a, b, 'updatedAt', 'asc'));
    assert.deepEqual(byDateAsc.map((i) => i.name), ['Archive', 'Note 10.note', 'Note 2.note']);

    const origWindow = globalThis.window;
    try {
        globalThis.window = { crypto: globalThis.crypto };
        const sigWebCrypto = await computeSocketSignature('tok1', 'WEB', '12345');
        assert.match(sigWebCrypto, /^[A-Za-z0-9]+$/);
        assert.ok(sigWebCrypto.length >= 40);

        // Verify LAN HTTP fallback via window.sha256.hmac.arrayBuffer when crypto.subtle is absent
        globalThis.window = {
            sha256: Object.assign(() => '', {
                hmac: {
                    arrayBuffer: () => new Uint8Array([65, 66, 67, 255]).buffer,
                },
            }),
        };
        const sigFallback = await computeSocketSignature('tok1', 'WEB', '12345');
        assert.equal(sigFallback, 'QUJDw');
    } finally {
        globalThis.window = origWindow;
    }
});
