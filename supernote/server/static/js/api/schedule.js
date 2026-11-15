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
 * @returns {Promise<RawScheduleTaskGroup[]>}
 */
export async function fetchTaskGroups() {
    const data = await apiRequest('/api/file/schedule/group/all', {
        body: {},
        errorPrefix: 'Failed to fetch task groups'
    });
    return data.scheduleTaskGroup || [];
}

/**
 * Create a new task group via POST /api/file/schedule/group
 */
export function createTaskGroup(title) {
    return apiRequest('/api/file/schedule/group', {
        body: { title },
        errorPrefix: 'Failed to create task group'
    });
}

/**
 * Delete a task group via DELETE /api/file/schedule/group/{taskListId}
 */
export function deleteTaskGroup(taskListId) {
    return apiRequest(`/api/file/schedule/group/${encodeURIComponent(taskListId)}`, {
        method: 'DELETE',
        errorPrefix: 'Failed to delete task group'
    });
}

/**
 * Fetch tasks via POST /api/file/schedule/task/all (optionally filtered by taskListId).
 * @param {string | number | null} [taskListId=null]
 * @returns {Promise<{ tasks: ScheduleTask[], nextPageToken: string | null }>}
 */
export async function fetchTasks(taskListId = null) {
    const payload = taskListId ? { taskListId: String(taskListId) } : {};
    const data = await apiRequest('/api/file/schedule/task/all', {
        body: payload,
        errorPrefix: 'Failed to fetch tasks'
    });
    const rawTasks = data.scheduleTask || [];

    return {
        tasks: rawTasks.map(t => ({
            id: String(t.taskId),
            taskListId: t.taskListId ? String(t.taskListId) : null,
            title: t.title || 'Untitled Task',
            detail: t.detail || '',
            status: t.status || 'needsAction',
            importance: normalizeTaskImportance(t.importance),
            dueTime: t.dueTime || 0,
            completedTime: t.completedTime || 0,
            isReminderOn: t.isReminderOn === 'Y' || t.isReminderOn === true,
            links: t.links || null,
            sort: t.sort ?? null,
            sortCompleted: t.sortCompleted ?? null,
            planerSort: t.planerSort ?? null,
            allSort: t.allSort ?? null,
            createTime: t.createTime || 0,
            updateTime: t.lastModified || 0,
        })),
        nextPageToken: data.nextPageToken || null
    };
}

/**
 * Create a new task via POST /api/file/schedule/task
 * @param {ScheduleTaskInput} taskData
 */
export function createScheduleTask(taskData) {
    return apiRequest('/api/file/schedule/task', {
        body: {
            taskListId: taskData.taskListId ? String(taskData.taskListId) : null,
            title: taskData.title,
            detail: taskData.detail || '',
            importance: normalizeTaskImportance(taskData.importance),
            status: taskData.status || 'needsAction',
            dueTime: taskData.dueTime || 0,
            isReminderOn: taskData.isReminderOn ? 'Y' : 'N'
        },
        errorPrefix: 'Failed to create task'
    });
}

/**
 * Update an existing task via PUT /api/file/schedule/task
 * @param {ScheduleTaskInput} taskData
 */
export function updateScheduleTask(taskData) {
    const taskId = String(taskData.id || taskData.taskId);
    /** @type {Record<string, unknown>} */
    const payload = {
        taskId,
        title: taskData.title,
        detail: taskData.detail,
        importance: taskData.importance !== undefined ? normalizeTaskImportance(taskData.importance) : undefined,
        status: taskData.status,
        dueTime: taskData.dueTime,
        completedTime: taskData.completedTime,
        lastModified: taskData.lastModified || Date.now(),
        isReminderOn: taskData.isReminderOn !== undefined ? (taskData.isReminderOn ? 'Y' : 'N') : undefined
    };
    if ('taskListId' in taskData) {
        payload.taskListId = taskData.taskListId ? String(taskData.taskListId) : null;
    }

    return apiRequest('/api/file/schedule/task', {
        method: 'PUT',
        body: payload,
        errorPrefix: 'Failed to update task'
    });
}

/**
 * Delete a task via DELETE /api/file/schedule/task/{taskId}
 */
export function deleteScheduleTask(taskId) {
    return apiRequest(`/api/file/schedule/task/${encodeURIComponent(taskId)}`, {
        method: 'DELETE',
        errorPrefix: 'Failed to delete task'
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
        errorPrefix: 'Failed to fetch ICS feed'
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
