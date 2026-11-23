import assert from 'node:assert/strict';
import test from 'node:test';

import {
    clearRecycleBin,
    computeSocketSignature,
    connectSocket,
    createApiKey,
    deleteRecycleItems,
    disconnectSocket,
    fetchAiStatus,
    fetchApiKeys,
    fetchFiles,
    fetchOAuthGrants,
    fetchProcessingStatus,
    fetchRecycleBin,
    fetchSummaries,
    fetchSystemTasks,
    login,
    revertRecycleItems,
    revokeApiKey,
    revokeOAuthGrant,
    searchFiles,
    searchSemantic,
    submitOAuthBridgeDecision,
} from '../../supernote/server/static/js/api/client.js';
import {
    ApiError,
    getToken,
    logout,
    onLogout,
    setToken,
} from '../../supernote/server/static/js/api/http.js';

test('client.js: fetchFiles aggregates paginated userFileVOList responses', async () => {
    const origFetch = globalThis.fetch;
    /** @type {number[]} */
    const requestedPages = [];
    try {
        setToken('page-tok');
        globalThis.fetch = async (_url, init) => {
            const body = JSON.parse(String(init?.body || '{}'));
            requestedPages.push(body.pageNo);
            if (body.pageNo === 1) {
                return new Response(
                    JSON.stringify({
                        pages: 2,
                        userFileVOList: [
                            { id: '1', fileName: 'Note', isFolder: 'Y', size: 0, updateTime: 10 },
                        ],
                    }),
                    { status: 200 },
                );
            }
            return new Response(
                JSON.stringify({
                    pages: 2,
                    userFileVOList: [
                        {
                            id: '2',
                            fileName: 'Ideas.NOTE',
                            isFolder: 'N',
                            size: 2048,
                            updateTime: 20,
                        },
                    ],
                }),
                { status: 200 },
            );
        };

        const items = await fetchFiles('0', 1);
        assert.deepEqual(requestedPages, [1, 2]);
        assert.deepEqual(items, [
            {
                id: '1',
                name: 'Note',
                isDirectory: true,
                size: 0,
                updatedAt: 10,
                extension: null,
            },
            {
                id: '2',
                name: 'Ideas.NOTE',
                isDirectory: false,
                size: 2048,
                updatedAt: 20,
                extension: 'note',
            },
        ]);
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('client.js: searchFiles and searchSemantic normalize wire DTOs', async () => {
    const origFetch = globalThis.fetch;
    try {
        setToken('search-tok');
        globalThis.fetch = async (url) => {
            if (url === '/api/file/label/list/search') {
                return new Response(
                    JSON.stringify({
                        entries: [
                            {
                                id: '10',
                                name: 'Projects',
                                tag: 'folder',
                                path_display: '/Projects',
                            },
                            {
                                id: '20',
                                name: 'Spec.note',
                                tag: 'file',
                                path_display: '/Projects/Spec.note',
                                size: 4096,
                                lastUpdateTime: 1700000000000,
                            },
                        ],
                    }),
                    { status: 200 },
                );
            }
            return new Response(
                JSON.stringify({
                    results: [
                        {
                            page_id: 'p-2',
                            file_id: 20,
                            file_name: 'Spec.note',
                            page_index: 2,
                            score: 0.91,
                            text_preview: 'Architecture notes',
                            date: '2026-06-18',
                        },
                    ],
                }),
                { status: 200 },
            );
        };

        assert.deepEqual(await searchFiles('Spec'), [
            {
                id: '10',
                name: 'Projects',
                path: '/Projects',
                isDirectory: true,
                size: 0,
                updatedAt: 0,
                extension: null,
            },
            {
                id: '20',
                name: 'Spec.note',
                path: '/Projects/Spec.note',
                isDirectory: false,
                size: 4096,
                updatedAt: 1700000000000,
                extension: 'note',
            },
        ]);

        assert.deepEqual(await searchSemantic('Architecture'), [
            {
                key: 'p-2',
                fileId: '20',
                fileName: 'Spec.note',
                extension: 'note',
                pageIndex: 2,
                pageNumber: 3,
                score: 0.91,
                textPreview: 'Architecture notes',
                date: '2026-06-18',
            },
        ]);
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('client.js: fetchSummaries, fetchProcessingStatus, fetchSystemTasks, and fetchAiStatus unwrap domain envelopes', async () => {
    const origFetch = globalThis.fetch;
    try {
        setToken('ext-tok');
        globalThis.fetch = async (url) => {
            if (url === '/api/extended/file/summary/list') {
                return new Response(
                    JSON.stringify({
                        summaryDOList: [
                            { id: 1, content: 'raw ocr', dataSource: 'OCR' },
                            { id: 2, name: 'Group', isSummaryGroup: 'Y' },
                            {
                                id: 3,
                                name: 'Weekly Digest',
                                content: '## Highlights',
                                dataSource: 'gemini-2.5-flash',
                            },
                        ],
                    }),
                    { status: 200 },
                );
            }
            if (url === '/api/extended/file/processing/status') {
                return new Response(JSON.stringify({ statusMap: { 20: 'COMPLETED' } }), {
                    status: 200,
                });
            }
            if (url === '/api/extended/system/tasks') {
                return new Response(
                    JSON.stringify({
                        tasks: [
                            {
                                id: 't1',
                                fileId: '20',
                                taskType: 'OCR',
                                key: 'page_0',
                                status: 'COMPLETED',
                                retryCount: 0,
                                updateTime: 1000,
                                lastError: null,
                            },
                        ],
                    }),
                    { status: 200 },
                );
            }
            return new Response(JSON.stringify({ ocrEnabled: true, model: 'gemini' }), {
                status: 200,
            });
        };

        assert.deepEqual(await fetchSummaries('20'), [
            {
                id: '3',
                name: 'Weekly Digest',
                content: '## Highlights',
                dataSource: 'gemini-2.5-flash',
            },
        ]);
        assert.deepEqual(await fetchProcessingStatus(['20']), { 20: 'COMPLETED' });
        assert.deepEqual(await fetchSystemTasks(), [
            {
                id: 't1',
                fileId: '20',
                taskType: 'OCR',
                key: 'page_0',
                status: 'COMPLETED',
                retryCount: 0,
                updateTime: 1000,
                lastError: null,
            },
        ]);
        assert.deepEqual(await fetchAiStatus(), {
            hasApiKey: false,
            ocrEnabled: true,
            ocrModel: null,
            summaryEnabled: false,
            summaryModel: null,
            vectorSearchEnabled: false,
            embeddingModel: null,
            model: 'gemini',
        });
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('client.js: login surfaces HTTP 429 lockout errorMsg from random-code challenge', async () => {
    const origFetch = globalThis.fetch;
    try {
        globalThis.fetch = async (url) => {
            if (url === '/api/official/user/query/random/code') {
                return new Response(
                    JSON.stringify({ errorMsg: 'Too many login attempts. Try again in 60s.' }),
                    { status: 429 },
                );
            }
            return new Response('{}', { status: 200 });
        };

        await assert.rejects(
            () => login('user@example.com', 'secret'),
            (err) => err instanceof ApiError && err.status === 429 && /Too many/.test(err.message),
        );
    } finally {
        globalThis.fetch = origFetch;
    }
});

test('client.js: submitOAuthBridgeDecision sends JSON Accept + token headers and handles 400/401 without reload', async () => {
    const origFetch = globalThis.fetch;
    const origWindow = globalThis.window;
    let reloaded = false;
    let logoutCalled = 0;
    const unsub = onLogout(() => {
        logoutCalled++;
    });

    try {
        globalThis.window = /** @type {any} */ ({
            location: {
                reload() {
                    reloaded = true;
                },
            },
        });
        setToken('oauth-tok');

        /** @type {Array<{ url: string, init: any }>} */
        const calls = [];
        globalThis.fetch = async (url, init) => {
            calls.push({ url: String(url), init });
            if (String(url).includes('case=ok')) {
                return new Response(
                    JSON.stringify({ redirect_url: 'https://claude.ai/cb?code=123' }),
                    { status: 200 },
                );
            }
            if (String(url).includes('case=bad')) {
                return new Response(
                    JSON.stringify({
                        error: 'invalid_scope',
                        error_description: 'Unsupported scope',
                    }),
                    { status: 400 },
                );
            }
            if (String(url).includes('case=expired')) {
                return new Response('Unauthorized', { status: 401 });
            }
            return new Response('{}', { status: 200 });
        };

        assert.equal(
            await submitOAuthBridgeDecision('/login-bridge?case=ok', 'approve'),
            'https://claude.ai/cb?code=123',
        );
        assert.equal(calls[0].init.headers['x-access-token'], 'oauth-tok');
        assert.equal(calls[0].init.headers.Accept, 'application/json');

        await assert.rejects(
            () => submitOAuthBridgeDecision('/login-bridge?case=bad', 'approve'),
            (err) =>
                err instanceof ApiError &&
                err.status === 400 &&
                err.message === 'Unsupported scope',
        );

        await assert.rejects(
            () => submitOAuthBridgeDecision('/login-bridge?case=expired', 'deny'),
            (err) => err instanceof ApiError && err.status === 401,
        );
        assert.equal(getToken(), null);
        assert.equal(logoutCalled, 1);
        assert.equal(reloaded, false);
    } finally {
        unsub();
        await logout({ reload: false });
        globalThis.fetch = origFetch;
        globalThis.window = origWindow;
    }
});

test('client.js: computeSocketSignature supports Web Crypto and plain-HTTP LAN fallback', async () => {
    const origWindow = globalThis.window;
    try {
        globalThis.window = /** @type {any} */ ({ crypto: globalThis.crypto });
        const sigWeb = await computeSocketSignature('tok1', 'WEB', '12345');
        assert.match(sigWeb, /^[A-Za-z0-9]{40,}$/);

        globalThis.window = /** @type {any} */ ({
            sha256: Object.assign(() => '', {
                hmac: { arrayBuffer: () => new Uint8Array([65, 66, 67, 255]).buffer },
            }),
        });
        assert.equal(await computeSocketSignature('tok1', 'WEB', '12345'), 'QUJDw');
    } finally {
        globalThis.window = origWindow;
    }
});

test('client.js: connectSocket guards logout/concurrent races and dispatches parsed sync events', async () => {
    const origWindow = globalThis.window;
    let ioCalls = 0;
    /** @type {(() => void) | null} */
    let releaseSign = null;
    /** @type {Record<string, (data: unknown) => void>} */
    const handlers = {};
    /** @type {Array<{ type: string, detail: any }>} */
    const dispatched = [];

    try {
        setToken('sock-tok');
        globalThis.window = /** @type {any} */ ({
            crypto: {
                subtle: {
                    async importKey() {
                        return {};
                    },
                    sign() {
                        return new Promise((resolve) => {
                            releaseSign = () => resolve(new Uint8Array([1, 2, 3, 4]).buffer);
                        });
                    },
                },
            },
            dispatchEvent(evt) {
                dispatched.push({ type: evt.type, detail: evt.detail });
                return true;
            },
            io() {
                ioCalls++;
                return {
                    connected: true,
                    on(evt, cb) {
                        handlers[evt] = cb;
                        return this;
                    },
                    emit() {
                        return this;
                    },
                    disconnect() {
                        this.connected = false;
                    },
                };
            },
        });

        const aborted = connectSocket();
        await Promise.resolve();
        await logout({ reload: false });
        releaseSign?.();
        assert.equal(await aborted, null);
        assert.equal(ioCalls, 0);

        setToken('sock-tok-2');
        const p1 = connectSocket();
        const p2 = connectSocket();
        await Promise.resolve();
        releaseSign?.();
        const [s1, s2] = await Promise.all([p1, p2]);
        assert.equal(s1, s2);
        assert.equal(ioCalls, 1);

        handlers.ServerMessage?.(JSON.stringify({ data: [{ id: '1' }] }));
        handlers['to-do']?.({ taskId: '9' });
        handlers.digest?.('{"fileId":"2"}');
        assert.deepEqual(dispatched, [
            { type: 'supernote:file-sync', detail: { data: [{ id: '1' }] } },
            { type: 'supernote:task-sync', detail: { taskId: '9' } },
            { type: 'supernote:digest-sync', detail: { fileId: '2' } },
        ]);

        handlers.ServerMessage?.({ code: 403 });
        assert.equal(s1?.connected, false);
    } finally {
        disconnectSocket();
        await logout({ reload: false });
        globalThis.window = origWindow;
    }
});

test('client.js: recycle bin endpoints paginate, normalize, and pass string IDs', async () => {
    const origFetch = globalThis.fetch;
    /** @type {Array<{ url: string, body: any }>} */
    const calls = [];
    try {
        setToken('recycle-tok');
        globalThis.fetch = async (url, init) => {
            const body = JSON.parse(String(init?.body || '{}'));
            calls.push({ url: String(url), body });
            if (url === '/api/file/recycle/list/query') {
                if (body.pageNo === 1) {
                    return new Response(
                        JSON.stringify({
                            success: true,
                            total: 2,
                            recycleFileVOList: [
                                {
                                    fileId: '900719925474099301',
                                    isFolder: 'Y',
                                    fileName: 'OldFolder',
                                    size: 0,
                                    updateTime: '1700000000000',
                                },
                            ],
                        }),
                        { status: 200 },
                    );
                }
                return new Response(
                    JSON.stringify({
                        success: true,
                        total: 2,
                        recycleFileVOList: [
                            {
                                fileId: '900719925474099302',
                                isFolder: 'N',
                                fileName: 'Draft.note',
                                size: 4096,
                                updateTime: '1700000100000',
                            },
                        ],
                    }),
                    { status: 200 },
                );
            }
            return new Response(JSON.stringify({ success: true }), { status: 200 });
        };

        const items = await fetchRecycleBin(1);
        assert.deepEqual(items, [
            {
                id: '900719925474099301',
                name: 'OldFolder',
                isDirectory: true,
                size: 0,
                deletedAt: 1700000000000,
                extension: null,
            },
            {
                id: '900719925474099302',
                name: 'Draft.note',
                isDirectory: false,
                size: 4096,
                deletedAt: 1700000100000,
                extension: 'note',
            },
        ]);

        await revertRecycleItems(['900719925474099302']);
        await deleteRecycleItems(['900719925474099301']);
        await clearRecycleBin();

        assert.deepEqual(calls.slice(2), [
            { url: '/api/file/recycle/revert', body: { idList: ['900719925474099302'] } },
            { url: '/api/file/recycle/delete', body: { idList: ['900719925474099301'] } },
            { url: '/api/file/recycle/clear', body: {} },
        ]);
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('client.js: OAuth grant and API key helpers unwrap envelopes and send DELETE by id', async () => {
    const origFetch = globalThis.fetch;
    /** @type {Array<[string, string, unknown]>} */
    const calls = [];
    const grant = {
        id: 'g1',
        clientId: 'https://client.example.com/',
        scopes: ['supernote:all'],
        createdAt: 1700000000,
        expiresAt: 1702592000,
        lastUsedAt: null,
    };
    const apiKey = {
        id: 'k1',
        name: 'Laptop CLI',
        keyPrefix: 'sn_01234567...',
        createdAt: 1700000000,
        lastUsedAt: null,
        expiresAt: null,
    };
    try {
        setToken('settings-tok');
        globalThis.fetch = async (url, init) => {
            const method = init?.method || 'GET';
            calls.push([String(url), method, init?.body ? JSON.parse(String(init.body)) : null]);
            if (url === '/api/extended/oauth/grants') {
                return new Response(JSON.stringify({ success: true, grants: [grant] }));
            }
            if (url === '/api/extended/keys' && method === 'GET') {
                return new Response(JSON.stringify({ success: true, keys: [apiKey] }));
            }
            if (url === '/api/extended/keys' && method === 'POST') {
                return new Response(
                    JSON.stringify({
                        success: true,
                        errorCode: null,
                        id: 'k2',
                        name: 'Laptop CLI',
                        key: 'sn_0123456789abcdef0123456789abcdef',
                        createdAt: 1700000100,
                        expiresAt: 1702592100,
                    }),
                );
            }
            return new Response(JSON.stringify({ success: true }));
        };

        assert.deepEqual(await fetchOAuthGrants(), [grant]);
        assert.deepEqual(await fetchApiKeys(), [apiKey]);
        assert.deepEqual(await createApiKey('Laptop CLI', 30), {
            id: 'k2',
            name: 'Laptop CLI',
            key: 'sn_0123456789abcdef0123456789abcdef',
            createdAt: 1700000100,
            expiresAt: 1702592100,
        });
        await revokeOAuthGrant('g1');
        await revokeApiKey('k/2');

        assert.deepEqual(calls, [
            ['/api/extended/oauth/grants', 'GET', null],
            ['/api/extended/keys', 'GET', null],
            ['/api/extended/keys', 'POST', { name: 'Laptop CLI', expiresInDays: 30 }],
            ['/api/extended/oauth/grants/g1', 'DELETE', null],
            ['/api/extended/keys/k%2F2', 'DELETE', null],
        ]);
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('client.js: revokeOAuthGrant surfaces the server error for an unknown grant', async () => {
    const origFetch = globalThis.fetch;
    try {
        setToken('settings-tok');
        globalThis.fetch = async () =>
            new Response(JSON.stringify({ error: 'OAuth grant not found or already revoked' }), {
                status: 404,
            });
        await assert.rejects(
            revokeOAuthGrant('missing'),
            (err) =>
                err instanceof ApiError &&
                err.status === 404 &&
                err.message === 'OAuth grant not found or already revoked',
        );
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});
