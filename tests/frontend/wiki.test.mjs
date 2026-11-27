import assert from 'node:assert/strict';
import test from 'node:test';

import { logout, setToken } from '../../supernote/server/static/js/api/http.js';
import {
    deleteWikiPage,
    encodeSlugPath,
    fetchWikiDiagnostics,
    fetchWikiLintIssues,
    fetchWikiPage,
    fetchWikiPages,
    fetchWikiStatus,
    formatDryRunDropReason,
    formatLintTypeLabel,
    formatPageKindLabel,
    formatSourceRef,
    formatWikiActionResult,
    resolveWikiLintIssue,
    runWikiDryRun,
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

test('formatSourceRef resolves notebook filenames, 64-bit file IDs, tasks, and deleted sources', () => {
    const note = formatSourceRef({
        source_type: 'note_page',
        source_key: '780925676306825948:P1',
        // Simulate JSON.parse rounding a 64-bit integer; formatSourceRef must recover exact ID from source_key.
        file_id: Number('780925676306825948'),
        file_name: 'Aurora_Spec.note',
        page_index: 2,
        is_source_deleted: false,
    });
    assert.equal(note.label, 'Aurora_Spec.note · p.3');
    assert.equal(note.clickable, true);
    assert.equal(note.fileId, '780925676306825948');
    assert.equal(note.pageIndex, 2);

    const deletedNote = formatSourceRef({
        source_type: 'note_page',
        source_key: '101:P1',
        file_name: 'Old.note',
        page_index: 0,
        is_source_deleted: true,
    });
    assert.equal(deletedNote.clickable, false);
    assert.equal(deletedNote.label, 'Old.note · p.1');

    const task = formatSourceRef({
        source_type: 'schedule_task',
        source_key: 'task-aurora-ups',
        task_title: 'Install UPS',
        is_source_deleted: false,
    });
    assert.equal(task.label, 'Install UPS');
    assert.equal(task.clickable, true);
    assert.equal(task.taskId, 'task-aurora-ups');

    // Unresolved (missing/recycled/hallucinated) sources must not render as clickable buttons.
    const unresolvedNote = formatSourceRef({
        source_type: 'note_page',
        source_key: '999:P1',
        file_id: 999,
        is_source_deleted: false,
    });
    assert.equal(unresolvedNote.clickable, false);

    const unresolvedTask = formatSourceRef({
        source_type: 'schedule_task',
        source_key: 'missing-task',
        is_source_deleted: false,
    });
    assert.equal(unresolvedTask.clickable, false);
});

test('fetchWikiDiagnostics and runWikiDryRun unwrap payloads and send expected body', async () => {
    const origFetch = globalThis.fetch;
    /** @type {Array<{ url: string, init: RequestInit }>} */
    const calls = [];
    setToken('test-token');
    globalThis.fetch = async (url, init = {}) => {
        calls.push({ url: String(url), init });
        if (String(url) === '/api/extended/wiki/diagnostics') {
            return jsonResponse({
                success: true,
                notebooks: [
                    {
                        file_id: '1042',
                        file_name: 'Daily.note',
                        ocr_pages: 10,
                        cited_pages: 0,
                        avg_chars_per_page: 280,
                        cited_slugs: [],
                    },
                ],
            });
        }
        return jsonResponse({
            success: true,
            pages_sent: [
                {
                    source_id: 'page01',
                    file_id: '1042',
                    file_path: 'Daily.note',
                    page_index: 0,
                    page_date: '2026-04-01',
                    chars: 280,
                    snippet: 'Morning notes',
                },
            ],
            candidate_slugs: ['projects/solar'],
            ops: [],
            lint_proposals_count: 0,
            elapsed_ms: 420,
        });
    };

    try {
        const notebooks = await fetchWikiDiagnostics();
        assert.equal(notebooks.length, 1);
        assert.equal(notebooks[0].file_id, '1042');
        assert.equal(notebooks[0].cited_pages, 0);

        const report = await runWikiDryRun({
            fileId: '1042',
            startDate: '2026-04-01',
            offsetPages: 8,
            maxPages: 4,
        });
        assert.equal(report.pages_sent.length, 1);
        assert.equal(report.candidate_slugs[0], 'projects/solar');
        assert.equal(report.elapsed_ms, 420);

        assert.equal(calls.length, 2);
        assert.equal(calls[1].url, '/api/extended/wiki/diagnostics/dry-run');
        assert.equal(calls[1].init.method, 'POST');
        assert.deepEqual(JSON.parse(String(calls[1].init.body)), {
            file_id: '1042',
            start_date: '2026-04-01',
            offset_pages: 8,
            max_pages: 4,
        });
    } finally {
        globalThis.fetch = origFetch;
        logout();
    }
});

test('formatDryRunDropReason maps internal codes to plain-English explanations', () => {
    assert.equal(formatDryRunDropReason(null), '');
    assert.equal(
        formatDryRunDropReason('edit_policy:protected_prose'),
        'Skipped: human-edited page is protected',
    );
    assert.equal(formatDryRunDropReason('edit_policy:locked'), 'Skipped: page is locked');
    assert.equal(
        formatDryRunDropReason('index_auto_maintained'),
        'Skipped: index page is auto-generated',
    );
    assert.equal(
        formatDryRunDropReason('page_cap_exceeded'),
        'Skipped: per-turn page limit reached',
    );
    assert.equal(formatDryRunDropReason('custom_reason'), 'Skipped: custom_reason');
});
