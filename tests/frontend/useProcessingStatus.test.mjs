import assert from 'node:assert/strict';
import test from 'node:test';
import { ref } from 'vue';

import { logout, setToken } from '../../supernote/server/static/js/api/http.js';
import { useProcessingStatus } from '../../supernote/server/static/js/composables/useProcessingStatus.js';
import {
    loadServerFeatures,
    resetServerFeatures,
} from '../../supernote/server/static/js/composables/useServerFeatures.js';
import { mountComposable } from './helpers/vue_test_scope.mjs';

async function flushAsync() {
    await new Promise((resolve) => setImmediate(resolve));
}

test('useProcessingStatus.js: reacts to watchers, schedules 3s polls, queues force refresh in flight, and cleans up', async (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const origFetch = globalThis.fetch;
    const origWindow = globalThis.window;
    const origDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');

    /** @type {Record<string, () => void>} */
    const winListeners = {};
    /** @type {Record<string, () => void>} */
    const docListeners = {};
    /** @type {Array<(statusMap: Record<string, string>) => void>} */
    const pendingPolls = [];
    /** @type {string[][]} */
    const polledBatches = [];
    const docState = { hidden: false };

    try {
        setToken('proc-tok');
        globalThis.window = /** @type {any} */ ({
            addEventListener(type, fn) {
                winListeners[type] = fn;
            },
            removeEventListener(type) {
                delete winListeners[type];
            },
        });
        Object.defineProperty(globalThis, 'document', {
            value: {
                get hidden() {
                    return docState.hidden;
                },
                addEventListener(type, fn) {
                    docListeners[type] = fn;
                },
                removeEventListener(type) {
                    delete docListeners[type];
                },
            },
            configurable: true,
        });

        globalThis.fetch = async (url, init) => {
            if (url === '/api/user/logout') {
                return new Response('{}', { status: 200 });
            }
            const body = JSON.parse(String(init?.body || '{}'));
            polledBatches.push(body.fileIds);
            return new Promise((resolve) => {
                pendingPolls.push((statusMap) =>
                    resolve(new Response(JSON.stringify({ statusMap }), { status: 200 })),
                );
            });
        };

        const files = ref(/** @type {any[]} */ ([]));
        const isLoggedIn = ref(true);
        const activeTab = ref('files');
        const view = ref('grid');

        const { result, unmount } = await mountComposable(() =>
            useProcessingStatus({ files, isLoggedIn, activeTab, view }),
        );

        assert.equal(typeof winListeners['supernote:digest-sync'], 'function');
        assert.equal(typeof docListeners.visibilitychange, 'function');

        // Reactive `files` update polls only .note files
        files.value = [
            { id: '101', name: 'Notebook.note', extension: 'note', isDirectory: false },
            { id: '102', name: 'Slide.pdf', extension: 'pdf', isDirectory: false },
        ];
        assert.equal(pendingPolls.length, 1);
        assert.deepEqual(polledBatches[0], ['101']);

        // Pending status schedules a 3000ms follow-up poll
        pendingPolls[0]({ 101: 'PROCESSING' });
        await flushAsync();
        assert.deepEqual(result.processingStatuses.value, { 101: 'PROCESSING' });

        t.mock.timers.tick(3000);
        assert.equal(pendingPolls.length, 2);

        // Digest-sync arriving while poll #2 is in flight queues an immediate forced poll #3
        winListeners['supernote:digest-sync']();
        assert.equal(pendingPolls.length, 2);

        pendingPolls[1]({ 101: 'COMPLETED' });
        await flushAsync();
        assert.equal(pendingPolls.length, 3);

        pendingPolls[2]({ 101: 'COMPLETED' });
        await flushAsync();
        assert.deepEqual(result.processingStatuses.value, { 101: 'COMPLETED' });

        // Visibility / tab / auth transitions pause and resume polling cleanly
        docState.hidden = true;
        docListeners.visibilitychange();
        docState.hidden = false;
        docListeners.visibilitychange();
        assert.equal(pendingPolls.length, 3); // Already COMPLETED -> no extra poll

        isLoggedIn.value = false;
        result.resetProcessingStatuses();
        assert.deepEqual(result.processingStatuses.value, {});

        unmount();
        assert.equal(winListeners['supernote:digest-sync'], undefined);
        assert.equal(docListeners.visibilitychange, undefined);
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
        globalThis.window = origWindow;
        if (origDocument) {
            Object.defineProperty(globalThis, 'document', origDocument);
        } else {
            delete globalThis.document;
        }
    }
});

test('useProcessingStatus.js: skips polling when the processor component is disabled', async () => {
    const origFetch = globalThis.fetch;
    const origWindow = globalThis.window;
    const origDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
    /** @type {string[]} */
    const urls = [];

    try {
        setToken('poll-disabled-tok');
        globalThis.window = /** @type {any} */ ({
            addEventListener() {},
            removeEventListener() {},
        });
        Object.defineProperty(globalThis, 'document', {
            configurable: true,
            value: {
                hidden: false,
                addEventListener() {},
                removeEventListener() {},
            },
        });
        globalThis.fetch = async (url) => {
            const urlStr = String(url);
            urls.push(urlStr);
            if (urlStr === '/api/extended/system/features') {
                return new Response(
                    JSON.stringify({ success: true, runningComponents: ['http', 'web_ui'] }),
                );
            }
            return new Response('Not Found', { status: 404 });
        };

        await loadServerFeatures();
        urls.length = 0;

        const files = ref([{ id: '1', name: 'A.note', extension: 'note' }]);
        const isLoggedIn = ref(true);
        const activeTab = ref('files');
        const view = ref('grid');

        const { result, unmount } = await mountComposable(() =>
            useProcessingStatus({ files, isLoggedIn, activeTab, view }),
        );
        await result.refreshProcessingStatuses({ force: true });
        assert.deepEqual(urls, []);
        unmount();
    } finally {
        resetServerFeatures();
        await logout({ reload: false });
        globalThis.fetch = origFetch;
        globalThis.window = origWindow;
        if (origDocument) {
            Object.defineProperty(globalThis, 'document', origDocument);
        } else {
            delete globalThis.document;
        }
    }
});
