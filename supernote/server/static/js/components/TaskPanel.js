import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue';
import { useSchedule } from '../composables/useSchedule.js';
import { showToast } from '../composables/useToast.js';
import { normalizeEpochMs } from '../utils/format.js';
import TaskSidebar from './tasks/TaskSidebar.js';
import TaskRow from './tasks/TaskRow.js';
import TaskEditorModal, { toLocalDateInputValue } from './tasks/TaskEditorModal.js';
import TaskIcsModal from './tasks/TaskIcsModal.js';

export default {
    name: 'TaskPanel',
    components: {
        TaskSidebar,
        TaskRow,
        TaskEditorModal,
        TaskIcsModal
    },
    props: ['focusTask'],
    setup(props) {
        const {
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
        } = useSchedule();

        // Modals
        const showNewTaskModal = ref(false);
        const showNewGroupModal = ref(false);
        const showIcsModal = ref(false);
        const pendingDelete = ref(null);
        const editingTask = ref(null);
        const newGroupInput = ref(null);
        const newGroupTitle = ref('');

        function handleTaskSyncEvent() {
            Promise.all([loadGroups(), loadTasks()]).catch(() => {});
        }

        function applyFocusedTask(task) {
            if (!task) return;
            selectedGroupId.value = null;
            selectedFilter.value = task.status === 'completed' ? 'completed' : 'all';
            searchQuery.value = task.title || '';
        }

        function handleKeydown(e) {
            if (e.key !== 'Escape') return;
            if (pendingDelete.value) {
                pendingDelete.value = null;
                e.preventDefault();
                e.stopImmediatePropagation();
            } else if (showNewGroupModal.value) {
                showNewGroupModal.value = false;
                e.preventDefault();
                e.stopImmediatePropagation();
            }
        }

        watch(() => props.focusTask?.seq, () => {
            applyFocusedTask(props.focusTask);
        });

        watch(showNewGroupModal, (isOpen) => {
            if (isOpen) {
                nextTick(() => newGroupInput.value?.focus());
            } else {
                newGroupTitle.value = '';
            }
        });

        onMounted(async () => {
            window.addEventListener('supernote:task-sync', handleTaskSyncEvent);
            window.addEventListener('keydown', handleKeydown);
            await Promise.all([loadGroups(), loadTasks()]);
            applyFocusedTask(props.focusTask);
        });

        onUnmounted(() => {
            window.removeEventListener('supernote:task-sync', handleTaskSyncEvent);
            window.removeEventListener('keydown', handleKeydown);
        });

        const groupNameMap = computed(() => {
            const map = {};
            taskGroups.value.forEach(g => {
                map[g.id] = g.title;
            });
            return map;
        });

        const groupTaskCounts = computed(() => {
            const counts = {};
            for (const task of tasks.value) {
                if (task.status !== 'completed' && task.taskListId !== null && task.taskListId !== undefined) {
                    const key = String(task.taskListId);
                    counts[key] = (counts[key] || 0) + 1;
                }
            }
            return counts;
        });

        const todayTasksCount = computed(() => {
            const todayStr = new Date().toDateString();
            return tasks.value.filter(t => {
                if (!t.dueTime || t.status === 'completed') return false;
                const dueMs = normalizeEpochMs(t.dueTime);
                return dueMs !== null && new Date(dueMs).toDateString() === todayStr;
            }).length;
        });

        const completedTasksCount = computed(() => {
            return tasks.value.filter(t => t.status === 'completed').length;
        });

        const defaultNewTaskDueDate = computed(() => (
            selectedFilter.value === 'today' ? toLocalDateInputValue(new Date()) : ''
        ));

        function openCreateTaskModal() {
            editingTask.value = null;
            showNewTaskModal.value = true;
        }

        function openEditTaskModal(task) {
            editingTask.value = task;
            showNewTaskModal.value = true;
        }

        async function handleSaveTask(payload) {
            if (editingTask.value) {
                await modifyTask(payload);
            } else {
                await addTask(payload);
            }
            showNewTaskModal.value = false;
        }

        async function handleCreateGroup() {
            if (!newGroupTitle.value.trim()) return;
            await addGroup(newGroupTitle.value.trim());
            newGroupTitle.value = '';
            showNewGroupModal.value = false;
        }

        function requestDeleteTask(task) {
            if (!task) return;
            pendingDelete.value = {
                type: 'task',
                id: task.id,
                title: task.title || 'this task',
                count: 0
            };
        }

        function requestDeleteGroup(group) {
            if (!group) return;
            const count = tasks.value.filter(t => String(t.taskListId) === String(group.id)).length;
            pendingDelete.value = {
                type: 'group',
                id: group.id,
                title: group.title || 'this list',
                count
            };
        }

        async function confirmDeletePending() {
            const target = pendingDelete.value;
            pendingDelete.value = null;
            if (!target) return;
            if (target.type === 'group') {
                const ok = await removeGroup(target.id);
                if (ok) showToast('Task list deleted', 'success');
            } else {
                const ok = await removeTask(target.id);
                if (ok) showToast('Task deleted', 'success');
            }
        }

        function selectFilterMode(filter) {
            selectedFilter.value = filter;
            selectedGroupId.value = null;
        }

        function selectGroup(groupId) {
            selectedGroupId.value = groupId;
            selectedFilter.value = 'all';
        }

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
            todayTasksCount,
            completedTasksCount,
            groupNameMap,
            groupTaskCounts,
            defaultNewTaskDueDate,

            // Modals
            showNewTaskModal,
            showNewGroupModal,
            showIcsModal,
            pendingDelete,
            editingTask,
            newGroupTitle,
            newGroupInput,

            // Methods
            toggleTaskCompleted,
            requestDeleteTask,
            requestDeleteGroup,
            confirmDeletePending,
            openCreateTaskModal,
            openEditTaskModal,
            handleSaveTask,
            handleCreateGroup,
            selectFilterMode,
            selectGroup
        };
    },
    template: `
    <div class="flex flex-col md:flex-row gap-6">
        <!-- Sidebar Navigation -->
        <task-sidebar
            :task-groups="taskGroups"
            :selected-filter="selectedFilter"
            :selected-group-id="selectedGroupId"
            :open-tasks-count="openTasksCount"
            :today-tasks-count="todayTasksCount"
            :high-priority-count="highPriorityCount"
            :completed-tasks-count="completedTasksCount"
            :group-task-counts="groupTaskCounts"
            @select-filter="selectFilterMode"
            @select-group="selectGroup"
            @create-group="showNewGroupModal = true"
            @delete-group="requestDeleteGroup"
            @open-ics="showIcsModal = true"
        />

        <!-- Main Tasks View -->
        <div class="flex-grow min-w-0">
            <!-- Header & Action Controls -->
            <div class="flex flex-wrap items-center justify-between gap-3 mb-5">
                <div class="relative flex-grow max-w-md">
                    <input v-model="searchQuery" type="text" placeholder="Filter tasks..." aria-label="Filter tasks"
                        class="w-full pl-9 pr-8 py-2 bg-white border border-stone-200/90 rounded-xl text-xs outline-none focus:ring-2 focus:ring-slate-900 focus:border-slate-900 transition-all shadow-sm">
                    <svg class="w-3.5 h-3.5 text-stone-500 absolute left-3 top-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
                    </svg>
                    <button v-if="searchQuery" @click="searchQuery = ''" type="button"
                        aria-label="Clear task filter" title="Clear filter"
                        class="absolute right-2.5 top-2 p-0.5 rounded text-stone-500 hover:text-slate-900 hover:bg-stone-100 transition-colors">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <div class="flex items-center gap-2">
                    <button @click="showIcsModal = true" type="button"
                        class="flex items-center gap-1.5 bg-white hover:bg-stone-50 text-slate-700 border border-stone-200/90 px-3 py-2 rounded-xl font-semibold text-xs transition-all shadow-sm"
                        title="Export Calendar Feed (.ics)">
                        <svg class="w-3.5 h-3.5 text-stone-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                        </svg>
                        ICS Feed
                    </button>
                    <button @click="openCreateTaskModal" type="button"
                        class="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-white px-3.5 py-2 rounded-xl font-semibold text-xs transition-all shadow-sm">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
                        </svg>
                        New Task
                    </button>
                </div>
            </div>

            <!-- Loading State -->
            <div v-if="isLoading" class="flex justify-center py-16">
                <div class="animate-spin rounded-full h-8 w-8 border-2 border-stone-300 border-t-slate-900"></div>
            </div>

            <!-- Empty State -->
            <div v-else-if="filteredTasks.length === 0" class="bg-white border border-stone-200/90 rounded-2xl p-12 text-center shadow-sm">
                <div class="w-11 h-11 bg-stone-100 text-stone-500 rounded-xl flex items-center justify-center mx-auto mb-3">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                    </svg>
                </div>
                <h3 class="text-sm font-bold text-slate-900 mb-1">No tasks found</h3>
                <p class="text-xs text-stone-500 mb-5">
                    <template v-if="searchQuery.trim()">No tasks match "{{ searchQuery.trim() }}". Clear the filter or create a new task.</template>
                    <template v-else>Create a new task to get started on your schedule.</template>
                </p>
                <div class="flex items-center justify-center gap-2">
                    <button v-if="searchQuery.trim()" @click="searchQuery = ''" type="button"
                        class="px-4 py-2 bg-white hover:bg-stone-50 text-slate-700 border border-stone-200 rounded-xl text-xs font-semibold transition-colors">
                        Clear Filter
                    </button>
                    <button @click="openCreateTaskModal" type="button"
                        class="inline-flex items-center gap-1.5 bg-slate-900 text-white px-4 py-2 rounded-xl text-xs font-semibold hover:bg-slate-800 transition-colors shadow-sm">
                        + New Task
                    </button>
                </div>
            </div>

            <!-- Task List -->
            <div v-else class="bg-white rounded-2xl border border-stone-200/90 shadow-sm divide-y divide-stone-100 overflow-hidden">
                <task-row
                    v-for="task in filteredTasks"
                    :key="task.id"
                    :task="task"
                    :group-name="task.taskListId ? groupNameMap[task.taskListId] : null"
                    @toggle-complete="toggleTaskCompleted"
                    @edit="openEditTaskModal"
                    @delete="requestDeleteTask"
                />
            </div>
        </div>

        <!-- New / Edit Task Modal -->
        <task-editor-modal
            v-if="showNewTaskModal"
            :task="editingTask"
            :task-groups="taskGroups"
            :default-due-date="defaultNewTaskDueDate"
            :default-group-id="selectedGroupId"
            @save="handleSaveTask"
            @close="showNewTaskModal = false"
        />

        <!-- New Group Modal -->
        <div v-if="showNewGroupModal" role="dialog" aria-modal="true" aria-label="Create Task List"
            class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px]" @click.self="showNewGroupModal = false">
            <div class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-md p-6 space-y-4 animate-fade-in">
                <h3 class="text-base font-bold text-slate-900">Create Task List</h3>
                <input ref="newGroupInput" v-model="newGroupTitle" type="text" placeholder="List name (e.g. Work, Personal)..."
                    class="w-full px-3.5 py-2.5 bg-stone-50 border border-stone-200 rounded-xl outline-none focus:ring-2 focus:ring-slate-900 text-sm mb-4"
                    @keyup.enter="handleCreateGroup">
                <div class="flex justify-end gap-2.5">
                    <button @click="showNewGroupModal = false" type="button" class="px-4 py-2 text-stone-600 hover:text-slate-900 text-xs font-semibold">Cancel</button>
                    <button @click="handleCreateGroup" :disabled="!newGroupTitle.trim()" type="button"
                        class="px-5 py-2 bg-slate-900 hover:bg-slate-800 disabled:opacity-40 text-white rounded-xl text-xs font-semibold transition-all">
                        Create List
                    </button>
                </div>
            </div>
        </div>

        <!-- In-App Task / List Delete Confirmation Modal -->
        <div v-if="pendingDelete" role="dialog" aria-modal="true" aria-label="Confirm Task Delete"
            class="fixed inset-0 z-[110] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px]" @click.self="pendingDelete = null">
            <div class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-sm p-6 animate-fade-in">
                <div class="w-10 h-10 rounded-xl bg-rose-50 text-rose-600 flex items-center justify-center mb-3">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                    </svg>
                </div>
                <h3 class="text-base font-bold text-slate-900 mb-1">
                    Delete {{ pendingDelete.type === 'group' ? 'task list' : 'task' }} "{{ pendingDelete.title }}"?
                </h3>
                <p class="text-xs text-stone-600 mb-5 leading-relaxed">
                    <template v-if="pendingDelete.type === 'group' && pendingDelete.count > 0">
                        This will permanently delete the list and all {{ pendingDelete.count }} {{ pendingDelete.count === 1 ? 'task' : 'tasks' }} inside it.
                    </template>
                    <template v-else-if="pendingDelete.type === 'group'">
                        This task list will be permanently removed.
                    </template>
                    <template v-else>
                        This task will be permanently deleted from your schedule.
                    </template>
                </p>
                <div class="flex justify-end gap-2.5">
                    <button @click="pendingDelete = null" type="button"
                        class="px-4 py-2 text-xs text-stone-600 hover:text-slate-900 font-semibold">Cancel</button>
                    <button @click="confirmDeletePending" type="button"
                        class="px-5 py-2 bg-rose-600 hover:bg-rose-700 text-white rounded-xl text-xs font-semibold transition-all">
                        Delete
                    </button>
                </div>
            </div>
        </div>

        <!-- ICS Export Modal -->
        <task-ics-modal
            v-if="showIcsModal"
            :task-groups="taskGroups"
            :initial-group-id="selectedGroupId"
            @close="showIcsModal = false"
        />
    </div>
    `
};
