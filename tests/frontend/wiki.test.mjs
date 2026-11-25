import assert from 'node:assert/strict';
import test from 'node:test';

import { logout, setToken } from '../../supernote/server/static/js/api/http.js';
import {
    deleteWikiPage,
    encodeSlugPath,
    fetchWikiLintIssues,
    fetchWikiPage,
    fetchWikiPages,
    fetchWikiStatus,
    resolveWikiLintIssue,
    saveWikiPage,
    searchWikiPages,
    triggerWikiCompile,
} from '../../supernote/server/static/js/api/wiki.js';

function jsonResponse(body, status = 200) {
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });
}

test('encodeSlugPath validates segments and encodes special characters', () => {
    assert.equal(encodeSlugPath('projects/q3-plan'), 'projects/q3-plan');
    assert.equal(encodeSlugPath('/projects/q3-plan/'), 'projects/q3-plan');
    assert.equal(encodeSlugPath('topics/c#?v=1'), 'topics/c%23%3Fv%3D1');

    for (const bad of ['', '   ', '/', '../status', 'a/../b', 'a/./b', 'a//b']) {
        assert.throws(() => encodeSlugPath(bad));
    }
});

test('wiki API client handles disabled 404 gracefully and fetches pages/status', async () => {
    const origFetch = globalThis.fetch;
    try {
        setToken('wiki-test-token');
        const seenUrls = [];
        globalThis.fetch = async (url) => {
            seenUrls.push(String(url));
            if (String(url).includes('/api/extended/wiki/status')) {
                return jsonResponse({ error: 'Not Found' }, 404);
            }
            if (String(url).includes('/api/extended/wiki/pages?')) {
                return jsonResponse({ pages: [{ slug: 'projects/a', title: 'A' }] });
            }
            if (String(url).includes('/api/extended/wiki/pages/projects/missing')) {
                return jsonResponse({ error: 'Not Found' }, 404);
            }
            return jsonResponse({ error: 'Unexpected' }, 500);
        };

        assert.equal(await fetchWikiStatus(), null);
        const pages = await fetchWikiPages({ pageKind: 'project', limit: 25 });
        assert.equal(pages?.length, 1);
        assert.ok(seenUrls.some((u) => u.includes('page_kind=project') && u.includes('limit=25')));
        assert.equal(await fetchWikiPage('projects/missing'), null);
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('wiki API client saves, searches, compiles, resolves lint, and deletes', async () => {
    const origFetch = globalThis.fetch;
    try {
        setToken('wiki-test-token');
        const calls = [];
        globalThis.fetch = async (url, init) => {
            calls.push({ url: String(url), method: init?.method || 'GET', body: init?.body });
            if (
                String(url).includes('/api/extended/wiki/pages/projects/a') &&
                init?.method === 'PUT'
            ) {
                return jsonResponse({ page: { slug: 'projects/a', title: 'Alpha', version: 2 } });
            }
            if (
                String(url).includes('/api/extended/wiki/pages/projects/a') &&
                init?.method === 'DELETE'
            ) {
                return jsonResponse({ deleted: true });
            }
            if (String(url).includes('/api/extended/wiki/search')) {
                return jsonResponse({ hits: [{ slug: 'projects/a', title: 'Alpha', score: 10 }] });
            }
            if (String(url).includes('/api/extended/wiki/compile')) {
                return jsonResponse({ mode: 'lint', issues: [] });
            }
            if (String(url).includes('/api/extended/wiki/lint/7/resolve')) {
                return jsonResponse({ issue: { issue_id: 7, status: 'resolved' } });
            }
            if (String(url).includes('/api/extended/wiki/lint')) {
                return jsonResponse({ issues: [{ issue_id: 7, status: 'open' }] });
            }
            return jsonResponse({ error: 'Unexpected' }, 500);
        };

        const saved = await saveWikiPage('projects/a', { title: 'Alpha', body_md: 'Body' });
        assert.equal(saved.version, 2);

        const hits = await searchWikiPages('alpha');
        assert.equal(hits[0].slug, 'projects/a');

        const compiled = await triggerWikiCompile('lint');
        assert.equal(compiled.mode, 'lint');

        const issues = await fetchWikiLintIssues('open');
        assert.equal(issues[0].issue_id, 7);

        const resolved = await resolveWikiLintIssue(7, 'resolved');
        assert.equal(resolved.status, 'resolved');

        await deleteWikiPage('projects/a');
        assert.ok(calls.some((c) => c.method === 'DELETE'));
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});
