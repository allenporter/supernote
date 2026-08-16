/**
 * Schedule & Task Management API Client Functions
 */
import { getToken, logout } from './client.js';

function getAuthHeaders() {
    const token = getToken();
    if (!token) throw new Error("Unauthorized");
    return {
        'Content-Type': 'application/json',
        'x-access-token': token
    };
}

/**
 * Fetch all task groups via POST /api/file/schedule/group/all
 */
export async function fetchTaskGroups() {
    const response = await fetch('/api/file/schedule/group/all', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({})
    });

    if (response.status === 401) {
        logout();
        throw new Error("Unauthorized");
    }

    if (!response.ok) {
        throw new Error(`Failed to fetch task groups: ${response.statusText}`);
    }

    const data = await response.json();
    return data.scheduleTaskGroup || [];
}

/**
 * Create a new task group via POST /api/file/schedule/group
 */
export async function createTaskGroup(title) {
    const response = await fetch('/api/file/schedule/group', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ title })
    });

    if (!response.ok) {
        throw new Error(`Failed to create task group: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Delete a task group via DELETE /api/file/schedule/group/{taskListId}
 */
export async function deleteTaskGroup(taskListId) {
    const response = await fetch(`/api/file/schedule/group/${taskListId}`, {
        method: 'DELETE',
        headers: getAuthHeaders()
    });

    if (!response.ok) {
        throw new Error(`Failed to delete task group: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Fetch tasks via POST /api/file/schedule/task/all (optionally filtered by taskListId).
 */
export async function fetchTasks(taskListId = null) {
    const payload = taskListId ? { taskListId: String(taskListId) } : {};

    const response = await fetch('/api/file/schedule/task/all', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify(payload)
    });

    if (response.status === 401) {
        logout();
        throw new Error("Unauthorized");
    }

    if (!response.ok) {
        throw new Error(`Failed to fetch tasks: ${response.statusText}`);
    }

    const data = await response.json();
    const rawTasks = data.scheduleTask || [];

    return {
        tasks: rawTasks.map(t => ({
            id: String(t.taskId),
            taskListId: String(t.taskListId || "0"),
            title: t.title || "Untitled Task",
            detail: t.detail || "",
            status: t.status || "needsAction",
            importance: t.importance || "low",
            dueTime: t.dueTime || 0,
            completedTime: t.completedTime || 0,
            isReminderOn: t.isReminderOn === "Y" || t.isReminderOn === true,
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
 */
export async function createScheduleTask(taskData) {
    const response = await fetch('/api/file/schedule/task', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
            taskListId: String(taskData.taskListId || "0"),
            title: taskData.title,
            detail: taskData.detail || "",
            importance: taskData.importance || "low",
            status: taskData.status || "needsAction",
            dueTime: taskData.dueTime || 0,
            isReminderOn: taskData.isReminderOn ? "Y" : "N"
        })
    });

    if (!response.ok) {
        throw new Error(`Failed to create task: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Update an existing task via PUT /api/file/schedule/task
 */
export async function updateScheduleTask(taskData) {
    const taskId = String(taskData.id || taskData.taskId);
    const response = await fetch('/api/file/schedule/task', {
        method: 'PUT',
        headers: getAuthHeaders(),
        body: JSON.stringify({
            taskId: taskId,
            taskListId: taskData.taskListId ? String(taskData.taskListId) : undefined,
            title: taskData.title,
            detail: taskData.detail,
            importance: taskData.importance,
            status: taskData.status,
            dueTime: taskData.dueTime,
            lastModified: taskData.lastModified || Math.floor(Date.now() * 1000),
            isReminderOn: taskData.isReminderOn !== undefined ? (taskData.isReminderOn ? "Y" : "N") : undefined
        })
    });

    if (!response.ok) {
        throw new Error(`Failed to update task: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Delete a task via DELETE /api/file/schedule/task/{taskId}
 */
export async function deleteScheduleTask(taskId) {
    const response = await fetch(`/api/file/schedule/task/${taskId}`, {
        method: 'DELETE',
        headers: getAuthHeaders()
    });

    if (!response.ok) {
        throw new Error(`Failed to delete task: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Fetch ICS calendar feed content via GET /api/schedule/feed.ics
 */
export async function fetchIcsFeed(taskListId = null) {
    const headers = getAuthHeaders();
    const url = taskListId && String(taskListId) !== '0'
        ? `/api/schedule/feed.ics?taskListId=${encodeURIComponent(taskListId)}`
        : '/api/schedule/feed.ics';

    const response = await fetch(url, {
        method: 'GET',
        headers
    });

    if (response.status === 401) {
        logout();
        throw new Error("Unauthorized");
    }

    if (!response.ok) {
        throw new Error(`Failed to fetch ICS feed: ${response.statusText}`);
    }

    return await response.text();
}

/**
 * Trigger direct browser download of the .ics calendar file
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
