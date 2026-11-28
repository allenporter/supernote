import assert from 'node:assert/strict';
import test from 'node:test';

import { logout, setToken } from '../../supernote/server/static/js/api/http.js';
import {
    getMonthCalendarMeta,
    shiftMonthKey,
    useTimeline,
} from '../../supernote/server/static/js/composables/useTimeline.js';

test('useTimeline.js: month helpers compute bounds and shift across year boundaries', () => {
    const meta = getMonthCalendarMeta('2026-02');
    assert.equal(meta.startDate, '2026-02-01');
    assert.equal(meta.endDate, '2026-02-28');
    assert.equal(meta.daysInMonth, 28);
    assert.equal(shiftMonthKey('2026-01', -1), '2025-12');
    assert.equal(shiftMonthKey('2026-12', 1), '2027-01');
});

test('useTimeline.js: loads grouped pages, paginates, toggles date filter, and resets on logout', async () => {
    const origFetch = globalThis.fetch;
    try {
        setToken('tl-tok');
        globalThis.fetch = async (url, init) => {
            const body = JSON.parse(String(init?.body || '{}'));
            if (url === '/api/extended/timeline/days') {
                return new Response(
                    JSON.stringify({
                        success: true,
                        days: [{ date: '2026-03-14', count: 2, createdCount: 1, editedCount: 1 }],
                    }),
                    { status: 200 },
                );
            }
            if (url === '/api/extended/timeline/pages') {
                if (body.cursor === 'c1') {
                    return new Response(
                        JSON.stringify({
                            success: true,
                            items: [
                                {
                                    date: '2026-03-10',
                                    timestampMs: 100,
                                    fileId: '1001',
                                    fileName: 'Alpha.note',
                                    pageIndex: 0,
                                    pageId: 'P1',
                                    sources: ['created'],
                                    isBlank: false,
                                    hasFiveStar: false,
                                    keywords: [],
                                    imageUrl: null,
                                },
                            ],
                            nextCursor: null,
                            hasMore: false,
                        }),
                        { status: 200 },
                    );
                }
                return new Response(
                    JSON.stringify({
                        success: true,
                        items: [
                            {
                                date: '2026-03-14',
                                timestampMs: 200,
                                fileId: '1001',
                                fileName: 'Alpha.note',
                                pageIndex: 1,
                                pageId: 'P2',
                                sources: ['edited'],
                                isBlank: false,
                                hasFiveStar: true,
                                keywords: ['q1'],
                                imageUrl: null,
                            },
                        ],
                        nextCursor: body.startDate ? null : 'c1',
                        hasMore: !body.startDate,
                    }),
                    { status: 200 },
                );
            }
            return new Response('{}', { status: 200 });
        };

        const tl = useTimeline();
        await tl.refreshAll();
        assert.equal(tl.groupedDays.value.length, 1);
        assert.equal(tl.groupedDays.value[0].date, '2026-03-14');
        assert.equal(tl.daysByDate.value['2026-03-14'].count, 2);
        assert.equal(tl.hasMore.value, true);

        await tl.loadMore();
        assert.deepEqual(
            tl.groupedDays.value.map((g) => g.date),
            ['2026-03-14', '2026-03-10'],
        );
        assert.equal(tl.hasMore.value, false);

        await tl.selectDate('2026-03-14');
        assert.equal(tl.selectedDate.value, '2026-03-14');
        assert.equal(tl.items.value.length, 1);

        // Clicking same date toggles off
        await tl.selectDate('2026-03-14');
        assert.equal(tl.selectedDate.value, null);

        logout();
        assert.equal(tl.items.value.length, 0);
        assert.deepEqual(tl.daysByDate.value, {});
    } finally {
        globalThis.fetch = origFetch;
        logout();
    }
});
