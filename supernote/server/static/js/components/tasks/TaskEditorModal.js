import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { normalizeTaskImportance } from '../../api/schedule.js';
import { normalizeEpochMs } from '../../utils/format.js';

/**
 * @param {Date} dateObj
 * @returns {string}
 */
export function toLocalDateInputValue(dateObj) {
    const year = dateObj.getFullYear();
    const month = String(dateObj.getMonth() + 1).padStart(2, '0');
    const day = String(dateObj.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

export default {
    name: 'TaskEditorModal',
    props: {
        task: {
            type: Object,
            default: null,
        },
        taskGroups: {
            type: Array,
            default: () => [],
        },
        defaultDueDate: {
            type: String,
            default: '',
        },
        defaultGroupId: {
            type: [String, Number],
            default: null,
        },
    },
    emits: ['save', 'close'],
    /**
     * @param {Record<string, any>} props
     * @param {{ emit: (event: string, ...args: any[]) => void }} context
     */
    setup(props, { emit }) {
        /** @type {import('vue').Ref<HTMLInputElement | null>} */
        const taskTitleInput = ref(null);

        /**
         * @param {ScheduleTask | null | undefined} task
         */
        function buildFormState(task) {
            if (task) {
                let formattedDate = '';
                if (task.dueTime) {
                    const dueMs = normalizeEpochMs(task.dueTime);
                    if (dueMs !== null) {
                        formattedDate = toLocalDateInputValue(new Date(dueMs));
                    }
                }
                return {
                    id: task.id,
                    taskListId: task.taskListId ? String(task.taskListId) : null,
                    title: task.title || '',
                    detail: task.detail || '',
                    importance: normalizeTaskImportance(task.importance),
                    dueDate: formattedDate,
                    status: task.status || 'needsAction',
                };
            }

            return {
                id: null,
                taskListId: props.defaultGroupId ? String(props.defaultGroupId) : null,
                title: '',
                detail: '',
                importance: 'low',
                dueDate: props.defaultDueDate || '',
                status: 'needsAction',
            };
        }

        const taskForm = ref(buildFormState(props.task));

        watch(
            () => props.task,
            (nextTask) => {
                taskForm.value = buildFormState(nextTask);
            },
        );

        function handleSaveTask() {
            if (!taskForm.value.title.trim()) return;

            let epochDue = 0;
            if (taskForm.value.dueDate) {
                const parsedDate = new Date(`${taskForm.value.dueDate}T12:00:00Z`);
                epochDue = parsedDate.getTime();
            }

            emit('save', {
                id: taskForm.value.id,
                taskListId: taskForm.value.taskListId,
                title: taskForm.value.title.trim(),
                detail: taskForm.value.detail.trim(),
                importance: normalizeTaskImportance(taskForm.value.importance),
                dueTime: epochDue,
                status: taskForm.value.status,
            });
        }

        /**
         * @param {KeyboardEvent} e
         */
        function handleKeydown(e) {
            if (e.key === 'Escape' && !e.defaultPrevented) {
                e.preventDefault();
                e.stopPropagation();
                emit('close');
            }
        }

        onMounted(() => {
            window.addEventListener('keydown', handleKeydown);
            nextTick(() => taskTitleInput.value?.focus());
        });

        onUnmounted(() => {
            window.removeEventListener('keydown', handleKeydown);
        });

        return {
            taskTitleInput,
            taskForm,
            handleSaveTask,
        };
    },
    template: `
    <div role="dialog" aria-modal="true" :aria-label="task ? 'Edit Task' : 'New Task'"
        class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px]" @click.self="$emit('close')">
        <div class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-lg p-6 space-y-5 animate-fade-in">
            <h3 class="text-base font-bold text-slate-900">
                {{ task ? 'Edit Task' : 'New Task' }}
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
                <button @click="$emit('close')" type="button" class="px-4 py-2 text-stone-600 hover:text-slate-900 text-xs font-semibold">
                    Cancel
                </button>
                <button @click="handleSaveTask" :disabled="!taskForm.title.trim()" type="button"
                    class="px-5 py-2 bg-slate-900 hover:bg-slate-800 disabled:opacity-40 text-white rounded-xl text-xs font-semibold transition-all">
                    {{ task ? 'Save Changes' : 'Save Task' }}
                </button>
            </div>
        </div>
    </div>
    `,
};
