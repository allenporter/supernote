import { ref, computed } from 'vue';
import { getErrorMessage } from '../utils/format.js';
import { showToast } from './useToast.js';
import {
    fetchTaskGroups,
    createTaskGroup,
    deleteTaskGroup,
    fetchTasks,
    createScheduleTask,
    updateScheduleTask,
    deleteScheduleTask,
    fetchIcsFeed,
    downloadIcsFeed
} from '../api/schedule.js';

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

    async function loadGroups() {
        try {
            const groups = await fetchTaskGroups();
            taskGroups.value = groups.map(g => ({
                id: String(g.taskListId),
                title: g.title || "Untitled Group"
            }));
        } catch (e) {
            console.error("Failed to load task groups:", e);
        }
    }

    async function loadTasks() {
        isLoading.value = true;
        error.value = null;
        try {
            const { tasks: fetchedTasks } = await fetchTasks();
            tasks.value = fetchedTasks;
        } catch (e) {
            error.value = getErrorMessage(e);
        } finally {
            isLoading.value = false;
        }
    }

    /**
     * @param {ScheduleTaskInput} taskData
     */
    async function addTask(taskData) {
        try {
            await createScheduleTask(taskData);
            await loadTasks();
        } catch (e) {
            showToast(`Failed to create task: ${getErrorMessage(e)}`);
        }
    }

    /**
     * @param {ScheduleTask} task
     */
    async function toggleTaskCompleted(task) {
        const newStatus = task.status === 'completed' ? 'needsAction' : 'completed';
        const newCompletedTime = newStatus === 'completed' ? Date.now() : 0;
        try {
            await updateScheduleTask({
                ...task,
                status: newStatus,
                completedTime: newCompletedTime
            });
            task.status = newStatus;
            task.completedTime = newCompletedTime;
        } catch (e) {
            showToast(`Failed to update task: ${getErrorMessage(e)}`);
        }
    }

    /**
     * @param {ScheduleTaskInput} taskData
     */
    async function modifyTask(taskData) {
        try {
            await updateScheduleTask(taskData);
            await loadTasks();
        } catch (e) {
            showToast(`Failed to update task: ${getErrorMessage(e)}`);
        }
    }

    /**
     * @param {string | number} taskId
     */
    async function removeTask(taskId) {
        try {
            await deleteScheduleTask(taskId);
            tasks.value = tasks.value.filter(t => t.id !== String(taskId));
            return true;
        } catch (e) {
            showToast(`Failed to delete task: ${getErrorMessage(e)}`);
            return false;
        }
    }

    /**
     * @param {string} title
     */
    async function addGroup(title) {
        try {
            await createTaskGroup(title);
            await loadGroups();
        } catch (e) {
            showToast(`Failed to create group: ${getErrorMessage(e)}`);
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
            await loadGroups();
            await loadTasks();
            return true;
        } catch (e) {
            showToast(`Failed to delete group: ${getErrorMessage(e)}`);
            return false;
        }
    }

    // Filtered & Sorted Tasks COMPUTED
    const filteredTasks = computed(() => {
        const result = tasks.value.filter(task => {
            // Group Filter
            if (selectedGroupId.value !== null && String(task.taskListId) !== String(selectedGroupId.value)) {
                return false;
            }

            // Quick Filters
            if (selectedFilter.value === 'today') {
                if (!task.dueTime) return false;
                const dueMs = task.dueTime < 1e11 ? task.dueTime * 1000 : task.dueTime;
                const isToday = new Date(dueMs).toDateString() === new Date().toDateString();
                if (!isToday) return false;
            } else if (selectedFilter.value === 'high') {
                if (task.importance !== 'high') return false;
            } else if (selectedFilter.value === 'completed') {
                if (task.status !== 'completed') return false;
            }

            // Search Query
            if (searchQuery.value.trim()) {
                const query = searchQuery.value.toLowerCase();
                const titleMatch = task.title.toLowerCase().includes(query);
                const detailMatch = task.detail.toLowerCase().includes(query);
                if (!titleMatch && !detailMatch) return false;
            }

            return true;
        });

        // Sort based on current view tab & device sort indexes with robust fallbacks
        return result.sort((a, b) => {
            /** @type {number | null | undefined} */
            let valA = null;
            /** @type {number | null | undefined} */
            let valB = null;

            if (selectedFilter.value === 'completed') {
                valA = a.sortCompleted;
                valB = b.sortCompleted;
            } else if (selectedGroupId.value !== null) {
                // Group View: Sort by `sort`
                valA = a.sort;
                valB = b.sort;
            } else {
                // All Tasks View: Sort by `allSort`
                valA = a.allSort;
                valB = b.allSort;
            }

            // If both have explicit sort values, sort by index ascending
            if (valA !== null && valA !== undefined && valB !== null && valB !== undefined) {
                if (valA !== valB) return valA - valB;
            }
            // Explicitly sorted items come before unsorted (null) items
            if (valA !== null && valA !== undefined && (valB === null || valB === undefined)) {
                return -1;
            }
            if ((valA === null || valA === undefined) && valB !== null && valB !== undefined) {
                return 1;
            }

            // Fallback: Due time ascending (if present)
            if (a.dueTime && b.dueTime && a.dueTime !== b.dueTime) {
                return a.dueTime - b.dueTime;
            }

            // Fallback: Creation time descending (newest first)
            return (b.createTime || 0) - (a.createTime || 0);
        });
    });

    const openTasksCount = computed(() => tasks.value.filter(t => t.status !== 'completed').length);
    const highPriorityCount = computed(() => tasks.value.filter(t => t.importance === 'high' && t.status !== 'completed').length);

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
        fetchIcsFeed,
        downloadIcsFeed
    };
}
