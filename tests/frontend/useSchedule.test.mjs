import assert from 'node:assert/strict';
import test from 'node:test';

import { logout, setToken } from '../../supernote/server/static/js/api/http.js';
import {
    parseLocalDateInputToEpochMs,
    toLocalDateInputValue,
} from '../../supernote/server/static/js/components/tasks/TaskEditorModal.js';
import {
    compareScheduleTasks,
    useSchedule,
} from '../../supernote/server/static/js/composables/useSchedule.js';
import { clearToasts } from '../../supernote/server/static/js/composables/useToast.js';

test('useSchedule.js: compareScheduleTasks enforces strict weak ordering across view modes', () => {
    const taskDatedLate = /** @type {any} */ ({
        id: 'a',
        dueTime: 200000,
        updateTime: 10000,
        allSort: null,
        sort: 2,
        sortCompleted: 5,
    });
    const taskUndated = /** @type {any} */ ({
        id: 'b',
        dueTime: 0,
        updateTime: 20000,
        allSort: null,
        sort: 1,
        sortCompleted: null,
    });
    const taskDatedEarly = /** @type {any} */ ({
        id: 'c',
        dueTime: 100000,
        updateTime: 30000,
        allSort: null,
        sort: null,
        sortCompleted: 1,
    });

    assert.deepEqual(
        [taskUndated, taskDatedLate, taskDatedEarly]
            .sort((x, y) => compareScheduleTasks(x, y, 'all', null))
            .map((t) => t.id),
        ['c', 'a', 'b'],
    );
    assert.deepEqual(
        [taskDatedLate, taskUndated, taskDatedEarly]
            .sort((x, y) => compareScheduleTasks(x, y, 'all', 'group-1'))
            .map((t) => t.id),
        ['b', 'a', 'c'],
    );
    assert.deepEqual(
        [taskUndated, taskDatedLate, taskDatedEarly]
            .sort((x, y) => compareScheduleTasks(x, y, 'completed', null))
            .map((t) => t.id),
        ['c', 'a', 'b'],
    );
});

test('useSchedule.js: filteredTasks aligns open-only today/high filters with badge counts and searchQuery', async () => {
    const origFetch = globalThis.fetch;
    try {
        setToken('sched-filter-tok');
        const todayEpoch = parseLocalDateInputToEpochMs(toLocalDateInputValue(new Date()));
        globalThis.fetch = async () =>
            new Response(
                JSON.stringify({
                    scheduleTask: [
                        {
                            taskId: 't-open',
                            taskListId: 'g1',
                            title: 'Open High Today',
                            detail: 'Sprint review',
                            status: 'needsAction',
                            importance: 'high',
                            dueTime: todayEpoch,
                        },
                        {
                            taskId: 't-done',
                            taskListId: 'g1',
                            title: 'Done Task',
                            status: 'completed',
                            importance: 'high',
                            dueTime: todayEpoch,
                        },
                    ],
                }),
                { status: 200 },
            );

        const sched = useSchedule();
        await sched.loadTasks();
        assert.equal(sched.openTasksCount.value, 1);
        assert.equal(sched.highPriorityCount.value, 1);

        sched.selectedFilter.value = 'today';
        assert.deepEqual(
            sched.filteredTasks.value.map((t) => t.id),
            ['t-open'],
        );

        sched.selectedFilter.value = 'high';
        assert.deepEqual(
            sched.filteredTasks.value.map((t) => t.id),
            ['t-open'],
        );

        sched.selectedFilter.value = 'completed';
        assert.deepEqual(
            sched.filteredTasks.value.map((t) => t.id),
            ['t-done'],
        );

        sched.selectedFilter.value = 'all';
        sched.searchQuery.value = 'sprint';
        assert.deepEqual(
            sched.filteredTasks.value.map((t) => t.id),
            ['t-open'],
        );
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('useSchedule.js: returns boolean mutation status and deduplicates in-flight toggleTaskCompleted with minimal PUT', async () => {
    const origFetch = globalThis.fetch;
    const origDateNow = Date.now;
    try {
        Date.now = () => 1710000000000;
        setToken('sched-mut-tok');
        /** @type {any[]} */
        const putBodies = [];
        let failCreate = false;
        /** @type {(() => void) | null} */
        let releasePut = null;

        globalThis.fetch = async (url, init) => {
            if (url === '/api/file/schedule/task' && init?.method === 'POST') {
                if (failCreate) {
                    return new Response(JSON.stringify({ errorMsg: 'Quota exceeded' }), {
                        status: 400,
                    });
                }
                return new Response(JSON.stringify({ success: true }), { status: 200 });
            }
            if (url === '/api/file/schedule/task' && init?.method === 'PUT') {
                putBodies.push(JSON.parse(String(init.body)));
                return new Promise((resolve) => {
                    releasePut = () =>
                        resolve(new Response(JSON.stringify({ success: true }), { status: 200 }));
                });
            }
            return new Response(
                JSON.stringify({
                    scheduleTask: [
                        {
                            taskId: 't-done',
                            taskListId: 'g1',
                            title: null,
                            status: 'completed',
                            importance: 'high',
                            dueTime: 0,
                        },
                    ],
                }),
                { status: 200 },
            );
        };

        const sched = useSchedule();
        await sched.loadTasks();

        failCreate = true;
        assert.equal(await sched.addTask({ title: 'Draft' }), false);
        failCreate = false;
        assert.equal(await sched.addTask({ title: 'Saved' }), true);

        const untitledTask = sched.tasks.value[0];
        const firstToggle = sched.toggleTaskCompleted(untitledTask);
        assert.equal(await sched.toggleTaskCompleted(untitledTask), false);
        releasePut?.();
        assert.equal(await firstToggle, true);

        assert.deepEqual(putBodies, [
            {
                taskId: 't-done',
                status: 'needsAction',
                completedTime: 0,
                lastModified: 1710000000000,
            },
        ]);
    } finally {
        Date.now = origDateNow;
        clearToasts();
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});
