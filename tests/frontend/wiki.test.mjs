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
    formatLintTypeLabel,
    formatPageKindLabel,
    formatWikiActionResult,
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

for (const { name, mode, result, expected } of [
    {
        name: 'paused compiler status',
        mode: 'backfill',
        result: { mode: 'backfill', status: 'paused' },
        expected: {
            message: 'Wiki compiler is paused — check the status banner for details.',
            type: 'error',
        },
    },
    {
        name: 'empty backfill batch',
        mode: 'backfill',
        result: { mode: 'backfill', events_processed: 0, pages_updated: 0, status: 'idle' },
        expected: {
            message: 'No remaining OCR’d notebooks to backfill.',
            type: 'info',
        },
    },
    {
        name: 'updated backfill batch with remaining notebooks',
        mode: 'backfill',
        result: {
            mode: 'backfill',
            events_processed: 5,
            pages_updated: 3,
            files_processed: ['A.note', 'B.note'],
            remaining_files: 4,
            status: 'idle',
        },
        expected: {
            message:
                'Backfilled batch — compiled 2 notebooks (3 pages updated). 4 notebooks remaining.',
            type: 'success',
        },
    },
    {
        name: 'final backfill batch completes without prompting to run again',
        mode: 'backfill',
        result: {
            mode: 'backfill',
            events_processed: 2,
            pages_updated: 1,
            files_processed: ['Final.note'],
            remaining_files: 0,
            status: 'idle',
        },
        expected: {
            message: 'Backfill complete — compiled 1 notebook (1 page updated).',
            type: 'success',
        },
    },
    {
        name: 'legacy backfill batch without remaining_files',
        mode: 'backfill',
        result: { mode: 'backfill', events_processed: 5, pages_updated: 3, status: 'idle' },
        expected: {
            message: 'Backfilled batch (3 pages updated).',
            type: 'success',
        },
    },
    {
        name: 'background backfill start',
        mode: 'backfill_start',
        result: { mode: 'backfill_start', status: 'backfilling', remaining_files: 7 },
        expected: {
            message:
                'Started background backfill (7 notebooks queued, 1 per turn). You can safely leave this tab.',
            type: 'success',
        },
    },
    {
        name: 'background backfill stop',
        mode: 'backfill_stop',
        result: { mode: 'backfill_stop', status: 'stopping', remaining_files: 5 },
        expected: {
            message: 'Stopping backfill after the current notebook finishes.',
            type: 'info',
        },
    },
    {
        name: 'background backfill reset',
        mode: 'backfill_reset',
        result: { mode: 'backfill_reset', status: 'idle', remaining_files: 9 },
        expected: {
            message: 'Backfill cursor reset — 9 notebooks ready to rebuild.',
            type: 'info',
        },
    },
    {
        name: 'up-to-date incremental compile',
        mode: 'incremental',
        result: { mode: 'incremental', events_processed: 0, pages_updated: 0, status: 'idle' },
        expected: {
            message: 'Wiki is up to date — no new notebook or task changes.',
            type: 'info',
        },
    },
    {
        name: 'updated incremental compile',
        mode: 'incremental',
        result: { mode: 'incremental', events_processed: 1, pages_updated: 1, status: 'idle' },
        expected: {
            message: 'Updated 1 page from 1 recent change.',
            type: 'success',
        },
    },
    {
        name: 'lint pass result',
        mode: 'lint',
        result: { mode: 'lint', issues: [{ issue_id: 1 }] },
        expected: {
            message: 'Wiki lint finished (1 open issue).',
            type: 'success',
        },
    },
]) {
    test(`formatWikiActionResult formats ${name}`, () => {
        assert.deepEqual(formatWikiActionResult(mode, result), expected);
    });
}

test('formatPageKindLabel and formatLintTypeLabel produce readable labels', () => {
    assert.equal(formatPageKindLabel('source_digest'), 'Source');
    assert.equal(formatPageKindLabel('project'), 'Project');
    assert.equal(formatPageKindLabel('entity'), 'Entity');
    assert.equal(formatPageKindLabel('topic'), 'Topic');
    assert.equal(formatPageKindLabel('custom'), 'custom');
    assert.equal(formatLintTypeLabel('orphan_page'), 'orphan page');
    assert.equal(formatLintTypeLabel('broken_link'), 'broken link');
});
