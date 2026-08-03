import { ref, computed } from 'vue';
import {
    fetchTaskGroups,
    createTaskGroup,
    deleteTaskGroup,
    fetchTasks,
    createScheduleTask,
    updateScheduleTask,
    deleteScheduleTask
} from '../api/schedule.js';

export function useSchedule() {
    const taskGroups = ref([]);
    const tasks = ref([]);
    const isLoading = ref(false);
    const error = ref(null);

    // Filters
    const selectedFilter = ref('all'); // 'all', 'today', 'high', 'completed'
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
            error.value = e.message;
        } finally {
            isLoading.value = false;
        }
    }

    async function addTask(taskData) {
        try {
            await createScheduleTask(taskData);
            await loadTasks();
        } catch (e) {
            alert("Failed to create task: " + e.message);
        }
    }

    async function toggleTaskCompleted(task) {
        const newStatus = task.status === 'completed' ? 'needsAction' : 'completed';
        try {
            await updateScheduleTask({
                ...task,
                status: newStatus
            });
            task.status = newStatus;
        } catch (e) {
            alert("Failed to update task: " + e.message);
        }
    }

    async function modifyTask(taskData) {
        try {
            await updateScheduleTask(taskData);
            await loadTasks();
        } catch (e) {
            alert("Failed to update task: " + e.message);
        }
    }

    async function removeTask(taskId) {
        try {
            await deleteScheduleTask(taskId);
            tasks.value = tasks.value.filter(t => t.id !== String(taskId));
        } catch (e) {
            alert("Failed to delete task: " + e.message);
        }
    }

    async function addGroup(title) {
        try {
            await createTaskGroup(title);
            await loadGroups();
        } catch (e) {
            alert("Failed to create group: " + e.message);
        }
    }

    async function removeGroup(groupId, groupTitle = '') {
        const count = tasks.value.filter(t => String(t.taskListId) === String(groupId)).length;
        const warningText = count > 0
            ? `Are you sure you want to delete "${groupTitle || 'this group'}"?\n\n⚠️ WARNING: Deleting this group will permanently delete all ${count} task(s) inside it!`
            : `Are you sure you want to delete "${groupTitle || 'this group'}"?`;

        if (!confirm(warningText)) return;
        try {
            await deleteTaskGroup(groupId);
            if (selectedGroupId.value === String(groupId)) {
                selectedGroupId.value = null;
            }
            await loadGroups();
            await loadTasks();
        } catch (e) {
            alert("Failed to delete group: " + e.message);
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
                const now = Math.floor(Date.now() / 1000);
                const oneDaySeconds = 86400;
                if (!task.dueTime || Math.abs(task.dueTime - now) > oneDaySeconds) return false;
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
            let valA = null;
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
        removeGroup
    };
}
