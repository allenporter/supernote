import assert from 'node:assert/strict';
import test from 'node:test';

import {
    ApiError,
    apiRequest,
    getToken,
    logout,
    onLogout,
    setToken,
} from '../../supernote/server/static/js/api/http.js';

test('http.js: attaches token and JSON headers and returns text or fallbackValue', async () => {
    /** @type {Array<{ url: string, init: any }>} */
    const calls = [];
    const origFetch = globalThis.fetch;
    try {
        setToken('tok-123');
        assert.equal(getToken(), 'tok-123');

        globalThis.fetch = async (url, init) => {
            calls.push({ url: String(url), init });
            if (url === '/api/ok') {
                return new Response(JSON.stringify({ ok: true }), { status: 200 });
            }
            if (url === '/api/text') {
                return new Response('BEGIN:VCALENDAR', { status: 200 });
            }
            return new Response('Not Found', { status: 404, statusText: 'Not Found' });
        };

        assert.deepEqual(await apiRequest('/api/ok', { body: { id: '1' } }), { ok: true });
        assert.equal(calls[0].init.headers['x-access-token'], 'tok-123');
        assert.equal(calls[0].init.headers['Content-Type'], 'application/json');

        assert.equal(
            await apiRequest('/api/text', { method: 'GET', responseType: 'text' }),
            'BEGIN:VCALENDAR',
        );
        assert.deepEqual(await apiRequest('/api/missing', { fallbackValue: [] }), []);
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('http.js: 401 clears token, notifies active logout listeners, and honors unsubscribe', async () => {
    const origFetch = globalThis.fetch;
    let logoutNotified = 0;
    const unsubscribe = onLogout(() => {
        logoutNotified++;
    });
    try {
        setToken('tok-expired');
        globalThis.fetch = async () => new Response('Unauthorized', { status: 401 });

        await assert.rejects(
            () => apiRequest('/api/expired', { reloadOnUnauthorized: false }),
            (err) => err instanceof ApiError && err.status === 401,
        );
        assert.equal(getToken(), null);
        assert.equal(logoutNotified, 1);

        unsubscribe();
        setToken('tok-second');
        await logout({ reload: false });
        assert.equal(logoutNotified, 1);

        await assert.rejects(
            () => apiRequest('/api/requires-auth', { reloadOnUnauthorized: false }),
            (err) => err instanceof ApiError && err.status === 401,
        );
    } finally {
        unsubscribe();
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});
