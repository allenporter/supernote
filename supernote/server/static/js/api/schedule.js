/**
 * Schedule & Task Management API Client Functions
 */
import { apiRequest } from './http.js';

/**
 * Normalize Supernote device/CLI task importance values ('high'/'1',
 * 'normal'/'medium'/'5', 'low'/'9') into canonical UI levels ('high' | 'medium' | 'low').
 * @param {unknown} importance
 * @returns {TaskImportance}
 */
export function normalizeTaskImportance(importance) {
    if (importance === null || importance === undefined) return 'low';
    const normalized = String(importance).trim().toLowerCase();
    if (normalized === 'high' || normalized === '1') return 'high';
    if (normalized === 'normal' || normalized === 'medium' || normalized === '5') return 'medium';
    return 'low';
}

/**
 * Fetch all task groups via POST /api/file/schedule/group/all
 * @returns {Promise<ScheduleTaskGroup[]>}
 */
export async function fetchTaskGroups() {
    const data = await apiRequest('/api/file/schedule/group/all', {
        body: {},
        errorPrefix: 'Failed to fetch task groups',
    });
    /** @type {Array<Record<string, any>>} */
    const rawGroups = Array.isArray(data?.scheduleTaskGroup) ? data.scheduleTaskGroup : [];
    return rawGroups.map((g) => ({
        id: String(g.taskListId),
        title: g.title || 'Untitled Group',
    }));
}

/**
 * Create a new task group via POST /api/file/schedule/group
 * @param {string} title
 * @returns {Promise<void>}
 */
export async function createTaskGroup(title) {
    await apiRequest('/api/file/schedule/group', {
        body: { title },
        errorPrefix: 'Failed to create task group',
    });
}

/**
 * Delete a task group via DELETE /api/file/schedule/group/{taskListId}
 * @param {string | number} taskListId
 * @returns {Promise<void>}
 */
export async function deleteTaskGroup(taskListId) {
    await apiRequest(`/api/file/schedule/group/${encodeURIComponent(taskListId)}`, {
        method: 'DELETE',
        errorPrefix: 'Failed to delete task group',
    });
}

/**
 * Fetch tasks via POST /api/file/schedule/task/all (optionally filtered by taskListId).
 * @param {string | number | null} [taskListId=null]
 * @returns {Promise<ScheduleTask[]>}
 */
export async function fetchTasks(taskListId = null) {
    const payload = taskListId ? { taskListId: String(taskListId) } : {};
    const data = await apiRequest('/api/file/schedule/task/all', {
        body: payload,
        errorPrefix: 'Failed to fetch tasks',
    });
    /** @type {Array<Record<string, any>>} */
    const rawTasks = Array.isArray(data?.scheduleTask) ? data.scheduleTask : [];

    return rawTasks.map((t) => ({
        id: String(t.taskId),
        taskListId: t.taskListId ? String(t.taskListId) : null,
        title: t.title || 'Untitled Task',
        detail: t.detail || '',
        status: t.status === 'completed' ? 'completed' : 'needsAction',
        importance: normalizeTaskImportance(t.importance),
        dueTime: t.dueTime || 0,
        completedTime: t.completedTime || 0,
        isReminderOn: t.isReminderOn === 'Y' || t.isReminderOn === true,
        links: typeof t.links === 'string' ? t.links : null,
        sort: t.sort ?? null,
        sortCompleted: t.sortCompleted ?? null,
        planerSort: t.planerSort ?? null,
        allSort: t.allSort ?? null,
        updateTime: t.lastModified || 0,
    }));
}

/**
 * Create a new task via POST /api/file/schedule/task
 * @param {ScheduleTaskInput} taskData
 * @returns {Promise<void>}
 */
export async function createScheduleTask(taskData) {
    await apiRequest('/api/file/schedule/task', {
        body: {
            taskListId: taskData.taskListId ? String(taskData.taskListId) : null,
            title: taskData.title,
            detail: taskData.detail || '',
            importance: normalizeTaskImportance(taskData.importance),
            status: taskData.status || 'needsAction',
            dueTime: taskData.dueTime || 0,
            isReminderOn: taskData.isReminderOn ? 'Y' : 'N',
        },
        errorPrefix: 'Failed to create task',
    });
}

/**
 * Update an existing task via PUT /api/file/schedule/task
 * @param {ScheduleTaskInput} taskData
 * @returns {Promise<void>}
 */
export async function updateScheduleTask(taskData) {
    const taskId = String(taskData.id || taskData.taskId);
    /** @type {Record<string, unknown>} */
    const payload = {
        taskId,
        title: taskData.title,
        detail: taskData.detail,
        importance:
            taskData.importance !== undefined
                ? normalizeTaskImportance(taskData.importance)
                : undefined,
        status: taskData.status,
        dueTime: taskData.dueTime,
        completedTime: taskData.completedTime,
        lastModified: taskData.lastModified || Date.now(),
        isReminderOn:
            taskData.isReminderOn !== undefined ? (taskData.isReminderOn ? 'Y' : 'N') : undefined,
    };
    if ('taskListId' in taskData) {
        payload.taskListId = taskData.taskListId ? String(taskData.taskListId) : null;
    }

    await apiRequest('/api/file/schedule/task', {
        method: 'PUT',
        body: payload,
        errorPrefix: 'Failed to update task',
    });
}

/**
 * Delete a task via DELETE /api/file/schedule/task/{taskId}
 * @param {string | number} taskId
 * @returns {Promise<void>}
 */
export async function deleteScheduleTask(taskId) {
    await apiRequest(`/api/file/schedule/task/${encodeURIComponent(taskId)}`, {
        method: 'DELETE',
        errorPrefix: 'Failed to delete task',
    });
}

/**
 * Fetch ICS calendar feed content via GET /api/schedule/feed.ics
 * @param {string | number | null} [taskListId=null]
 * @returns {Promise<string>}
 */
export function fetchIcsFeed(taskListId = null) {
    const url = taskListId
        ? `/api/schedule/feed.ics?taskListId=${encodeURIComponent(taskListId)}`
        : '/api/schedule/feed.ics';

    return apiRequest(url, {
        method: 'GET',
        responseType: 'text',
        errorPrefix: 'Failed to fetch ICS feed',
    });
}

/**
 * Trigger direct browser download of the .ics calendar file
 * @param {string | number | null} [taskListId=null]
 * @param {string} [filename='tasks.ics']
 * @returns {Promise<void>}
 */
export async function downloadIcsFeed(taskListId = null, filename = 'tasks.ics') {
    const content = await fetchIcsFeed(taskListId);
    const blob = new Blob([content], { type: 'text/calendar;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}
