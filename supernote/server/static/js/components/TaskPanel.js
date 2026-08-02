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
            removeGroup
        } = useSchedule();

        // Modals
        const showNewTaskModal = ref(false);
        const showNewGroupModal = ref(false);
        const editingTask = ref(null);

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

        // Group Name Map
        const groupNameMap = computed(() => {
            const map = { '0': 'General' };
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

            // Modals
            showNewTaskModal,
            showNewGroupModal,
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
            selectGroup
        };
    },
    template: `
    <div class="flex flex-col md:flex-row gap-6 max-w-6xl mx-auto w-full animate-fade-in">
        <!-- Sidebar Column: Filters & Task Groups -->
        <div class="w-full md:w-56 flex-shrink-0 space-y-4">
            <!-- Filter Modes -->
            <div class="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-2xl p-2.5 space-y-0.5">
                <div class="px-2 py-1">
                    <span class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Filters</span>
                </div>

                <button @click="selectFilterMode('all')"
                    :class="selectedFilter === 'all' && selectedGroupId === null ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900 font-semibold' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'"
                    class="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs transition-colors">
                    <span>All Tasks</span>
                    <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 font-bold">{{ openTasksCount }}</span>
                </button>

                <button @click="selectFilterMode('today')"
                    :class="selectedFilter === 'today' ? 'bg-emerald-600 text-white font-semibold' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'"
                    class="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs transition-colors">
                    <span>Due Today</span>
                    <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 font-bold">{{ todayTasksCount }}</span>
                </button>

                <button @click="selectFilterMode('high')"
                    :class="selectedFilter === 'high' ? 'bg-rose-600 text-white font-semibold' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'"
                    class="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs transition-colors">
                    <span>High Priority</span>
                    <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300 font-bold">{{ highPriorityCount }}</span>
                </button>

                <button @click="selectFilterMode('completed')"
                    :class="selectedFilter === 'completed' ? 'bg-slate-700 text-white font-semibold' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'"
                    class="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs transition-colors">
                    <span>Completed</span>
                    <span class="text-[10px] px-1.5 py-0.2 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 font-bold">{{ completedTasksCount }}</span>
                </button>
            </div>

            <!-- Task Groups Management Panel -->
            <div class="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 rounded-2xl p-2.5 space-y-1">
                <div class="flex items-center justify-between px-2 py-1">
                    <span class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Task Groups</span>
                    <button @click="showNewGroupModal = true" class="text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:underline">
                        + Add
                    </button>
                </div>

                <div class="space-y-0.5">
                    <div v-for="group in taskGroups" :key="group.id" class="group flex items-center justify-between">
                        <button @click="selectGroup(group.id)"
                            :class="selectedGroupId === group.id ? 'bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 font-bold' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'"
                            class="flex-1 flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs transition-colors text-left truncate">
                            <span class="truncate">{{ group.title }}</span>
                            <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 font-mono ml-1 flex-shrink-0">{{ getTaskCountForGroup(group.id) }}</span>
                        </button>

                        <!-- Delete Group Button -->
                        <button @click.stop="removeGroup(group.id, group.title)"
                            class="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-rose-600 transition-opacity ml-1 flex-shrink-0" title="Delete Group">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Main Task List Column -->
        <div class="flex-1 min-w-0 space-y-4">
            <!-- Search & New Task Bar -->
            <div class="flex items-center justify-between gap-3">
                <div class="relative flex-1">
                    <input v-model="searchQuery" type="text" placeholder="Filter tasks by keyword..."
                        class="w-full pl-8 pr-4 py-1.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl text-xs outline-none focus:ring-2 focus:ring-indigo-500 text-slate-900 dark:text-slate-100">
                    <svg class="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                </div>

                <button @click="openCreateTaskModal"
                    class="px-3.5 py-1.5 bg-slate-900 dark:bg-white text-white dark:text-slate-900 hover:bg-slate-800 text-xs font-semibold rounded-xl transition-all shadow-sm flex-shrink-0">
                    + New Task
                </button>
            </div>

            <!-- Loading State -->
            <div v-if="isLoading" class="flex justify-center py-16">
                <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
            </div>

            <!-- Empty State -->
            <div v-else-if="filteredTasks.length === 0" class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-12 text-center shadow-sm">
                <div class="w-10 h-10 bg-slate-100 dark:bg-slate-800 text-slate-500 rounded-xl flex items-center justify-center mx-auto mb-3">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                </div>
                <h3 class="text-sm font-semibold text-slate-900 dark:text-white mb-1">No tasks found</h3>
                <p class="text-xs text-slate-500 dark:text-slate-400 mb-4">Create a new task to get started on your schedule.</p>
                <button @click="openCreateTaskModal" class="inline-flex items-center gap-1.5 bg-slate-900 dark:bg-white text-white dark:text-slate-900 px-3.5 py-1.5 rounded-xl text-xs font-medium hover:bg-slate-800 transition-colors shadow-sm">
                    + New Task
                </button>
            </div>

            <!-- Task Cards -->
            <div v-else class="space-y-2">
                <div v-for="task in filteredTasks" :key="task.id"
                    :class="task.status === 'completed' ? 'opacity-60 bg-slate-50/70 dark:bg-slate-900/40 border-slate-200 dark:border-slate-800' : 'bg-white dark:bg-slate-900 border-slate-200/80 dark:border-slate-800 hover:border-slate-300 shadow-sm'"
                    class="group rounded-xl border p-3 transition-all flex items-start gap-3">

                    <!-- Checkbox -->
                    <button @click="toggleTaskCompleted(task)" class="mt-0.5 flex-shrink-0 transition-transform active:scale-95">
                        <div v-if="task.status === 'completed'" class="w-4 h-4 bg-indigo-600 text-white rounded flex items-center justify-center shadow-sm">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path></svg>
                        </div>
                        <div v-else class="w-4 h-4 rounded border-2 border-slate-300 dark:border-slate-600 hover:border-indigo-600 transition-colors"></div>
                    </button>

                    <!-- Task Body -->
                    <div class="flex-grow min-w-0" @click="openEditTaskModal(task)">
                        <div class="flex flex-wrap items-center gap-2">
                            <span :class="{'line-through text-slate-400 dark:text-slate-500': task.status === 'completed'}"
                                class="font-semibold text-slate-900 dark:text-slate-100 text-sm cursor-pointer hover:text-indigo-600 transition-colors">
                                {{ task.title }}
                            </span>

                            <!-- Badges -->
                            <span v-if="groupNameMap[task.taskListId]" class="text-[10px] px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-medium">
                                {{ groupNameMap[task.taskListId] }}
                            </span>

                            <span v-if="task.importance === 'high'" class="text-[10px] px-2 py-0.5 rounded-md bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300 font-bold">
                                High
                            </span>

                            <span v-if="formatDueDate(task.dueTime)" class="text-[10px] px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 font-medium flex items-center gap-1">
                                📅 {{ formatDueDate(task.dueTime) }}
                            </span>
                        </div>

                        <p v-if="task.detail" class="text-xs text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-1">
                            {{ task.detail }}
                        </p>
                    </div>

                    <!-- Delete Task Button -->
                    <button @click.stop="removeTask(task.id)" class="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-rose-600 p-1 transition-opacity" title="Delete Task">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                    </button>
                </div>
            </div>
        </div>

        <!-- New/Edit Task Modal -->
        <div v-if="showNewTaskModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/30 backdrop-blur-[2px]">
            <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 max-w-md w-full shadow-2xl space-y-4">
                <h3 class="text-base font-bold text-slate-900 dark:text-white">{{ editingTask ? 'Edit Task' : 'New Task' }}</h3>

                <div class="space-y-3 text-sm">
                    <div>
                        <label class="block text-slate-500 mb-1">Title</label>
                        <input v-model="taskForm.title" type="text" placeholder="Task title..." class="w-full p-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl outline-none text-slate-900 dark:text-slate-100">
                    </div>

                    <div>
                        <label class="block text-slate-500 mb-1">Details</label>
                        <textarea v-model="taskForm.detail" rows="2" placeholder="Optional notes..." class="w-full p-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl outline-none text-slate-900 dark:text-slate-100"></textarea>
                    </div>

                    <div class="grid grid-cols-2 gap-3">
                        <div>
                            <label class="block text-slate-500 mb-1">Group</label>
                            <select v-model="taskForm.taskListId" class="w-full p-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl outline-none text-slate-900 dark:text-slate-100">
                                <option value="0">General</option>
                                <option v-for="g in taskGroups" :key="g.id" :value="g.id">{{ g.title }}</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-slate-500 mb-1">Priority</label>
                            <select v-model="taskForm.importance" class="w-full p-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl outline-none text-slate-900 dark:text-slate-100">
                                <option value="low">Normal</option>
                                <option value="high">High</option>
                            </select>
                        </div>
                    </div>

                    <div>
                        <label class="block text-slate-500 mb-1">Due Date</label>
                        <input v-model="taskForm.dueDate" type="date" class="w-full p-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl outline-none text-slate-900 dark:text-slate-100">
                    </div>
                </div>

                <div class="flex justify-end gap-2 pt-2">
                    <button @click="showNewTaskModal = false" class="px-3.5 py-2 text-slate-500 hover:text-slate-800 text-xs font-semibold">Cancel</button>
                    <button @click="handleSaveTask" class="px-4 py-2 bg-slate-900 dark:bg-white text-white dark:text-slate-900 text-xs font-semibold rounded-xl">Save</button>
                </div>
            </div>
        </div>

        <!-- New Group Modal -->
        <div v-if="showNewGroupModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/30 backdrop-blur-[2px]">
            <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 max-w-sm w-full shadow-2xl space-y-4">
                <h3 class="text-sm font-bold text-slate-900 dark:text-white">New Task Group</h3>
                <input v-model="newGroupTitle" type="text" placeholder="Group name..." class="w-full p-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl text-xs outline-none text-slate-900 dark:text-slate-100">
                <div class="flex justify-end gap-2">
                    <button @click="showNewGroupModal = false" class="px-3 py-1.5 text-slate-500 text-xs font-semibold">Cancel</button>
                    <button @click="handleCreateGroup" class="px-4 py-1.5 bg-slate-900 dark:bg-white text-white dark:text-slate-900 text-xs font-semibold rounded-xl">Create</button>
                </div>
            </div>
        </div>
    </div>
    `
}
