import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue';
import { useSchedule } from '../composables/useSchedule.js';
import { showToast } from '../composables/useToast.js';
import { normalizeEpochMs } from '../utils/format.js';

export default {
    name: 'TaskPanel',
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
            removeGroup,
            fetchIcsFeed,
            downloadIcsFeed
        } = useSchedule();

        // Modals
        const showNewTaskModal = ref(false);
        const showNewGroupModal = ref(false);
        const showIcsModal = ref(false);
        const pendingDelete = ref(null);
        const editingTask = ref(null);
        const taskTitleInput = ref(null);
        const newGroupInput = ref(null);

        // ICS Export State
        const icsFilterGroupId = ref('all');
        const icsPreviewContent = ref('');
        const isIcsLoading = ref(false);
        const copySuccess = ref(false);

        // Form Fields
        const newGroupTitle = ref('');
        const taskForm = ref({
            id: null,
            taskListId: null,
            title: '',
            detail: '',
            importance: 'low',
            dueDate: '', // YYYY-MM-DD
            status: 'needsAction'
        });

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
                e.stopPropagation();
            } else if (showNewTaskModal.value) {
                showNewTaskModal.value = false;
                e.preventDefault();
                e.stopPropagation();
            } else if (showNewGroupModal.value) {
                showNewGroupModal.value = false;
                e.preventDefault();
                e.stopPropagation();
            } else if (showIcsModal.value) {
                showIcsModal.value = false;
                e.preventDefault();
                e.stopPropagation();
            }
        }

        watch(() => props.focusTask?.seq, () => {
            applyFocusedTask(props.focusTask);
        });

        watch(showNewTaskModal, (isOpen) => {
            if (isOpen) {
                nextTick(() => taskTitleInput.value?.focus());
            }
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

        async function openIcsModal() {
            showIcsModal.value = true;
            icsFilterGroupId.value = selectedGroupId.value ? String(selectedGroupId.value) : 'all';
            await refreshIcsPreview();
        }

        async function refreshIcsPreview() {
            isIcsLoading.value = true;
            try {
                const targetGroupId = icsFilterGroupId.value === 'all' ? null : icsFilterGroupId.value;
                icsPreviewContent.value = await fetchIcsFeed(targetGroupId);
            } catch (e) {
                icsPreviewContent.value = "Error loading ICS feed: " + e.message;
            } finally {
                isIcsLoading.value = false;
            }
        }

        async function handleDownloadIcs() {
            try {
                const targetGroupId = icsFilterGroupId.value === 'all' ? null : icsFilterGroupId.value;
                const groupObj = taskGroups.value.find(g => String(g.id) === String(targetGroupId));
                const nameSlug = groupObj ? groupObj.title.toLowerCase().replace(/[^a-z0-9]/g, '_') : 'supernote_tasks';
                await downloadIcsFeed(targetGroupId, `${nameSlug}.ics`);
            } catch (e) {
                showToast("Failed to download ICS feed: " + e.message);
            }
        }

        async function copyIcsContent() {
            if (!icsPreviewContent.value) return;
            try {
                await navigator.clipboard.writeText(icsPreviewContent.value);
                copySuccess.value = true;
                setTimeout(() => { copySuccess.value = false; }, 2500);
            } catch (e) {
                showToast("Failed to copy to clipboard");
            }
        }

        // Group Name Map
        const groupNameMap = computed(() => {
            const map = {};
            taskGroups.value.forEach(g => {
                map[g.id] = g.title;
            });
            return map;
        });

        function getTaskCountForGroup(groupId) {
            return tasks.value.filter(t => String(t.taskListId) === String(groupId) && t.status !== 'completed').length;
        }

        const todayTasksCount = computed(() => {
            const todayStr = new Date().toDateString();
            return tasks.value.filter(t => {
                if (!t.dueTime || t.status === 'completed') return false;
                const dueMs = t.dueTime < 1e11 ? t.dueTime * 1000 : t.dueTime;
                return new Date(dueMs).toDateString() === todayStr;
            }).length;
        });

        const completedTasksCount = computed(() => {
            return tasks.value.filter(t => t.status === 'completed').length;
        });

        function toLocalDateInputValue(dateObj) {
            const year = dateObj.getFullYear();
            const month = String(dateObj.getMonth() + 1).padStart(2, '0');
            const day = String(dateObj.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        }

        function openCreateTaskModal() {
            editingTask.value = null;
            const defaultDueDate = selectedFilter.value === 'today'
                ? toLocalDateInputValue(new Date())
                : '';
            taskForm.value = {
                id: null,
                taskListId: selectedGroupId.value ? String(selectedGroupId.value) : null,
                title: '',
                detail: '',
                importance: 'low',
                dueDate: defaultDueDate,
                status: 'needsAction'
            };
            showNewTaskModal.value = true;
        }

        function openEditTaskModal(task) {
            editingTask.value = task;
            let formattedDate = '';
            if (task.dueTime) {
                const dueMs = task.dueTime < 1e11 ? task.dueTime * 1000 : task.dueTime;
                const dateObj = new Date(dueMs);
                formattedDate = toLocalDateInputValue(dateObj);
            }

            taskForm.value = {
                id: task.id,
                taskListId: task.taskListId ? String(task.taskListId) : null,
                title: task.title,
                detail: task.detail || '',
                importance: task.importance || 'low',
                dueDate: formattedDate,
                status: task.status || 'needsAction'
            };
            showNewTaskModal.value = true;
        }

        async function handleSaveTask() {
            if (!taskForm.value.title.trim()) return;

            let epochDue = 0;
            if (taskForm.value.dueDate) {
                const parsedDate = new Date(taskForm.value.dueDate + 'T12:00:00Z');
                epochDue = parsedDate.getTime();
            }

            const payload = {
                id: taskForm.value.id,
                taskListId: taskForm.value.taskListId,
                title: taskForm.value.title.trim(),
                detail: taskForm.value.detail.trim(),
                importance: taskForm.value.importance,
                dueTime: epochDue,
                status: taskForm.value.status
            };

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

        function getDueMeta(task) {
            if (!task || !task.dueTime) return null;
            const dueMs = normalizeEpochMs(task.dueTime);
            if (dueMs === null) return null;
            const due = new Date(dueMs);
            if (Number.isNaN(due.getTime())) return null;

            const now = new Date();
            const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
            const tomorrowStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1).getTime();
            const dueDayStart = new Date(due.getFullYear(), due.getMonth(), due.getDate()).getTime();

            if (task.status !== 'completed' && dueDayStart < todayStart) {
                const shortDate = due.toLocaleDateString(undefined, {
                    month: 'short',
                    day: 'numeric',
                    ...(due.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {})
                });
                return {
                    label: `Overdue · ${shortDate}`,
                    classes: 'bg-rose-50 text-rose-700 border-rose-200 font-semibold'
                };
            }

            if (dueDayStart === todayStart) {
                return {
                    label: 'Due Today',
                    classes: task.status === 'completed'
                        ? 'bg-stone-50 text-stone-500 border-stone-200'
                        : 'bg-emerald-50 text-emerald-700 border-emerald-200 font-semibold'
                };
            }

            if (dueDayStart === tomorrowStart) {
                return {
                    label: 'Due Tomorrow',
                    classes: task.status === 'completed'
                        ? 'bg-stone-50 text-stone-500 border-stone-200'
                        : 'bg-amber-50 text-amber-700 border-amber-200 font-semibold'
                };
            }

            return {
                label: due.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }),
                classes: 'bg-stone-50 text-stone-500 border-stone-200'
            };
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
            getTaskCountForGroup,

            // Modals & ICS
            showNewTaskModal,
            showNewGroupModal,
            showIcsModal,
            pendingDelete,
            icsFilterGroupId,
            icsPreviewContent,
            isIcsLoading,
            copySuccess,
            editingTask,
            taskForm,
            newGroupTitle,
            taskTitleInput,
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
            getDueMeta,
            selectFilterMode,
            selectGroup,
            openIcsModal,
            refreshIcsPreview,
            handleDownloadIcs,
            copyIcsContent
        };
    },
    template: `
    <div class="flex flex-col md:flex-row gap-6">
        <!-- Sidebar Navigation -->
        <aside class="w-full md:w-64 flex-shrink-0">
            <div class="bg-white rounded-2xl border border-stone-200/90 shadow-sm p-4 space-y-5">
                <!-- Views / Filters -->
                <div>
                    <h3 class="text-[11px] font-bold text-stone-500 uppercase tracking-wider px-2.5 mb-2">Views</h3>
                    <nav class="space-y-1">
                        <button @click="selectFilterMode('all')" type="button"
                            :class="selectedFilter === 'all' && selectedGroupId === null ? 'bg-slate-900 text-white font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                            class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors">
                            <span class="flex items-center gap-2.5">
                                <svg class="w-4 h-4 opacity-80" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"></path>
                                </svg>
                                All Tasks
                            </span>
                            <span :class="selectedFilter === 'all' && selectedGroupId === null ? 'bg-white/20 text-white' : 'bg-stone-100 text-stone-600'"
                                class="text-[11px] font-mono px-2 py-0.5 rounded-md tabular-nums">{{ openTasksCount }}</span>
                        </button>

                        <button @click="selectFilterMode('today')" type="button"
                            :class="selectedFilter === 'today' ? 'bg-slate-900 text-white font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                            class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors">
                            <span class="flex items-center gap-2.5">
                                <svg class="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                                </svg>
                                Due Today
                            </span>
                            <span :class="selectedFilter === 'today' ? 'bg-white/20 text-white' : 'bg-stone-100 text-stone-600'"
                                class="text-[11px] font-mono px-2 py-0.5 rounded-md tabular-nums">{{ todayTasksCount }}</span>
                        </button>

                        <button @click="selectFilterMode('high')" type="button"
                            :class="selectedFilter === 'high' ? 'bg-slate-900 text-white font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                            class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors">
                            <span class="flex items-center gap-2.5">
                                <svg class="w-4 h-4 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
                                </svg>
                                High Priority
                            </span>
                            <span :class="selectedFilter === 'high' ? 'bg-white/20 text-white' : 'bg-rose-50 text-rose-700 font-bold'"
                                class="text-[11px] font-mono px-2 py-0.5 rounded-md tabular-nums">{{ highPriorityCount }}</span>
                        </button>

                        <button @click="selectFilterMode('completed')" type="button"
                            :class="selectedFilter === 'completed' ? 'bg-slate-900 text-white font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                            class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors">
                            <span class="flex items-center gap-2.5">
                                <svg class="w-4 h-4 text-stone-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                                </svg>
                                Completed
                            </span>
                            <span :class="selectedFilter === 'completed' ? 'bg-white/20 text-white' : 'bg-stone-100 text-stone-600'"
                                class="text-[11px] font-mono px-2 py-0.5 rounded-md tabular-nums">{{ completedTasksCount }}</span>
                        </button>
                    </nav>
                </div>

                <!-- Task Groups -->
                <div class="border-t border-stone-100 pt-4">
                    <div class="flex items-center justify-between px-2.5 mb-2">
                        <h3 class="text-[11px] font-bold text-stone-500 uppercase tracking-wider">Task Lists</h3>
                        <button @click="showNewGroupModal = true" type="button"
                            class="text-slate-900 hover:text-stone-600 text-xs font-semibold flex items-center gap-1">
                            + New
                        </button>
                    </div>
                    <nav class="space-y-1">
                        <div v-for="group in taskGroups" :key="group.id" class="group flex items-center justify-between">
                            <button @click="selectGroup(group.id)" type="button"
                                :class="selectedGroupId === group.id ? 'bg-stone-200/80 text-slate-900 font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                                class="flex-grow flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors text-left truncate">
                                <span class="truncate">{{ group.title }}</span>
                                <span class="text-[11px] font-mono px-2 py-0.5 rounded-md bg-stone-100 text-stone-600 ml-2 tabular-nums">{{ getTaskCountForGroup(group.id) }}</span>
                            </button>
                            <button @click.stop="requestDeleteGroup(group)" type="button"
                                :aria-label="'Delete list ' + group.title"
                                class="hover-reveal text-stone-500 hover:text-rose-600 p-1.5 rounded-lg hover:bg-rose-50 transition-colors" title="Delete List">
                                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                                </svg>
                            </button>
                        </div>
                    </nav>
                </div>

                <!-- Export ICS Feed Sidebar Link -->
                <div class="border-t border-stone-100 pt-4">
                    <button @click="openIcsModal" type="button"
                        class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs text-stone-600 hover:text-slate-900 hover:bg-stone-100/80 transition-colors">
                        <span class="flex items-center gap-2.5 font-medium">
                            <svg class="w-4 h-4 text-stone-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
                            </svg>
                            Export .ics Feed
                        </span>
                        <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-stone-100 text-stone-600 font-semibold border border-stone-200/70">iCal</span>
                    </button>
                </div>
            </div>
        </aside>

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
                    <button @click="openIcsModal" type="button"
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
                <div v-for="task in filteredTasks" :key="task.id"
                    :class="task.status === 'completed' ? 'bg-stone-50/60 opacity-75' : 'bg-white hover:bg-stone-50/70'"
                    class="group px-4 py-3.5 transition-colors flex items-start gap-3.5">

                    <!-- Checkbox -->
                    <button @click="toggleTaskCompleted(task)" type="button"
                        :aria-label="(task.status === 'completed' ? 'Mark incomplete: ' : 'Complete: ') + task.title"
                        class="mt-0.5 flex-shrink-0 transition-transform active:scale-95">
                        <div v-if="task.status === 'completed'" class="w-4 h-4 bg-slate-900 text-white rounded flex items-center justify-center">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                            </svg>
                        </div>
                        <div v-else class="w-4 h-4 border-2 border-stone-300 hover:border-slate-900 rounded transition-colors"></div>
                    </button>

                    <!-- Content -->
                    <div class="flex-grow min-w-0">
                        <div class="flex flex-wrap items-center justify-between gap-2">
                            <h4 :class="task.status === 'completed' ? 'line-through text-stone-500' : 'text-slate-900 font-semibold'"
                                class="text-xs sm:text-sm truncate">
                                {{ task.title }}
                            </h4>

                            <!-- Badges -->
                            <div class="flex flex-wrap items-center gap-1.5 flex-shrink-0">
                                <!-- Group Tag -->
                                <span v-if="task.taskListId && groupNameMap[task.taskListId]"
                                    class="text-[11px] px-2 py-0.5 rounded-md bg-stone-100 text-stone-600 font-medium border border-stone-200/60">
                                    {{ groupNameMap[task.taskListId] }}
                                </span>

                                <!-- Priority Badge -->
                                <span v-if="task.importance === 'high'" class="text-[11px] font-mono px-2 py-0.5 rounded-md bg-rose-50 text-rose-700 font-semibold border border-rose-200/70 flex items-center gap-1">
                                    <span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span> High
                                </span>
                                <span v-else-if="task.importance === 'medium'" class="text-[11px] font-mono px-2 py-0.5 rounded-md bg-amber-50 text-amber-700 font-semibold border border-amber-200/70 flex items-center gap-1">
                                    <span class="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Medium
                                </span>
                                <span v-else class="text-[11px] font-mono px-2 py-0.5 rounded-md bg-stone-100 text-stone-600 font-medium">
                                    Low
                                </span>

                                <!-- Due Date / Overdue Chip -->
                                <span v-if="getDueMeta(task)"
                                    :class="getDueMeta(task).classes"
                                    class="text-[11px] font-mono px-2 py-0.5 rounded-md border flex items-center gap-1 tabular-nums">
                                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                                    </svg>
                                    {{ getDueMeta(task).label }}
                                </span>
                            </div>
                        </div>

                        <!-- Detail Text -->
                        <p v-if="task.detail" class="text-xs text-stone-600 line-clamp-2 mt-1">
                            {{ task.detail }}
                        </p>
                    </div>

                    <!-- Action Buttons -->
                    <div class="hover-reveal flex items-center gap-1 shrink-0">
                        <button @click="openEditTaskModal(task)" type="button"
                            :aria-label="'Edit ' + task.title"
                            class="p-1.5 text-stone-500 hover:text-slate-900 rounded-lg hover:bg-stone-100 transition-colors" title="Edit Task">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
                            </svg>
                        </button>
                        <button @click="requestDeleteTask(task)" type="button"
                            :aria-label="'Delete ' + task.title"
                            class="p-1.5 text-stone-500 hover:text-rose-600 rounded-lg hover:bg-rose-50 transition-colors" title="Delete Task">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                            </svg>
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- New / Edit Task Modal -->
        <div v-if="showNewTaskModal" role="dialog" aria-modal="true" :aria-label="editingTask ? 'Edit Task' : 'New Task'"
            class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px]" @click.self="showNewTaskModal = false">
            <div class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-lg p-6 space-y-5 animate-fade-in">
                <h3 class="text-base font-bold text-slate-900">
                    {{ editingTask ? 'Edit Task' : 'New Task' }}
                </h3>

                <div class="space-y-4">
                    <div>
                        <label class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1">Title</label>
                        <input ref="taskTitleInput" v-model="taskForm.title" type="text" placeholder="Task title..."
                            class="w-full px-3.5 py-2.5 bg-stone-50 border border-stone-200 rounded-xl outline-none focus:ring-2 focus:ring-slate-900 focus:border-slate-900 transition-all text-sm"
                            @keyup.enter="handleSaveTask">
                    </div>

                    <div>
                        <label class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1">Details</label>
                        <textarea v-model="taskForm.detail" rows="3" placeholder="Optional notes or details..."
                            class="w-full px-3.5 py-2.5 bg-stone-50 border border-stone-200 rounded-xl outline-none focus:ring-2 focus:ring-slate-900 focus:border-slate-900 transition-all text-sm"></textarea>
                    </div>

                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1">Priority</label>
                            <select v-model="taskForm.importance" class="w-full px-3 py-2.5 bg-stone-50 border border-stone-200 rounded-xl text-xs font-medium outline-none focus:ring-2 focus:ring-slate-900">
                                <option value="low">Low Priority</option>
                                <option value="medium">Medium Priority</option>
                                <option value="high">High Priority</option>
                            </select>
                        </div>

                        <div>
                            <label class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1">Task List</label>
                            <select v-model="taskForm.taskListId" class="w-full px-3 py-2.5 bg-stone-50 border border-stone-200 rounded-xl text-xs font-medium outline-none focus:ring-2 focus:ring-slate-900">
                                <option :value="null">Inbox (General)</option>
                                <option v-for="g in taskGroups" :key="g.id" :value="g.id">{{ g.title }}</option>
                            </select>
                        </div>
                    </div>

                    <div>
                        <label class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1">Due Date</label>
                        <input v-model="taskForm.dueDate" type="date"
                            class="w-full px-3.5 py-2.5 bg-stone-50 border border-stone-200 rounded-xl outline-none focus:ring-2 focus:ring-slate-900 text-xs font-mono">
                    </div>
                </div>

                <div class="flex justify-end gap-2.5 pt-3 border-t border-stone-100">
                    <button @click="showNewTaskModal = false" type="button" class="px-4 py-2 text-stone-600 hover:text-slate-900 text-xs font-semibold">
                        Cancel
                    </button>
                    <button @click="handleSaveTask" :disabled="!taskForm.title.trim()" type="button"
                        class="px-5 py-2 bg-slate-900 hover:bg-slate-800 disabled:opacity-40 text-white rounded-xl text-xs font-semibold transition-all">
                        {{ editingTask ? 'Save Changes' : 'Save Task' }}
                    </button>
                </div>
            </div>
        </div>

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
        <div v-if="showIcsModal" role="dialog" aria-modal="true" aria-label="Export iCalendar Feed"
            class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px]" @click.self="showIcsModal = false">
            <div class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-xl p-6 space-y-5 animate-fade-in">
                <div class="flex items-center justify-between border-b border-stone-100 pb-3">
                    <div class="flex items-center gap-3">
                        <div class="w-9 h-9 bg-stone-100 rounded-xl flex items-center justify-center text-slate-800">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                            </svg>
                        </div>
                        <div>
                            <h3 class="text-base font-bold text-slate-900">Export iCalendar (.ics) Feed</h3>
                            <p class="text-xs text-stone-500">Download or copy RFC 5545 VTODO task feed</p>
                        </div>
                    </div>
                    <button @click="showIcsModal = false" type="button" aria-label="Close ICS modal"
                        class="text-stone-500 hover:text-slate-900 p-1.5 rounded-lg hover:bg-stone-100 transition-colors">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <div class="space-y-4">
                    <div>
                        <label class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1.5">Filter Feed by Task List</label>
                        <select v-model="icsFilterGroupId" @change="refreshIcsPreview" class="w-full px-3.5 py-2 bg-stone-50 border border-stone-200 rounded-xl text-xs font-medium outline-none focus:ring-2 focus:ring-slate-900">
                            <option value="all">All Task Lists (Complete Feed)</option>
                            <option v-for="g in taskGroups" :key="g.id" :value="g.id">{{ g.title }}</option>
                        </select>
                    </div>

                    <div>
                        <div class="flex items-center justify-between mb-1.5">
                            <label class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider">ICS Content Preview</label>
                            <button @click="copyIcsContent" type="button" class="text-xs font-semibold text-slate-900 hover:text-stone-600 flex items-center gap-1">
                                <span v-if="copySuccess" class="text-emerald-600 flex items-center gap-1">
                                    Copied!
                                </span>
                                <span v-else class="flex items-center gap-1">
                                    Copy Text
                                </span>
                            </button>
                        </div>
                        <div v-if="isIcsLoading" class="flex justify-center items-center py-12 bg-stone-50 rounded-xl border border-stone-200">
                            <div class="animate-spin rounded-full h-6 w-6 border-2 border-stone-300 border-t-slate-900"></div>
                        </div>
                        <textarea v-else readOnly v-model="icsPreviewContent" rows="8"
                            class="w-full p-3 font-mono text-xs bg-slate-900 text-stone-200 border border-slate-800 rounded-xl outline-none resize-none leading-relaxed"></textarea>
                    </div>
                </div>

                <div class="flex items-center justify-between pt-3 border-t border-stone-100">
                    <button @click="showIcsModal = false" type="button" class="px-4 py-2 text-stone-600 hover:text-slate-900 text-xs font-semibold">
                        Close
                    </button>
                    <div class="flex items-center gap-2.5">
                        <button @click="copyIcsContent" type="button" class="px-4 py-2 bg-stone-100 hover:bg-stone-200 text-slate-800 rounded-xl text-xs font-semibold transition-colors">
                            Copy Content
                        </button>
                        <button @click="handleDownloadIcs" type="button"
                            class="px-5 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-semibold transition-all">
                            Download .ics
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    `
};
