import { computed, ref } from 'vue';
import {
    createScheduleTask,
    createTaskGroup,
    deleteScheduleTask,
    deleteTaskGroup,
    fetchTaskGroups,
    fetchTasks,
    updateScheduleTask,
} from '../api/schedule.js';
import { getErrorMessage, normalizeEpochMs } from '../utils/format.js';
import { showToast } from './useToast.js';

/**
 * Strict weak ordering comparator for schedule tasks across filter and group views.
 * @param {ScheduleTask} a
 * @param {ScheduleTask} b
 * @param {'all' | 'today' | 'high' | 'completed'} selectedFilter
 * @param {string | null} selectedGroupId
 * @returns {number}
 */
export function compareScheduleTasks(a, b, selectedFilter, selectedGroupId) {
    /** @type {number | null | undefined} */
    let valA = null;
    /** @type {number | null | undefined} */
    let valB = null;

    if (selectedFilter === 'completed') {
        valA = a.sortCompleted;
        valB = b.sortCompleted;
    } else if (selectedGroupId !== null) {
        valA = a.sort;
        valB = b.sort;
    } else {
        valA = a.allSort;
        valB = b.allSort;
    }

    if (valA !== null && valA !== undefined && valB !== null && valB !== undefined) {
        if (valA !== valB) return valA - valB;
    } else if (valA !== null && valA !== undefined) {
        return -1;
    } else if (valB !== null && valB !== undefined) {
        return 1;
    }

    const dueA = normalizeEpochMs(a.dueTime);
    const dueB = normalizeEpochMs(b.dueTime);
    if (dueA !== null && dueB !== null && dueA !== dueB) {
        return dueA - dueB;
    }
    if ((dueA !== null) !== (dueB !== null)) {
        return dueA !== null ? -1 : 1;
    }

    const updatedA = normalizeEpochMs(a.updateTime) ?? 0;
    const updatedB = normalizeEpochMs(b.updateTime) ?? 0;
    return updatedB - updatedA;
}

export function useSchedule() {
    /** @type {import('vue').Ref<ScheduleTaskGroup[]>} */
    const taskGroups = ref([]);
    /** @type {import('vue').Ref<ScheduleTask[]>} */
    const tasks = ref([]);
    const isLoading = ref(false);
    /** @type {import('vue').Ref<string | null>} */
    const error = ref(null);

    // Filters
    /** @type {import('vue').Ref<'all' | 'today' | 'high' | 'completed'>} */
    const selectedFilter = ref('all'); // 'all', 'today', 'high', 'completed'
    /** @type {import('vue').Ref<string | null>} */
    const selectedGroupId = ref(null);
    const searchQuery = ref('');

    let activeGroupsSeq = 0;
    let activeTasksSeq = 0;
    /** @type {Set<string>} */
    const togglingTaskIds = new Set();

    async function loadGroups() {
        const seq = ++activeGroupsSeq;
        try {
            const loaded = await fetchTaskGroups();
            if (seq === activeGroupsSeq) {
                taskGroups.value = loaded;
            }
        } catch (e) {
            console.error('Failed to load task groups:', e);
        }
    }

    async function loadTasks() {
        const seq = ++activeTasksSeq;
        isLoading.value = true;
        error.value = null;
        try {
            const loaded = await fetchTasks();
            if (seq === activeTasksSeq) {
                tasks.value = loaded;
            }
        } catch (e) {
            if (seq === activeTasksSeq) {
                error.value = getErrorMessage(e);
            }
        } finally {
            if (seq === activeTasksSeq) {
                isLoading.value = false;
            }
        }
    }

    /**
     * @param {ScheduleTaskInput} taskData
     * @returns {Promise<boolean>}
     */
    async function addTask(taskData) {
        try {
            await createScheduleTask(taskData);
            await loadTasks();
            return true;
        } catch (e) {
            showToast(`Failed to create task: ${getErrorMessage(e)}`);
            return false;
        }
    }

    /**
     * @param {ScheduleTask} task
     * @returns {Promise<boolean>}
     */
    async function toggleTaskCompleted(task) {
        const taskId = String(task.id);
        if (togglingTaskIds.has(taskId)) return false;
        togglingTaskIds.add(taskId);
        const newStatus = task.status === 'completed' ? 'needsAction' : 'completed';
        const newCompletedTime = newStatus === 'completed' ? Date.now() : 0;
        try {
            await updateScheduleTask({
                id: taskId,
                status: newStatus,
                completedTime: newCompletedTime,
            });
            task.status = newStatus;
            task.completedTime = newCompletedTime;
            return true;
        } catch (e) {
            showToast(`Failed to update task: ${getErrorMessage(e)}`);
            return false;
        } finally {
            togglingTaskIds.delete(taskId);
        }
    }

    /**
     * @param {ScheduleTaskInput} taskData
     * @returns {Promise<boolean>}
     */
    async function modifyTask(taskData) {
        try {
            await updateScheduleTask(taskData);
            await loadTasks();
            return true;
        } catch (e) {
            showToast(`Failed to update task: ${getErrorMessage(e)}`);
            return false;
        }
    }

    /**
     * @param {string | number} taskId
     */
    async function removeTask(taskId) {
        try {
            await deleteScheduleTask(taskId);
            tasks.value = tasks.value.filter((t) => t.id !== String(taskId));
            return true;
        } catch (e) {
            showToast(`Failed to delete task: ${getErrorMessage(e)}`);
            return false;
        }
    }

    /**
     * @param {string} title
     * @returns {Promise<boolean>}
     */
    async function addGroup(title) {
        try {
            await createTaskGroup(title);
            await loadGroups();
            return true;
        } catch (e) {
            showToast(`Failed to create group: ${getErrorMessage(e)}`);
            return false;
        }
    }

    /**
     * @param {string | number} groupId
     */
    async function removeGroup(groupId) {
        try {
            await deleteTaskGroup(groupId);
            if (selectedGroupId.value === String(groupId)) {
                selectedGroupId.value = null;
            }
            await Promise.all([loadGroups(), loadTasks()]);
            return true;
        } catch (e) {
            showToast(`Failed to delete group: ${getErrorMessage(e)}`);
            return false;
        }
    }

    // Filtered & Sorted Tasks COMPUTED
    const filteredTasks = computed(() => {
        const todayStr = new Date().toDateString();
        const trimmedQuery = searchQuery.value.trim().toLowerCase();
        const result = tasks.value.filter((task) => {
            // Group Filter
            if (
                selectedGroupId.value !== null &&
                String(task.taskListId) !== String(selectedGroupId.value)
            ) {
                return false;
            }

            // Quick Filters (aligned with sidebar badge counts)
            if (selectedFilter.value === 'today') {
                if (!task.dueTime || task.status === 'completed') return false;
                const dueMs = normalizeEpochMs(task.dueTime);
                if (dueMs === null || new Date(dueMs).toDateString() !== todayStr) {
                    return false;
                }
            } else if (selectedFilter.value === 'high') {
                if (task.importance !== 'high' || task.status === 'completed') return false;
            } else if (selectedFilter.value === 'completed') {
                if (task.status !== 'completed') return false;
            }

            // Search Query
            if (trimmedQuery) {
                const titleMatch = task.title.toLowerCase().includes(trimmedQuery);
                const detailMatch = task.detail.toLowerCase().includes(trimmedQuery);
                if (!titleMatch && !detailMatch) return false;
            }

            return true;
        });

        return result.sort((a, b) =>
            compareScheduleTasks(a, b, selectedFilter.value, selectedGroupId.value),
        );
    });

    const openTasksCount = computed(
        () => tasks.value.filter((t) => t.status !== 'completed').length,
    );
    const highPriorityCount = computed(
        () => tasks.value.filter((t) => t.importance === 'high' && t.status !== 'completed').length,
    );

    return {
        taskGroups,
        tasks,
        filteredTasks,
        isLoading,
        error,
        selectedFilter,
        selectedGroupId,
        searchQuery,
        openTasksCount,
        highPriorityCount,
        loadGroups,
        loadTasks,
        addTask,
        toggleTaskCompleted,
        modifyTask,
        removeTask,
        addGroup,
        removeGroup,
    };
}
