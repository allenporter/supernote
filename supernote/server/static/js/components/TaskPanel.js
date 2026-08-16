import { ref, onMounted, computed } from 'vue';
import { useSchedule } from '../composables/useSchedule.js';

export default {
    name: 'TaskPanel',
    setup() {
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
        const editingTask = ref(null);

        // ICS Export State
        const icsFilterGroupId = ref('all');
        const icsPreviewContent = ref('');
        const isIcsLoading = ref(false);
        const copySuccess = ref(false);

        // Form Fields
        const newGroupTitle = ref('');
        const taskForm = ref({
            id: null,
            taskListId: '0',
            title: '',
            detail: '',
            importance: 'low',
            dueDate: '', // YYYY-MM-DD
            status: 'needsAction'
        });

        onMounted(async () => {
            await Promise.all([loadGroups(), loadTasks()]);
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
                alert("Failed to download ICS feed: " + e.message);
            }
        }

        async function copyIcsContent() {
            if (!icsPreviewContent.value) return;
            try {
                await navigator.clipboard.writeText(icsPreviewContent.value);
                copySuccess.value = true;
                setTimeout(() => { copySuccess.value = false; }, 2500);
            } catch (e) {
                alert("Failed to copy to clipboard");
            }
        }

        // Group Name Map
        const groupNameMap = computed(() => {
            const map = { '0': 'Inbox' };
            taskGroups.value.forEach(g => {
                map[g.id] = g.title;
            });
            return map;
        });

        function getTaskCountForGroup(groupId) {
            return tasks.value.filter(t => String(t.taskListId) === String(groupId) && t.status !== 'completed').length;
        }

        const todayTasksCount = computed(() => {
            const now = Math.floor(Date.now() / 1000);
            const oneDaySeconds = 86400;
            return tasks.value.filter(t => t.dueTime && Math.abs(t.dueTime - now) <= oneDaySeconds && t.status !== 'completed').length;
        });

        const completedTasksCount = computed(() => {
            return tasks.value.filter(t => t.status === 'completed').length;
        });

        function openCreateTaskModal() {
            editingTask.value = null;
            taskForm.value = {
                id: null,
                taskListId: selectedGroupId.value ? String(selectedGroupId.value) : '0',
                title: '',
                detail: '',
                importance: 'low',
                dueDate: '',
                status: 'needsAction'
            };
            showNewTaskModal.value = true;
        }

        function openEditTaskModal(task) {
            editingTask.value = task;
            let formattedDate = '';
            if (task.dueTime) {
                const dateObj = new Date(task.dueTime * 1000);
                formattedDate = dateObj.toISOString().split('T')[0];
            }

            taskForm.value = {
                id: task.id,
                taskListId: String(task.taskListId || '0'),
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
                epochDue = Math.floor(parsedDate.getTime() / 1000);
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

        function formatDueDate(dueTime) {
            if (!dueTime) return null;
            const due = new Date(dueTime * 1000);
            const now = new Date();

            const isToday = due.toDateString() === now.toDateString();
            if (isToday) return 'Due Today';

            const tomorrow = new Date(now);
            tomorrow.setDate(tomorrow.getDate() + 1);
            if (due.toDateString() === tomorrow.toDateString()) return 'Due Tomorrow';

            return due.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
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
            icsFilterGroupId,
            icsPreviewContent,
            isIcsLoading,
            copySuccess,
            editingTask,
            taskForm,
            newGroupTitle,

            // Methods
            toggleTaskCompleted,
            removeTask,
            removeGroup,
            openCreateTaskModal,
            openEditTaskModal,
            handleSaveTask,
            handleCreateGroup,
            formatDueDate,
            selectFilterMode,
            selectGroup,
            openIcsModal,
            refreshIcsPreview,
            handleDownloadIcs,
            copyIcsContent
        };
    },
    template: `
    <div class="flex flex-col md:flex-row gap-8">
        <!-- Sidebar Navigation -->
        <aside class="w-full md:w-64 flex-shrink-0">
            <div class="bg-white rounded-2xl border border-slate-200 shadow-sm p-4 space-y-6">
                <!-- Filters -->
                <div>
                    <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider px-3 mb-2">Tasks</h3>
                    <nav class="space-y-1">
                        <button @click="selectFilterMode('all')"
                            :class="selectedFilter === 'all' && selectedGroupId === null ? 'bg-indigo-50 text-indigo-700 font-semibold' : 'text-slate-600 hover:bg-slate-50'"
                            class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-sm transition-colors">
                            <span class="flex items-center gap-2.5">
                                <svg class="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"></path>
                                </svg>
                                All Tasks
                            </span>
                            <span class="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">{{ openTasksCount }}</span>
                        </button>

                        <button @click="selectFilterMode('today')"
                            :class="selectedFilter === 'today' ? 'bg-indigo-50 text-indigo-700 font-semibold' : 'text-slate-600 hover:bg-slate-50'"
                            class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-sm transition-colors">
                            <span class="flex items-center gap-2.5">
                                <svg class="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                                </svg>
                                Due Today
                            </span>
                            <span class="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">{{ todayTasksCount }}</span>
                        </button>

                        <button @click="selectFilterMode('high')"
                            :class="selectedFilter === 'high' ? 'bg-rose-50 text-rose-700 font-semibold' : 'text-slate-600 hover:bg-slate-50'"
                            class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-sm transition-colors">
                            <span class="flex items-center gap-2.5">
                                <svg class="w-4 h-4 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
                                </svg>
                                High Priority
                            </span>
                            <span class="text-xs px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 font-bold">{{ highPriorityCount }}</span>
                        </button>

                        <button @click="selectFilterMode('completed')"
                            :class="selectedFilter === 'completed' ? 'bg-slate-100 text-slate-900 font-semibold' : 'text-slate-600 hover:bg-slate-50'"
                            class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-sm transition-colors">
                            <span class="flex items-center gap-2.5">
                                <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                                </svg>
                                Completed
                            </span>
                            <span class="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">{{ completedTasksCount }}</span>
                        </button>
                    </nav>
                </div>

                <!-- Task Groups -->
                <div class="border-t border-slate-100 pt-4">
                    <div class="flex items-center justify-between px-3 mb-2">
                        <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Task Groups</h3>
                        <button @click="showNewGroupModal = true" class="text-indigo-600 hover:text-indigo-800 text-xs font-semibold flex items-center gap-1">
                            + Add
                        </button>
                    </div>
                    <nav class="space-y-1">
                        <div v-for="group in taskGroups" :key="group.id" class="group flex items-center justify-between">
                            <button @click="selectGroup(group.id)"
                                :class="selectedGroupId === group.id ? 'bg-indigo-50 text-indigo-700 font-semibold' : 'text-slate-600 hover:bg-slate-50'"
                                class="flex-grow flex items-center justify-between px-3 py-2 rounded-xl text-sm transition-colors text-left truncate">
                                <span class="truncate">{{ group.title }}</span>
                                <span class="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 ml-2">{{ getTaskCountForGroup(group.id) }}</span>
                            </button>
                            <button @click.stop="removeGroup(group.id, group.title)" class="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-rose-600 p-1.5 transition-opacity" title="Delete Group">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                                </svg>
                            </button>
                        </div>
                    </nav>
                </div>

                <!-- Export ICS Feed Sidebar Link -->
                <div class="border-t border-slate-100 pt-4">
                    <button @click="openIcsModal" class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-sm text-slate-600 hover:bg-slate-50 transition-colors">
                        <span class="flex items-center gap-2.5 font-medium">
                            <svg class="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
                            </svg>
                            Export .ics Feed
                        </span>
                        <span class="text-xs px-2 py-0.5 rounded-md bg-indigo-50 text-indigo-600 font-semibold">iCal</span>
                    </button>
                </div>
            </div>
        </aside>

        <!-- Main Tasks View -->
        <main class="flex-grow">
            <!-- Header & Action Controls -->
            <div class="flex flex-wrap items-center justify-between gap-4 mb-6">
                <div class="relative flex-grow max-w-md">
                    <input v-model="searchQuery" type="text" placeholder="Search tasks..."
                        class="w-full pl-10 pr-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all shadow-sm">
                    <svg class="w-4 h-4 text-slate-400 absolute left-3.5 top-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
                    </svg>
                </div>

                <div class="flex items-center gap-3">
                    <button @click="openIcsModal"
                        class="flex items-center gap-2 bg-white hover:bg-slate-50 text-slate-700 border border-slate-200 px-3.5 py-2.5 rounded-xl font-medium text-sm transition-all shadow-sm"
                        title="Export Calendar Feed (.ics)">
                        <svg class="w-4 h-4 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                        </svg>
                        ICS Feed
                    </button>
                    <button @click="openCreateTaskModal"
                        class="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2.5 rounded-xl font-medium text-sm transition-all shadow-lg shadow-indigo-100">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
                        </svg>
                        New Task
                    </button>
                </div>
            </div>

            <!-- Loading State -->
            <div v-if="isLoading" class="flex justify-center py-16">
                <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-indigo-600"></div>
            </div>

            <!-- Empty State -->
            <div v-else-if="filteredTasks.length === 0" class="bg-white border border-slate-200 rounded-2xl p-12 text-center shadow-sm">
                <div class="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-2xl flex items-center justify-center mx-auto mb-4">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                    </svg>
                </div>
                <h3 class="text-base font-semibold text-slate-900 mb-1">No tasks found</h3>
                <p class="text-sm text-slate-500 mb-6">Create a new task to get started on your schedule.</p>
                <button @click="openCreateTaskModal" class="inline-flex items-center gap-2 bg-indigo-600 text-white px-4 py-2 rounded-xl text-sm font-medium hover:bg-indigo-700 transition-colors shadow-lg shadow-indigo-100">
                    + New Task
                </button>
            </div>

            <!-- Task List -->
            <div v-else class="space-y-3">
                <div v-for="task in filteredTasks" :key="task.id"
                    :class="task.status === 'completed' ? 'opacity-60 bg-slate-50/70 border-slate-200' : 'bg-white border-slate-200 hover:border-indigo-200 shadow-sm hover:shadow-md'"
                    class="group rounded-2xl border p-4 transition-all flex items-start gap-4">

                    <!-- Checkbox -->
                    <button @click="toggleTaskCompleted(task)" class="mt-0.5 flex-shrink-0 transition-transform active:scale-95">
                        <div v-if="task.status === 'completed'" class="w-5 h-5 bg-indigo-600 text-white rounded-md flex items-center justify-center shadow-sm">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                            </svg>
                        </div>
                        <div v-else class="w-5 h-5 border-2 border-slate-300 hover:border-indigo-500 rounded-md transition-colors"></div>
                    </button>

                    <!-- Content -->
                    <div class="flex-grow min-w-0">
                        <div class="flex items-center justify-between gap-2 mb-1">
                            <h4 :class="task.status === 'completed' ? 'line-through text-slate-400' : 'text-slate-900 font-semibold'"
                                class="text-sm tracking-tight truncate">
                                {{ task.title }}
                            </h4>

                            <!-- Badges -->
                            <div class="flex items-center gap-2 flex-shrink-0">
                                <!-- Group Tag -->
                                <span v-if="task.taskListId !== '0' && groupNameMap[task.taskListId]"
                                    class="text-xs px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-600 font-medium border border-slate-200/60">
                                    {{ groupNameMap[task.taskListId] }}
                                </span>

                                <!-- Priority Badge -->
                                <span v-if="task.importance === 'high'" class="text-xs px-2.5 py-0.5 rounded-full bg-rose-50 text-rose-700 font-bold border border-rose-100 flex items-center gap-1">
                                    <span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span> High
                                </span>
                                <span v-else-if="task.importance === 'medium'" class="text-xs px-2.5 py-0.5 rounded-full bg-amber-50 text-amber-700 font-semibold border border-amber-100 flex items-center gap-1">
                                    <span class="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Medium
                                </span>
                                <span v-else class="text-xs px-2.5 py-0.5 rounded-full bg-sky-50 text-sky-700 font-medium border border-sky-100">
                                    Low
                                </span>

                                <!-- Due Date Chip -->
                                <span v-if="formatDueDate(task.dueTime)"
                                    :class="formatDueDate(task.dueTime) === 'Due Today' ? 'bg-emerald-50 text-emerald-700 border-emerald-100 font-semibold' : 'bg-slate-50 text-slate-500 border-slate-200'"
                                    class="text-xs px-2.5 py-0.5 rounded-full border flex items-center gap-1">
                                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                                    </svg>
                                    {{ formatDueDate(task.dueTime) }}
                                </span>
                            </div>
                        </div>

                        <!-- Detail Text -->
                        <p v-if="task.detail" class="text-xs text-slate-500 line-clamp-2 mt-0.5">
                            {{ task.detail }}
                        </p>
                    </div>

                    <!-- Action Buttons -->
                    <div class="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-opacity">
                        <button @click="openEditTaskModal(task)" class="p-1.5 text-slate-400 hover:text-indigo-600 rounded-lg hover:bg-slate-100 transition-colors" title="Edit Task">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
                            </svg>
                        </button>
                        <button @click="removeTask(task.id)" class="p-1.5 text-slate-400 hover:text-rose-600 rounded-lg hover:bg-rose-50 transition-colors" title="Delete Task">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                            </svg>
                        </button>
                    </div>
                </div>
            </div>
        </main>

        <!-- New / Edit Task Modal -->
        <div v-if="showNewTaskModal" class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm" @click.self="showNewTaskModal = false">
            <div class="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6 space-y-5 animate-in zoom-in-95">
                <h3 class="text-lg font-bold text-slate-900">
                    {{ editingTask ? 'Edit Task' : 'New Task' }}
                </h3>

                <div class="space-y-4">
                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Title</label>
                        <input v-model="taskForm.title" type="text" placeholder="Task title..."
                            class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all text-sm"
                            @keyup.enter="handleSaveTask">
                    </div>

                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Details</label>
                        <textarea v-model="taskForm.detail" rows="3" placeholder="Optional notes or details..."
                            class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all text-sm"></textarea>
                    </div>

                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Priority</label>
                            <select v-model="taskForm.importance" class="w-full px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm outline-none focus:ring-2 focus:ring-indigo-500">
                                <option value="low">Low Priority</option>
                                <option value="medium">Medium Priority</option>
                                <option value="high">High Priority</option>
                            </select>
                        </div>

                        <div>
                            <label class="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Task Group</label>
                            <select v-model="taskForm.taskListId" class="w-full px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm outline-none focus:ring-2 focus:ring-indigo-500">
                                <option value="0">Inbox (General)</option>
                                <option v-for="g in taskGroups" :key="g.id" :value="g.id">{{ g.title }}</option>
                            </select>
                        </div>
                    </div>

                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Due Date</label>
                        <input v-model="taskForm.dueDate" type="date"
                            class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-indigo-500 text-sm">
                    </div>
                </div>

                <div class="flex justify-end gap-3 pt-3 border-t border-slate-100">
                    <button @click="showNewTaskModal = false" class="px-4 py-2 text-slate-500 hover:text-slate-700 text-sm font-medium">
                        Cancel
                    </button>
                    <button @click="handleSaveTask" :disabled="!taskForm.title.trim()"
                        class="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-xl text-sm font-semibold shadow-lg shadow-indigo-100 transition-all">
                        {{ editingTask ? 'Save Changes' : 'Save Task' }}
                    </button>
                </div>
            </div>
        </div>

        <!-- New Group Modal -->
        <div v-if="showNewGroupModal" class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm" @click.self="showNewGroupModal = false">
            <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6 space-y-4 animate-in zoom-in-95">
                <h3 class="text-lg font-bold text-slate-900">Create Task Group</h3>
                <input v-model="newGroupTitle" type="text" placeholder="Group name (e.g. Projects, Personal)..."
                    class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-indigo-500 text-sm mb-4"
                    @keyup.enter="handleCreateGroup">
                <div class="flex justify-end gap-3">
                    <button @click="showNewGroupModal = false" class="px-4 py-2 text-slate-500 hover:text-slate-700 text-sm font-medium">Cancel</button>
                    <button @click="handleCreateGroup" :disabled="!newGroupTitle.trim()"
                        class="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-xl text-sm font-semibold shadow-lg shadow-indigo-100 transition-all">
                        Create Group
                    </button>
                </div>
            </div>
        </div>

        <!-- ICS Export Modal -->
        <div v-if="showIcsModal" class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm" @click.self="showIcsModal = false">
            <div class="bg-white rounded-2xl shadow-2xl w-full max-w-xl p-6 space-y-5 animate-in zoom-in-95">
                <div class="flex items-center justify-between border-b border-slate-100 pb-3">
                    <div class="flex items-center gap-3">
                        <div class="w-9 h-9 bg-indigo-50 rounded-xl flex items-center justify-center text-indigo-600">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                            </svg>
                        </div>
                        <div>
                            <h3 class="text-lg font-bold text-slate-900">Export iCalendar (.ics) Feed</h3>
                            <p class="text-xs text-slate-500">Download or copy RFC 5545 VTODO task feed</p>
                        </div>
                    </div>
                    <button @click="showIcsModal = false" class="text-slate-400 hover:text-slate-600 p-1.5 rounded-lg hover:bg-slate-100 transition-colors">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <div class="space-y-4">
                    <div>
                        <label class="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">Filter Feed by Task Group</label>
                        <select v-model="icsFilterGroupId" @change="refreshIcsPreview" class="w-full px-3.5 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm outline-none focus:ring-2 focus:ring-indigo-500">
                            <option value="all">All Task Groups (Complete Feed)</option>
                            <option v-for="g in taskGroups" :key="g.id" :value="g.id">{{ g.title }}</option>
                        </select>
                    </div>

                    <div>
                        <div class="flex items-center justify-between mb-1.5">
                            <label class="block text-xs font-semibold text-slate-700 uppercase tracking-wider">ICS Content Preview</label>
                            <button @click="copyIcsContent" class="text-xs font-semibold text-indigo-600 hover:text-indigo-800 flex items-center gap-1">
                                <span v-if="copySuccess" class="text-emerald-600 flex items-center gap-1">
                                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                                    </svg> Copied!
                                </span>
                                <span v-else class="flex items-center gap-1">
                                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"></path>
                                    </svg> Copy Text
                                </span>
                            </button>
                        </div>
                        <div v-if="isIcsLoading" class="flex justify-center items-center py-12 bg-slate-50 rounded-xl border border-slate-200">
                            <div class="animate-spin rounded-full h-7 w-7 border-b-2 border-indigo-600"></div>
                        </div>
                        <textarea v-else readOnly v-model="icsPreviewContent" rows="8"
                            class="w-full p-3 font-mono text-xs bg-slate-900 text-slate-200 border border-slate-800 rounded-xl outline-none resize-none leading-relaxed"></textarea>
                    </div>
                </div>

                <div class="flex items-center justify-between pt-3 border-t border-slate-100">
                    <button @click="showIcsModal = false" class="px-4 py-2 text-slate-500 hover:text-slate-700 text-sm font-medium">
                        Close
                    </button>
                    <div class="flex items-center gap-3">
                        <button @click="copyIcsContent" class="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-sm font-semibold transition-colors flex items-center gap-2">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path>
                            </svg>
                            Copy Content
                        </button>
                        <button @click="handleDownloadIcs"
                            class="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-sm font-semibold shadow-lg shadow-indigo-100 transition-all flex items-center gap-2">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
                            </svg>
                            Download .ics
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    `
};
