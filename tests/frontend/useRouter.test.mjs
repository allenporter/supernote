import assert from 'node:assert/strict';
import test from 'node:test';
import { ref } from 'vue';

import { logout, setToken } from '../../supernote/server/static/js/api/http.js';
import {
    buildCrumbsFromPathInfo,
    buildUrlHash,
    formatCrumbName,
    parseUrlHash,
    useRouter,
} from '../../supernote/server/static/js/composables/useRouter.js';

function createRouterHarness({ onOAuthRouteEnter = null, onOAuthRouteClear = null } = {}) {
    /** @type {string[]} */
    const historyStack = [''];
    let historyIdx = 0;
    /** @type {ReturnType<typeof useRouter> | null} */
    let routerRef = null;
    let pathQueries = 0;

    globalThis.window = /** @type {any} */ ({
        location: {
            origin: 'http://127.0.0.1:8080',
            get hash() {
                return historyStack[historyIdx] || '';
            },
        },
        history: {
            pushState(_state, _title, url) {
                historyStack.splice(historyIdx + 1);
                historyStack.push(String(url));
                historyIdx = historyStack.length - 1;
            },
            replaceState(_state, _title, url) {
                historyStack[historyIdx] = String(url);
            },
            back() {
                if (historyIdx > 0) {
                    historyIdx--;
                    void routerRef?.syncFromUrl();
                }
            },
        },
        addEventListener() {},
        removeEventListener() {},
    });

    globalThis.fetch = async (_url, init) => {
        pathQueries++;
        const body = JSON.parse(String(init?.body || '{}'));
        if (body.id === '99') {
            return new Response(
                JSON.stringify({
                    success: true,
                    path: '/EXPORT/Summary.note',
                    idPath: '/20/99',
                }),
                { status: 200 },
            );
        }
        if (body.id === '404') {
            return new Response(JSON.stringify({ success: true, path: '', idPath: '' }), {
                status: 200,
            });
        }
        return new Response(JSON.stringify({ success: true, path: '/INBOX', idPath: '/10' }), {
            status: 200,
        });
    };

    const isLoggedIn = ref(true);
    const files = ref(/** @type {any[]} */ ([]));
    const currentDirectoryId = ref('0');
    const loadedDirectoryId = ref(/** @type {string | null} */ (null));
    const selectedIds = ref(['stale']);

    /** @type {Record<string, Array<Record<string, any>>>} */
    const mockVfs = {
        0: [{ id: '10', name: 'INBOX', isDirectory: true }],
        10: [{ id: '55', name: 'Notes.note', isDirectory: false, extension: 'note' }],
        20: [{ id: '99', name: 'Summary.note', isDirectory: false, extension: 'note' }],
    };

    async function loadDirectory(dirId = '0') {
        const id = String(dirId);
        currentDirectoryId.value = id;
        files.value = mockVfs[id] || [];
        loadedDirectoryId.value = id;
    }

    const router = useRouter({
        isLoggedIn,
        files,
        currentDirectoryId,
        loadedDirectoryId,
        loadDirectory,
        selectedIds,
        onOAuthRouteEnter,
        onOAuthRouteClear,
    });
    routerRef = router;

    return {
        router,
        files,
        currentDirectoryId,
        selectedIds,
        historyStack,
        getPathQueries: () => pathQueries,
    };
}

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
    assert.deepEqual(parseUrlHash('#/settings'), {
        tab: 'settings',
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
    assert.equal(
        buildUrlHash('files', '42', 'viewer', { id: '9001' }, false, 2),
        '#/file/9001?page=3',
    );
    assert.equal(buildUrlHash('tasks', '0', 'grid', null, false, null), '#/tasks');
    assert.equal(buildUrlHash('settings', '0', 'grid', null, false, null), '#/settings');
    assert.equal(buildUrlHash('settings', '0', 'recycle', null, false, null), '#/settings');
    assert.equal(buildUrlHash('files', '0', 'grid', null, true, null), '#/system');

    assert.equal(formatCrumbName('INBOX', 0), 'Inbox');
    assert.equal(formatCrumbName('Projects', 1), 'Projects');
    assert.deepEqual(buildCrumbsFromPathInfo({ path: '/INBOX/Specs', idPath: '/10/20' }), [
        { id: '0', name: 'Cloud' },
        { id: '10', name: 'Inbox' },
        { id: '20', name: 'Specs' },
    ]);
});

test('useRouter.js: navigates folders/files, replaces history on page scroll & system jump, and falls back on missing folder', async () => {
    const origWindow = globalThis.window;
    const origFetch = globalThis.fetch;

    try {
        setToken('router-tok');
        const { router, files, currentDirectoryId, selectedIds, historyStack, getPathQueries } =
            createRouterHarness();

        await router.syncFromUrl(true);
        router.updateUrl(true);
        assert.equal(globalThis.window.location.hash, '#/files');
        assert.equal(currentDirectoryId.value, '0');
        assert.deepEqual(selectedIds.value, []);

        await router.openItem({ id: '10', name: 'INBOX', isDirectory: true });
        assert.equal(globalThis.window.location.hash, '#/files/10');
        assert.equal(getPathQueries(), 0);
        assert.deepEqual(router.breadcrumbs.value, [
            { id: '0', name: 'Cloud' },
            { id: '10', name: 'Inbox' },
        ]);

        await router.openItem(files.value[0]);
        assert.equal(globalThis.window.location.hash, '#/file/55');
        assert.equal(router.view.value, 'viewer');
        assert.equal(router.selectedFile.value?.id, '55');
        assert.equal(getPathQueries(), 0);

        const stackLenBeforeScroll = historyStack.length;
        router.handleViewerPageChange(2);
        assert.equal(globalThis.window.location.hash, '#/file/55?page=3');
        assert.equal(historyStack.length, stackLenBeforeScroll);

        await router.closeViewer();
        assert.equal(globalThis.window.location.hash, '#/files/10');
        assert.equal(router.view.value, 'grid');
        assert.equal(router.selectedFile.value, null);

        router.openSystemPanel();
        assert.equal(globalThis.window.location.hash, '#/system');
        assert.equal(router.showSystemPanel.value, true);
        const stackLenOnSystem = historyStack.length;

        await router.openItem({ id: '99', isDirectory: false });
        assert.equal(router.showSystemPanel.value, false);
        assert.equal(globalThis.window.location.hash, '#/file/99');
        assert.equal(historyStack.length, stackLenOnSystem);
        assert.equal(currentDirectoryId.value, '20');
        assert.deepEqual(router.breadcrumbs.value, [
            { id: '0', name: 'Cloud' },
            { id: '20', name: 'Export' },
        ]);
        assert.equal(router.selectedFile.value?.name, 'Summary.note');

        globalThis.window.history.pushState(null, '', '#/files/404');
        await router.syncFromUrl();
        assert.equal(globalThis.window.location.hash, '#/files');
        assert.equal(currentDirectoryId.value, '0');
    } finally {
        await logout({ reload: false });
        globalThis.window = origWindow;
        globalThis.fetch = origFetch;
    }
});

test('useRouter.js: handles OAuth /login-bridge routes and preserves pendingOAuthRequest across resetSessionRoutes', async () => {
    const origWindow = globalThis.window;
    const origFetch = globalThis.fetch;
    let oauthEntered = 0;
    let oauthCleared = 0;

    try {
        setToken('router-oauth-tok');
        const { router } = createRouterHarness({
            onOAuthRouteEnter: () => {
                oauthEntered++;
            },
            onOAuthRouteClear: () => {
                oauthCleared++;
            },
        });

        globalThis.window.history.pushState(
            null,
            '',
            `#/login?return_to=${encodeURIComponent('/login-bridge?client_id=https%3A%2F%2Fclaude.ai%2Fcb&code_challenge=abc')}`,
        );
        await router.syncFromUrl();
        assert.equal(oauthEntered, 1);
        assert.equal(router.pendingOAuthRequest.value?.isValid, true);

        router.resetSessionRoutes();
        assert.equal(router.view.value, 'grid');
        assert.equal(router.selectedFile.value, null);
        assert.deepEqual(router.breadcrumbs.value, [{ id: '0', name: 'Cloud' }]);
        assert.equal(router.pendingOAuthRequest.value?.isValid, true);

        const clearedBefore = oauthCleared;
        await router.clearOAuthRoute();
        assert.equal(router.pendingOAuthRequest.value, null);
        assert.equal(globalThis.window.location.hash, '#/files');

        globalThis.window.history.pushState(null, '', '#/tasks');
        await router.syncFromUrl();
        assert.equal(oauthCleared, clearedBefore + 1);
        assert.equal(router.activeTab.value, 'tasks');
    } finally {
        await logout({ reload: false });
        globalThis.window = origWindow;
        globalThis.fetch = origFetch;
    }
});

test('useRouter.js: handles #/recycle deep links, openRecycleBin, and closeRecycleBin', async () => {
    const origWindow = globalThis.window;
    const origFetch = globalThis.fetch;

    try {
        assert.deepEqual(parseUrlHash('#/recycle'), {
            tab: 'files',
            view: 'recycle',
            dirId: '0',
            showSystem: false,
        });
        assert.equal(buildUrlHash('files', '10', 'recycle', null), '#/recycle');

        setToken('router-recycle-tok');
        const { router, currentDirectoryId, selectedIds } = createRouterHarness();

        await router.openItem({ id: '10', name: 'INBOX', isDirectory: true });
        assert.equal(currentDirectoryId.value, '10');

        selectedIds.value = ['55'];
        router.openRecycleBin();
        assert.equal(router.activeTab.value, 'files');
        assert.equal(router.view.value, 'recycle');
        assert.deepEqual(selectedIds.value, []);
        assert.equal(globalThis.window.location.hash, '#/recycle');

        await router.closeRecycleBin();
        assert.equal(router.view.value, 'grid');
        assert.equal(currentDirectoryId.value, '10');
        assert.equal(globalThis.window.location.hash, '#/files/10');

        globalThis.window.history.pushState(null, '', '#/recycle');
        await router.syncFromUrl();
        assert.equal(router.activeTab.value, 'files');
        assert.equal(router.view.value, 'recycle');
    } finally {
        await logout({ reload: false });
        globalThis.window = origWindow;
        globalThis.fetch = origFetch;
    }
});
