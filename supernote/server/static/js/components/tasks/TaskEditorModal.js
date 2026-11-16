import { nextTick, onMounted, ref, watch } from 'vue';
import { normalizeTaskImportance } from '../../api/schedule.js';
import { useModalEscape } from '../../composables/useModalEscape.js';
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

/**
 * Parse a `YYYY-MM-DD` date input string into local-calendar noon epoch milliseconds
 * so round-tripping through `toLocalDateInputValue` preserves the calendar day in every timezone.
 * @param {string | null | undefined} dateStr
 * @returns {number}
 */
export function parseLocalDateInputToEpochMs(dateStr) {
    if (!dateStr) return 0;
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr.trim());
    if (!match) return 0;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const parsed = new Date(year, month - 1, day, 12, 0, 0, 0);
    if (
        Number.isNaN(parsed.getTime()) ||
        parsed.getFullYear() !== year ||
        parsed.getMonth() !== month - 1 ||
        parsed.getDate() !== day
    ) {
        return 0;
    }
    return parsed.getTime();
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
        isSubmitting: {
            type: Boolean,
            default: false,
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
            if (props.isSubmitting || !taskForm.value.title.trim()) return;

            const epochDue = parseLocalDateInputToEpochMs(taskForm.value.dueDate);

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

        useModalEscape(() => {
            if (!props.isSubmitting) emit('close');
        });

        onMounted(() => {
            nextTick(() => taskTitleInput.value?.focus());
        });

        return {
            taskTitleInput,
            taskForm,
            handleSaveTask,
        };
    },
    template: `
    <div role="dialog" aria-modal="true" :aria-label="task ? 'Edit Task' : 'New Task'"
        class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px]" @click.self="!isSubmitting && $emit('close')">
        <form @submit.prevent="handleSaveTask" class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-lg p-6 space-y-5 animate-fade-in">
            <h3 class="text-base font-bold text-slate-900">
                {{ task ? 'Edit Task' : 'New Task' }}
            </h3>

            <div class="space-y-4">
                <div>
                    <label for="task-title-input" class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1">Title</label>
                    <input id="task-title-input" ref="taskTitleInput" v-model="taskForm.title" type="text" placeholder="Task title..."
                        :disabled="isSubmitting"
                        class="w-full px-3.5 py-2.5 bg-stone-50 border border-stone-200 rounded-xl outline-none focus:ring-2 focus:ring-slate-900 focus:border-slate-900 transition-all text-sm disabled:opacity-60">
                </div>

                <div>
                    <label for="task-detail-input" class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1">Details</label>
                    <textarea id="task-detail-input" v-model="taskForm.detail" rows="3" placeholder="Optional notes or details..."
                        :disabled="isSubmitting"
                        class="w-full px-3.5 py-2.5 bg-stone-50 border border-stone-200 rounded-xl outline-none focus:ring-2 focus:ring-slate-900 focus:border-slate-900 transition-all text-sm disabled:opacity-60"></textarea>
                </div>

                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <label for="task-priority-select" class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1">Priority</label>
                        <select id="task-priority-select" v-model="taskForm.importance" :disabled="isSubmitting"
                            class="w-full px-3 py-2.5 bg-stone-50 border border-stone-200 rounded-xl text-xs font-medium outline-none focus:ring-2 focus:ring-slate-900 disabled:opacity-60">
                            <option value="low">Low Priority</option>
                            <option value="medium">Medium Priority</option>
                            <option value="high">High Priority</option>
                        </select>
                    </div>

                    <div>
                        <label for="task-group-select" class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1">Task List</label>
                        <select id="task-group-select" v-model="taskForm.taskListId" :disabled="isSubmitting"
                            class="w-full px-3 py-2.5 bg-stone-50 border border-stone-200 rounded-xl text-xs font-medium outline-none focus:ring-2 focus:ring-slate-900 disabled:opacity-60">
                            <option :value="null">Inbox (General)</option>
                            <option v-for="g in taskGroups" :key="g.id" :value="g.id">{{ g.title }}</option>
                        </select>
                    </div>
                </div>

                <div>
                    <label for="task-due-input" class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1">Due Date</label>
                    <input id="task-due-input" v-model="taskForm.dueDate" type="date" :disabled="isSubmitting"
                        class="w-full px-3.5 py-2.5 bg-stone-50 border border-stone-200 rounded-xl outline-none focus:ring-2 focus:ring-slate-900 text-xs font-mono disabled:opacity-60">
                </div>
            </div>

            <div class="flex justify-end gap-2.5 pt-3 border-t border-stone-100">
                <button @click="$emit('close')" :disabled="isSubmitting" type="button" class="px-4 py-2 text-stone-600 hover:text-slate-900 text-xs font-semibold disabled:opacity-40">
                    Cancel
                </button>
                <button :disabled="isSubmitting || !taskForm.title.trim()" type="submit"
                    class="px-5 py-2 bg-slate-900 hover:bg-slate-800 disabled:opacity-40 text-white rounded-xl text-xs font-semibold transition-all">
                    {{ isSubmitting ? 'Saving...' : (task ? 'Save Changes' : 'Save Task') }}
                </button>
            </div>
        </form>
    </div>
    `,
};
