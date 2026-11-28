import assert from 'node:assert/strict';
import test from 'node:test';

import { logout, setToken } from '../../supernote/server/static/js/api/http.js';
import {
    fetchTimelineDays,
    fetchTimelinePages,
} from '../../supernote/server/static/js/api/timeline.js';

test('timeline.js: fetchTimelinePages sends POST payload and normalizes response items', async () => {
    const origFetch = globalThis.fetch;
    /** @type {Record<string, any> | null} */
    let capturedBody = null;
    try {
        setToken('tl-tok');
        globalThis.fetch = async (url, init) => {
            assert.equal(url, '/api/extended/timeline/pages');
            assert.equal(init?.method, 'POST');
            capturedBody = JSON.parse(String(init?.body || '{}'));
            return new Response(
                JSON.stringify({
                    success: true,
                    items: [
                        {
                            date: '2026-03-14',
                            timestampMs: 1773496800000,
                            fileId: '1001',
                            fileName: 'Project.note',
                            pageIndex: 2,
                            pageId: 'P20260314120000',
                            sources: ['created', 'edited'],
                            isBlank: false,
                            hasFiveStar: true,
                            keywords: ['roadmap'],
                            summary: 'Planned Q2 roadmap',
                            imageUrl: 'http://localhost/api/oss/png/1001/2?sig=x',
                        },
                    ],
                    nextCursor: '1773496800000:1001:2',
                    hasMore: true,
                }),
                { status: 200 },
            );
        };

        const result = await fetchTimelinePages({
            startDate: '2026-03-14',
            endDate: '2026-03-14',
            starredOnly: true,
            tzOffsetMinutes: -480,
            limit: 20,
        });

        assert.deepEqual(capturedBody, {
            startDate: '2026-03-14',
            endDate: '2026-03-14',
            includeBlank: false,
            starredOnly: true,
            tzOffsetMinutes: -480,
            limit: 20,
            cursor: null,
        });
        assert.deepEqual(result, {
            items: [
                {
                    date: '2026-03-14',
                    timestampMs: 1773496800000,
                    fileId: '1001',
                    fileName: 'Project.note',
                    pageIndex: 2,
                    pageId: 'P20260314120000',
                    sources: ['created', 'edited'],
                    isBlank: false,
                    hasFiveStar: true,
                    keywords: ['roadmap'],
                    summary: 'Planned Q2 roadmap',
                    imageUrl: 'http://localhost/api/oss/png/1001/2?sig=x',
                },
            ],
            nextCursor: '1773496800000:1001:2',
            hasMore: true,
        });
    } finally {
        globalThis.fetch = origFetch;
        logout();
    }
});

test('timeline.js: fetchTimelineDays sends POST payload and normalizes day counts', async () => {
    const origFetch = globalThis.fetch;
    try {
        setToken('tl-tok');
        globalThis.fetch = async (url, init) => {
            assert.equal(url, '/api/extended/timeline/days');
            assert.equal(init?.method, 'POST');
            return new Response(
                JSON.stringify({
                    success: true,
                    days: [
                        {
                            date: '2026-03-14',
                            count: 3,
                            createdCount: 2,
                            editedCount: 1,
                            datedCount: 1,
                        },
                    ],
                }),
                { status: 200 },
            );
        };

        const days = await fetchTimelineDays({
            startDate: '2026-03-01',
            endDate: '2026-03-31',
            tzOffsetMinutes: 0,
        });
        assert.deepEqual(days, [
            { date: '2026-03-14', count: 3, createdCount: 2, editedCount: 1, datedCount: 1 },
        ]);
    } finally {
        globalThis.fetch = origFetch;
        logout();
    }
});
