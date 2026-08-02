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
 * Fetch all task groups.
 */
export async function fetchTaskGroups() {
    const response = await fetch('/api/schedule/groups', {
        method: 'GET',
        headers: getAuthHeaders()
    });

    if (response.status === 401) {
        logout();
        throw new Error("Unauthorized");
    }

    if (!response.ok) {
        throw new Error(`Failed to fetch task groups: ${response.statusText}`);
    }

    const data = await response.json();
    return data.schedule_task_group || data.scheduleTaskGroup || data.taskGroupList || [];
}

/**
 * Create a new task group.
 */
export async function createTaskGroup(title) {
    const response = await fetch('/api/schedule/groups', {
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
 * Delete a task group.
 */
export async function deleteTaskGroup(taskListId) {
    const response = await fetch(`/api/schedule/groups/${taskListId}`, {
        method: 'DELETE',
        headers: getAuthHeaders()
    });

    if (!response.ok) {
        throw new Error(`Failed to delete task group: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Fetch all tasks (optionally filtered by taskListId).
 */
export async function fetchTasks(taskListId = null) {
    let url = '/api/schedule/tasks';
    if (taskListId) {
        url += `?taskListId=${encodeURIComponent(taskListId)}`;
    }

    const response = await fetch(url, {
        method: 'GET',
        headers: getAuthHeaders()
    });

    if (response.status === 401) {
        logout();
        throw new Error("Unauthorized");
    }

    if (!response.ok) {
        throw new Error(`Failed to fetch tasks: ${response.statusText}`);
    }

    const data = await response.json();
    const rawTasks = data.schedule_task || data.scheduleTask || data.taskList || [];

    return {
        tasks: rawTasks.map(t => ({
            id: String(t.taskId || t.id),
            taskListId: String(t.taskListId || "0"),
            title: t.title || "Untitled Task",
            detail: t.detail || "",
            status: t.status || "needsAction",
            importance: t.importance || "low",
            dueTime: t.dueTime || 0,
            completedTime: t.completedTime || 0,
            isReminderOn: t.isReminderOn === "Y" || t.isReminderOn === true || t.isReminderOn === 1,
            links: t.links || null,
            sort: t.sort ?? null,
            sortCompleted: t.sortCompleted ?? null,
            planerSort: t.planerSort ?? null,
            allSort: t.allSort ?? null,
            createTime: t.createTime || 0,
            updateTime: t.updateTime || 0,
        })),
        nextPageToken: null
    };
}

/**
 * Create a new task.
 */
export async function createScheduleTask(taskData) {
    const response = await fetch('/api/schedule/tasks', {
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
 * Update an existing task.
 */
export async function updateScheduleTask(taskData) {
    const taskId = String(taskData.id || taskData.taskId);
    const response = await fetch(`/api/schedule/tasks/${taskId}`, {
        method: 'PUT',
        headers: getAuthHeaders(),
        body: JSON.stringify({
            taskListId: taskData.taskListId ? String(taskData.taskListId) : undefined,
            title: taskData.title,
            detail: taskData.detail,
            importance: taskData.importance,
            status: taskData.status,
            dueTime: taskData.dueTime,
            lastModified: taskData.lastModified || Math.floor(Date.now() / 1000),
            isReminderOn: taskData.isReminderOn !== undefined ? (taskData.isReminderOn ? "Y" : "N") : undefined
        })
    });

    if (!response.ok) {
        throw new Error(`Failed to update task: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Delete a task.
 */
export async function deleteScheduleTask(taskId) {
    const response = await fetch(`/api/schedule/tasks/${taskId}`, {
        method: 'DELETE',
        headers: getAuthHeaders()
    });

    if (!response.ok) {
        throw new Error(`Failed to delete task: ${response.statusText}`);
    }

    return await response.json();
}
