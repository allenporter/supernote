import assert from 'node:assert/strict';
import test from 'node:test';

import { logout, setToken } from '../../supernote/server/static/js/api/http.js';
import { useServerFeatures } from '../../supernote/server/static/js/composables/useServerFeatures.js';

test('useServerFeatures.js: gates tabs on running components and treats unknown state as available', async () => {
    const origFetch = globalThis.fetch;
    /** @type {string[]} */
    const calls = [];
    const {
        runningComponents,
        isComponentRunning,
        isTabAvailable,
        loadServerFeatures,
        resetServerFeatures,
    } = useServerFeatures();

    try {
        setToken('features-tok');

        // Before loading, every feature is available.
        assert.equal(runningComponents.value, null);
        assert.equal(isTabAvailable('wiki'), true);

        globalThis.fetch = async (url, init) => {
            calls.push(`${init?.method} ${url}`);
            return new Response(
                JSON.stringify({ success: true, runningComponents: ['schedule', 'search'] }),
            );
        };
        await loadServerFeatures();
        assert.deepEqual(calls, ['GET /api/extended/system/features']);
        assert.deepEqual(runningComponents.value, ['schedule', 'search']);
        assert.equal(isComponentRunning('search'), true);
        assert.equal(isComponentRunning('wiki'), false);
        assert.equal(isTabAvailable('files'), true);
        assert.equal(isTabAvailable('tasks'), true);
        assert.equal(isTabAvailable('digests'), false);
        assert.equal(isTabAvailable('wiki'), false);

        resetServerFeatures();
        assert.equal(runningComponents.value, null);
        assert.equal(isTabAvailable('wiki'), true);

        // Servers without the endpoint (404) or unreachable servers leave every feature available.
        globalThis.fetch = async () => new Response('Not Found', { status: 404 });
        await loadServerFeatures();
        assert.equal(runningComponents.value, null);

        globalThis.fetch = async () => {
            throw new TypeError('Failed to fetch');
        };
        await loadServerFeatures();
        assert.equal(runningComponents.value, null);
    } finally {
        resetServerFeatures();
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});
