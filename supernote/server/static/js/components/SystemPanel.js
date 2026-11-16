import { computed, nextTick, onMounted, ref } from 'vue';
import { fetchAiStatus, fetchCapacity, fetchSystemTasks } from '../api/client.js';
import { useModalEscape } from '../composables/useModalEscape.js';
import { formatSize, formatSystemTimestamp, getErrorMessage } from '../utils/format.js';

/** @type {Record<string, string>} */
const TASK_TYPE_LABELS = {
    PNG_CONVERSION: 'Page Render',
    OCR: 'OCR Transcript',
    SUMMARY: 'Page Summary',
    SYNTHESIS: 'Notebook Summary',
    EMBEDDING: 'Vector Index',
    RAPID_LOG: 'Rapid Log',
};

export default {
    name: 'SystemPanel',
    emits: ['close', 'open-file'],
    template: `
        <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-[2px] flex items-center justify-center p-4 z-[120] animate-fade-in" @click.self="$emit('close')">
            <div ref="dialogRef" tabindex="-1" role="dialog" aria-modal="true" aria-label="System Status"
                class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-4xl max-h-[88vh] flex flex-col overflow-hidden outline-none">
                <!-- Header -->
                <div class="flex items-center justify-between px-6 py-4 border-b border-stone-200/80 bg-[#F7F6F2]/60">
                    <div>
                        <h2 class="text-base font-bold text-slate-900">System Status &amp; Processing Queue</h2>
                        <p class="text-xs text-stone-500">Storage capacity, AI pipeline configuration, and background worker tasks</p>
                    </div>
                    <button @click="$emit('close')" type="button"
                        class="p-1.5 rounded-lg text-stone-500 hover:text-slate-900 hover:bg-stone-200/60 transition-colors"
                        aria-label="Close system status">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <!-- Content -->
                <div class="flex-1 overflow-y-auto p-6 space-y-6">
                    <!-- Top Row: Storage Quota & AI Pipeline -->
                    <div class="grid grid-cols-1 md:grid-cols-12 gap-4">
                        <!-- Storage Quota -->
                        <div class="md:col-span-5 bg-stone-50/80 border border-stone-200/80 p-4 rounded-xl flex flex-col justify-between">
                            <div class="flex items-center justify-between mb-3">
                                <span class="text-xs font-bold uppercase tracking-wider text-stone-500">Storage Usage</span>
                                <span v-if="capacity" class="text-xs font-mono font-semibold text-slate-700 tabular-nums">
                                    {{ usagePercent.toFixed(1) }}%
                                </span>
                            </div>
                            <div v-if="capacity" class="space-y-2.5">
                                <div class="w-full bg-stone-200/80 rounded-full h-2 overflow-hidden">
                                    <div class="bg-slate-900 h-2 rounded-full transition-all duration-500" :style="{ width: Math.max(usagePercent, capacity.usedCapacity > 0 ? 1.5 : 0) + '%' }"></div>
                                </div>
                                <div class="flex justify-between text-xs font-mono text-stone-500 tabular-nums">
                                    <span class="font-semibold text-slate-900">{{ formatSize(capacity.usedCapacity, '0 B') }} used</span>
                                    <span>{{ formatSize(capacity.totalCapacity, '0 B') }} total</span>
                                </div>
                            </div>
                            <div v-else class="animate-pulse bg-stone-200 h-10 rounded-lg"></div>
                        </div>

                        <!-- AI Pipeline Status -->
                        <div class="md:col-span-7 bg-stone-50/80 border border-stone-200/80 p-4 rounded-xl flex flex-col justify-between">
                            <div class="flex items-center justify-between mb-3">
                                <span class="text-xs font-bold uppercase tracking-wider text-stone-500">AI Processing Pipeline</span>
                                <span v-if="aiStatus"
                                    :class="aiStatus.ocrEnabled || aiStatus.summaryEnabled || aiStatus.vectorSearchEnabled ? 'text-emerald-700 bg-emerald-50 border-emerald-200' : 'text-stone-600 bg-stone-100 border-stone-200'"
                                    class="px-2 py-0.5 text-[10px] font-mono font-semibold rounded-md border">
                                    {{ aiStatus.ocrEnabled || aiStatus.summaryEnabled || aiStatus.vectorSearchEnabled ? 'Active' : 'Standby' }}
                                </span>
                            </div>
                            <div v-if="aiStatus" class="grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-xs">
                                <div class="bg-white p-2.5 rounded-lg border border-stone-200/80 flex flex-col gap-1">
                                    <div class="flex items-center justify-between">
                                        <span class="font-semibold text-slate-700">OCR</span>
                                        <span class="w-2 h-2 rounded-full" :class="aiStatus.ocrEnabled ? 'bg-emerald-500' : 'bg-stone-300'"></span>
                                    </div>
                                    <span class="text-[11px] font-mono truncate" :class="aiStatus.ocrEnabled ? 'text-emerald-700' : 'text-stone-500'">
                                        {{ aiStatus.ocrEnabled ? (aiStatus.ocrModel || aiStatus.model || 'Enabled') : 'Disabled' }}
                                    </span>
                                </div>
                                <div class="bg-white p-2.5 rounded-lg border border-stone-200/80 flex flex-col gap-1">
                                    <div class="flex items-center justify-between">
                                        <span class="font-semibold text-slate-700">Summaries</span>
                                        <span class="w-2 h-2 rounded-full" :class="aiStatus.summaryEnabled ? 'bg-emerald-500' : 'bg-stone-300'"></span>
                                    </div>
                                    <span class="text-[11px] font-mono truncate" :class="aiStatus.summaryEnabled ? 'text-emerald-700' : 'text-stone-500'">
                                        {{ aiStatus.summaryEnabled ? (aiStatus.summaryModel || 'Enabled') : 'Disabled' }}
                                    </span>
                                </div>
                                <div class="bg-white p-2.5 rounded-lg border border-stone-200/80 flex flex-col gap-1">
                                    <div class="flex items-center justify-between">
                                        <span class="font-semibold text-slate-700">Vector Search</span>
                                        <span class="w-2 h-2 rounded-full" :class="aiStatus.vectorSearchEnabled ? 'bg-emerald-500' : 'bg-stone-300'"></span>
                                    </div>
                                    <span class="text-[11px] font-mono truncate" :class="aiStatus.vectorSearchEnabled ? 'text-emerald-700' : 'text-stone-500'">
                                        {{ aiStatus.vectorSearchEnabled ? (aiStatus.embeddingModel || 'Enabled') : 'Disabled' }}
                                    </span>
                                </div>
                            </div>
                            <div v-else class="animate-pulse bg-stone-200 h-12 rounded-lg"></div>
                        </div>
                    </div>

                    <!-- Processing Queue Table -->
                    <div>
                        <div class="flex items-center justify-between mb-3">
                            <h3 class="text-xs font-bold uppercase tracking-wider text-stone-500">
                                Processing Queue <span v-if="!loading" class="font-mono font-normal text-stone-500">({{ tasks.length }})</span>
                            </h3>
                        </div>

                        <div v-if="loading" class="flex justify-center py-12 bg-stone-50/50 rounded-xl border border-stone-200/70">
                            <div class="animate-spin rounded-full h-6 w-6 border-2 border-stone-300 border-t-slate-900"></div>
                        </div>

                        <div v-else-if="error" class="p-4 bg-rose-50 border border-rose-200 text-rose-700 rounded-xl text-xs">
                            {{ error }}
                        </div>

                        <div v-else class="border border-stone-200/90 rounded-xl overflow-hidden bg-white shadow-sm">
                            <div class="overflow-x-auto">
                                <table class="w-full text-left border-collapse">
                                    <thead class="bg-stone-50/90 border-b border-stone-200/80">
                                        <tr>
                                            <th class="px-4 py-2.5 text-[11px] font-semibold text-stone-500 uppercase tracking-wider">Task</th>
                                            <th class="px-4 py-2.5 text-[11px] font-semibold text-stone-500 uppercase tracking-wider">Target</th>
                                            <th class="px-4 py-2.5 text-[11px] font-semibold text-stone-500 uppercase tracking-wider">File ID</th>
                                            <th class="px-4 py-2.5 text-[11px] font-semibold text-stone-500 uppercase tracking-wider">Status</th>
                                            <th class="px-4 py-2.5 text-[11px] font-semibold text-stone-500 uppercase tracking-wider text-right">Updated</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y divide-stone-100 text-xs">
                                        <tr v-for="task in tasks" :key="task.id" class="hover:bg-stone-50/70 transition-colors">
                                            <td class="px-4 py-2.5 font-semibold text-slate-900 whitespace-nowrap" :title="task.taskType">
                                                {{ formatTaskType(task.taskType) }}
                                            </td>
                                            <td class="px-4 py-2.5 font-mono text-stone-600 whitespace-nowrap" :title="task.key">
                                                {{ formatTaskKey(task.key) }}
                                            </td>
                                            <td class="px-4 py-2.5 font-mono whitespace-nowrap tabular-nums" :title="task.fileId ? ('Open file ' + task.fileId) : ''">
                                                <a v-if="task.fileId" :href="'#/file/' + task.fileId"
                                                    @click.prevent="$emit('open-file', task.fileId)"
                                                    class="text-slate-700 hover:text-slate-900 underline decoration-stone-300 hover:decoration-slate-900 underline-offset-2 transition-colors">
                                                    {{ formatShortId(task.fileId) }}
                                                </a>
                                                <span v-else class="text-stone-500">—</span>
                                            </td>
                                            <td class="px-4 py-2.5 whitespace-nowrap">
                                                <div class="flex items-center gap-1.5">
                                                    <span :class="statusClass(task.status)" class="px-2 py-0.5 inline-flex text-[10px] font-mono font-semibold rounded-md border">
                                                        {{ task.status }}
                                                    </span>
                                                    <span v-if="task.retryCount > 0" class="text-[10px] font-mono text-stone-500" :title="'Retries: ' + task.retryCount">
                                                        ({{ task.retryCount }}x)
                                                    </span>
                                                    <span v-if="task.lastError" class="text-[11px] text-rose-600 truncate max-w-[160px]" :title="task.lastError">
                                                        {{ task.lastError }}
                                                    </span>
                                                </div>
                                            </td>
                                            <td class="px-4 py-2.5 whitespace-nowrap text-right font-mono text-[11px] text-stone-500 tabular-nums">
                                                {{ formatSystemTimestamp(task.updateTime) }}
                                            </td>
                                        </tr>
                                        <tr v-if="tasks.length === 0">
                                            <td colspan="5" class="px-4 py-8 text-center text-xs text-stone-500">No background processing tasks recorded.</td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Footer -->
                <div class="px-6 py-3.5 border-t border-stone-200/80 bg-[#F7F6F2]/60 flex justify-end gap-2.5">
                    <button @click="loadData" type="button"
                        class="px-4 py-1.5 bg-white hover:bg-stone-50 border border-stone-200/90 rounded-lg text-xs font-semibold text-slate-700 shadow-sm transition-colors">
                        Refresh
                    </button>
                    <button @click="$emit('close')" type="button"
                        class="px-5 py-1.5 bg-slate-900 hover:bg-slate-800 rounded-lg text-xs font-semibold text-white shadow-sm transition-colors">
                        Done
                    </button>
                </div>
            </div>
        </div>
    `,
    /**
     * @param {Record<string, any>} _props
     * @param {{ emit: (event: string, ...args: any[]) => void }} context
     */
    setup(_props, { emit }) {
        /** @type {import('vue').Ref<HTMLElement | null>} */
        const dialogRef = ref(null);
        const loading = ref(true);
        /** @type {import('vue').Ref<string | null>} */
        const error = ref(null);
        /** @type {import('vue').Ref<SystemTaskItem[]>} */
        const tasks = ref([]);
        /** @type {import('vue').Ref<CapacityInfo | null>} */
        const capacity = ref(null);
        /** @type {import('vue').Ref<AiStatus | null>} */
        const aiStatus = ref(null);

        const usagePercent = computed(() => {
            if (!capacity.value || capacity.value.totalCapacity === 0) return 0;
            return Math.min(
                100,
                (capacity.value.usedCapacity / capacity.value.totalCapacity) * 100,
            );
        });

        const loadData = async () => {
            loading.value = true;
            error.value = null;
            try {
                const [tasksResult, capacityResult, aiStatusResult] = await Promise.all([
                    fetchSystemTasks(),
                    fetchCapacity(),
                    fetchAiStatus(),
                ]);

                tasks.value = tasksResult;
                capacity.value = capacityResult;
                aiStatus.value = aiStatusResult;
            } catch (e) {
                error.value = getErrorMessage(e);
            } finally {
                loading.value = false;
            }
        };

        /**
         * @param {string | null | undefined} rawType
         */
        const formatTaskType = (rawType) => {
            if (!rawType) return 'Task';
            return TASK_TYPE_LABELS[rawType] || rawType;
        };

        /**
         * @param {string | null | undefined} rawKey
         */
        const formatTaskKey = (rawKey) => {
            if (!rawKey) return '—';
            const str = String(rawKey);
            if (str.startsWith('page_') && str.length > 18) {
                return `Page …${str.slice(-6)}`;
            }
            if (str.length > 22) {
                return `${str.slice(0, 10)}…${str.slice(-6)}`;
            }
            return str;
        };

        /**
         * @param {string | number | null | undefined} fileId
         */
        const formatShortId = (fileId) => {
            if (!fileId) return '—';
            const str = String(fileId);
            if (str.length > 10) {
                return `#…${str.slice(-6)}`;
            }
            return `#${str}`;
        };

        /**
         * @param {string} status
         */
        const statusClass = (status) => {
            /** @type {Record<string, string>} */
            const classes = {
                PENDING: 'bg-amber-50 text-amber-700 border-amber-200',
                PROCESSING: 'bg-sky-50 text-sky-700 border-sky-200',
                COMPLETED: 'bg-emerald-50 text-emerald-700 border-emerald-200',
                FAILED: 'bg-rose-50 text-rose-700 border-rose-200',
            };
            return classes[status] || 'bg-stone-100 text-stone-600 border-stone-200';
        };

        useModalEscape(() => emit('close'));

        onMounted(() => {
            loadData();
            nextTick(() => dialogRef.value?.focus());
        });

        return {
            dialogRef,
            loading,
            error,
            tasks,
            capacity,
            aiStatus,
            usagePercent,
            formatSize,
            formatSystemTimestamp,
            loadData,
            formatTaskType,
            formatTaskKey,
            formatShortId,
            statusClass,
        };
    },
};
