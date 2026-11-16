import assert from 'node:assert/strict';
import test from 'node:test';

import { compareItems } from '../../supernote/server/static/js/components/FileBrowserPanel.js';
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
