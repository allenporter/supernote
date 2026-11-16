import assert from 'node:assert/strict';
import test from 'node:test';

import { logout, setToken } from '../../supernote/server/static/js/api/http.js';
import {
    fetchIcsFeed,
    fetchTaskGroups,
    fetchTasks,
    normalizeTaskImportance,
    updateScheduleTask,
} from '../../supernote/server/static/js/api/schedule.js';

test('schedule.js: normalizeTaskImportance maps numeric and string device levels', () => {
    assert.equal(normalizeTaskImportance('1'), 'high');
    assert.equal(normalizeTaskImportance('HIGH'), 'high');
    assert.equal(normalizeTaskImportance('5'), 'medium');
    assert.equal(normalizeTaskImportance('normal'), 'medium');
    assert.equal(normalizeTaskImportance('9'), 'low');
    assert.equal(normalizeTaskImportance(null), 'low');
});

test('schedule.js: maps groups/tasks, encodes feed URL, and preserves partial PUT fields', async () => {
    const origFetch = globalThis.fetch;
    /** @type {Array<{ url: string, body: any }>} */
    const puts = [];
    let lastGetUrl = '';
    try {
        setToken('sched-tok');
        globalThis.fetch = async (url, init) => {
            if (init?.method === 'PUT') {
                puts.push({ url: String(url), body: JSON.parse(String(init.body)) });
                return new Response(JSON.stringify({ success: true }), { status: 200 });
            }
            lastGetUrl = String(url);
            if (String(url).startsWith('/api/schedule/feed.ics')) {
                return new Response('BEGIN:VCALENDAR\nEND:VCALENDAR', { status: 200 });
            }
            if (url === '/api/file/schedule/group/all') {
                return new Response(
                    JSON.stringify({
                        scheduleTaskGroup: [{ taskListId: 7, title: 'Inbox' }, { taskListId: 8 }],
                    }),
                    { status: 200 },
                );
            }
            return new Response(
                JSON.stringify({
                    scheduleTask: [
                        {
                            taskId: 99,
                            taskListId: 7,
                            title: 'Review notebook',
                            importance: '1',
                            isReminderOn: 'Y',
                            lastModified: 1700000000000,
                        },
                    ],
                }),
                { status: 200 },
            );
        };

        assert.deepEqual(await fetchTaskGroups(), [
            { id: '7', title: 'Inbox' },
            { id: '8', title: 'Untitled Group' },
        ]);

        assert.deepEqual(await fetchTasks('7'), [
            {
                id: '99',
                taskListId: '7',
                title: 'Review notebook',
                detail: '',
                status: 'needsAction',
                importance: 'high',
                dueTime: 0,
                completedTime: 0,
                isReminderOn: true,
                links: null,
                sort: null,
                sortCompleted: null,
                planerSort: null,
                allSort: null,
                updateTime: 1700000000000,
            },
        ]);

        await updateScheduleTask({
            id: '99',
            status: 'completed',
            completedTime: 123,
            lastModified: 456,
        });
        assert.deepEqual(puts[0].body, {
            taskId: '99',
            status: 'completed',
            completedTime: 123,
            lastModified: 456,
        });

        const ics = await fetchIcsFeed('list a/b');
        assert.match(ics, /BEGIN:VCALENDAR/);
        assert.equal(lastGetUrl, '/api/schedule/feed.ics?taskListId=list%20a%2Fb');
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});
