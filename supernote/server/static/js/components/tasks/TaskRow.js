import { computed } from 'vue';
import { normalizeTaskImportance } from '../../api/schedule.js';
import { normalizeEpochMs } from '../../utils/format.js';

/**
 * @param {Partial<ScheduleTask> | null | undefined} task
 * @returns {{ label: string, classes: string } | null}
 */
export function getDueMeta(task) {
    if (!task?.dueTime) return null;
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
            ...(due.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}),
        });
        return {
            label: `Overdue · ${shortDate}`,
            classes: 'bg-rose-50 text-rose-700 border-rose-200 font-semibold',
        };
    }

    if (dueDayStart === todayStart) {
        return {
            label: 'Due Today',
            classes:
                task.status === 'completed'
                    ? 'bg-stone-50 text-stone-500 border-stone-200'
                    : 'bg-emerald-50 text-emerald-700 border-emerald-200 font-semibold',
        };
    }

    if (dueDayStart === tomorrowStart) {
        return {
            label: 'Due Tomorrow',
            classes:
                task.status === 'completed'
                    ? 'bg-stone-50 text-stone-500 border-stone-200'
                    : 'bg-amber-50 text-amber-700 border-amber-200 font-semibold',
        };
    }

    return {
        label: due.toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
        }),
        classes: 'bg-stone-50 text-stone-500 border-stone-200',
    };
}

export default {
    name: 'TaskRow',
    props: {
        task: {
            type: Object,
            required: true,
        },
        groupName: {
            type: String,
            default: null,
        },
    },
    emits: ['toggle-complete', 'edit', 'delete'],
    /**
     * @param {Record<string, any>} props
     */
    setup(props) {
        const importanceLevel = computed(() => normalizeTaskImportance(props.task.importance));
        const dueMeta = computed(() => getDueMeta(props.task));

        return {
            importanceLevel,
            dueMeta,
        };
    },
    template: `
    <div :class="task.status === 'completed' ? 'bg-stone-50/60 opacity-75' : 'bg-white hover:bg-stone-50/70'"
        class="group px-4 py-3.5 transition-colors flex items-start gap-3.5">

        <!-- Checkbox -->
        <button @click="$emit('toggle-complete', task)" type="button"
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
                    <span v-if="groupName"
                        class="text-[11px] px-2 py-0.5 rounded-md bg-stone-100 text-stone-600 font-medium border border-stone-200/60">
                        {{ groupName }}
                    </span>

                    <!-- Priority Badge -->
                    <span v-if="importanceLevel === 'high'" class="text-[11px] font-mono px-2 py-0.5 rounded-md bg-rose-50 text-rose-700 font-semibold border border-rose-200/70 flex items-center gap-1">
                        <span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span> High
                    </span>
                    <span v-else-if="importanceLevel === 'medium'" class="text-[11px] font-mono px-2 py-0.5 rounded-md bg-amber-50 text-amber-700 font-semibold border border-amber-200/70 flex items-center gap-1">
                        <span class="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Medium
                    </span>
                    <span v-else class="text-[11px] font-mono px-2 py-0.5 rounded-md bg-stone-100 text-stone-600 font-medium">
                        Low
                    </span>

                    <!-- Due Date / Overdue Chip -->
                    <span v-if="dueMeta"
                        :class="dueMeta.classes"
                        class="text-[11px] font-mono px-2 py-0.5 rounded-md border flex items-center gap-1 tabular-nums">
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                        </svg>
                        {{ dueMeta.label }}
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
            <button @click="$emit('edit', task)" type="button"
                :aria-label="'Edit ' + task.title"
                class="p-1.5 text-stone-500 hover:text-slate-900 rounded-lg hover:bg-stone-100 transition-colors" title="Edit Task">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
                </svg>
            </button>
            <button @click="$emit('delete', task)" type="button"
                :aria-label="'Delete ' + task.title"
                class="p-1.5 text-stone-500 hover:text-rose-600 rounded-lg hover:bg-rose-50 transition-colors" title="Delete Task">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                </svg>
            </button>
        </div>
    </div>
    `,
};
