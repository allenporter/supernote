import { computed, onMounted, onUnmounted, ref } from 'vue';
import {
    fetchAiStatus,
    fetchCapacity,
    fetchSystemQueueOverview,
    retryFailedSystemTasks,
} from '../api/client.js';
import { showToast } from '../composables/useToast.js';
import { formatSize, formatSystemTimestamp, getErrorMessage } from '../utils/format.js';

/** @type {Record<string, string>} */
const TASK_TYPE_LABELS = {
    HASHING: 'Page Hash',
    PAGE_HASHING: 'Page Hash',
    PNG_CONVERSION: 'Page Render',
    PNG: 'Page Render',
    OCR_EXTRACTION: 'OCR Transcript',
    OCR: 'OCR Transcript',
    EMBEDDING_GENERATION: 'Vector Index',
    EMBEDDING: 'Vector Index',
    SUMMARY_GENERATION: 'Notebook Summary',
    SUMMARY: 'Notebook Summary',
    SYNTHESIS: 'Notebook Summary',
    RAPID_LOG: 'Rapid Log',
};

/** @type {string[]} */
const STAGE_ORDER = [
    'HASHING',
    'PAGE_HASHING',
    'PNG_CONVERSION',
    'OCR_EXTRACTION',
    'EMBEDDING_GENERATION',
    'SUMMARY_GENERATION',
];

/**
 * @typedef {{
 *   taskType: string,
 *   label: string,
 *   count: number,
 *   isPageScoped: boolean,
 *   status: ProcessingStatus,
 * }} NotebookStageRollup
 */

/**
 * @typedef {{
 *   fileId: string,
 *   fileName: string,
 *   status: ProcessingStatus,
 *   latestUpdateTime: number,
 *   stages: NotebookStageRollup[],
 *   failedCount: number,
 * }} NotebookActivitySummary
 */

export default {
    name: 'SystemPanel',
    emits: ['open-file'],
    template: `
        <div class="space-y-6">
            <!-- 1. Live Queue Status Hero Banner -->
            <div :class="queueBannerClasses" class="p-4 rounded-xl border flex flex-col sm:flex-row sm:items-center justify-between gap-3 transition-colors">
                <div class="flex items-start sm:items-center gap-3 min-w-0">
                    <span v-if="isQueueWorking" class="relative flex h-3 w-3 shrink-0 mt-1 sm:mt-0">
                        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                        <span class="relative inline-flex rounded-full h-3 w-3 bg-sky-600"></span>
                    </span>
                    <span v-else :class="queueDotClass" class="w-2.5 h-2.5 rounded-full shrink-0 mt-1 sm:mt-0"></span>
                    <div class="min-w-0">
                        <div class="flex items-center gap-2 flex-wrap">
                            <span class="text-sm font-bold text-slate-900">{{ queueHeadline }}</span>
                            <span :class="queueBadgeClass" class="px-2 py-0.5 text-[10px] font-mono font-semibold rounded-md border">
                                {{ queueBadgeLabel }}
                            </span>
                        </div>
                        <p class="text-xs text-stone-600 mt-0.5">{{ queueSubtext }}</p>
                    </div>
                </div>
                <div class="flex items-center gap-2 shrink-0">
                    <button v-if="failedTasks.length > 0" @click="handleRetryFailed(null)" :disabled="retryingFileId !== null" type="button"
                        class="px-3 py-1.5 bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors">
                        {{ retryingFileId === 'all' ? 'Retrying...' : 'Retry All Failed' }}
                    </button>
                    <button @click="loadData" :disabled="loading" type="button"
                        class="px-3 py-1.5 bg-white hover:bg-stone-50 border border-stone-200/90 rounded-lg text-xs font-semibold text-slate-700 shadow-sm transition-colors">
                        Refresh
                    </button>
                </div>
            </div>

            <!-- 2. Needs Attention: Failed Tasks (Surfaced at Top When Present) -->
            <section v-if="failedTasks.length > 0" aria-labelledby="failed-tasks-heading"
                class="rounded-xl border border-rose-200 bg-rose-50/50 p-4 space-y-3">
                <div class="flex items-center justify-between gap-2">
                    <div>
                        <h3 id="failed-tasks-heading" class="text-xs font-bold uppercase tracking-wider text-rose-800">
                            Needs Attention ({{ failedTasks.length }})
                        </h3>
                        <p class="text-xs text-rose-700/90 mt-0.5">
                            These stages failed after automatic retries. Fix the underlying model/API error and click Retry.
                        </p>
                    </div>
                </div>
                <ul class="space-y-2.5">
                    <li v-for="task in failedTasks" :key="task.id"
                        class="bg-white border border-rose-200/90 rounded-xl p-3.5 shadow-sm space-y-2">
                        <div class="flex items-start justify-between gap-3">
                            <div class="min-w-0">
                                <div class="flex items-center gap-2 flex-wrap">
                                    <a v-if="task.fileId" :href="buildTaskHref(task)"
                                        @click.prevent="$emit('open-file', task.fileId)"
                                        class="text-xs sm:text-sm font-bold text-slate-900 hover:underline truncate">
                                        {{ task.fileName || formatShortId(task.fileId) }}
                                    </a>
                                    <span class="px-2 py-0.5 text-[10px] font-mono font-semibold rounded-md bg-rose-50 text-rose-700 border border-rose-200">
                                        {{ formatTaskType(task.taskType) }}
                                    </span>
                                    <span class="text-xs font-mono text-stone-600">
                                        {{ formatTaskTarget(task) }}
                                    </span>
                                    <span v-if="task.retryCount > 0" class="text-[11px] font-mono text-stone-500">
                                        · {{ task.retryCount }} retries
                                    </span>
                                </div>
                                <p class="text-[11px] font-mono text-stone-500 mt-0.5 tabular-nums">
                                    Failed {{ formatSystemTimestamp(task.updateTime) }}
                                </p>
                            </div>
                            <button @click="handleRetryFailed(task.fileId)" :disabled="retryingFileId !== null" type="button"
                                class="shrink-0 px-3 py-1.5 rounded-lg border border-rose-200 bg-rose-50 hover:bg-rose-100 disabled:opacity-50 text-rose-700 text-xs font-semibold transition-colors">
                                {{ retryingFileId === String(task.fileId) ? 'Retrying...' : 'Retry Notebook' }}
                            </button>
                        </div>
                        <div v-if="task.lastError"
                            class="px-3 py-2 rounded-lg bg-stone-50 border border-stone-200/80 text-xs font-mono text-rose-800 break-words leading-relaxed">
                            {{ task.lastError }}
                        </div>
                    </li>
                </ul>
            </section>

            <!-- 3. Storage Quota & AI Pipeline Capabilities -->
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

            <!-- 4. Recent Notebook Processing Activity (Notebook Rollup vs Stage Log) -->
            <div>
                <div class="flex items-center justify-between gap-2 mb-3 flex-wrap">
                    <h3 class="text-xs font-bold uppercase tracking-wider text-stone-500">
                        Recent Notebook Activity
                        <span v-if="!loading" class="font-mono font-normal text-stone-500">
                            ({{ viewMode === 'notebooks' ? notebookSummaries.length : tasks.length }})
                        </span>
                    </h3>
                    <div class="inline-flex items-center bg-stone-200/70 p-0.5 rounded-lg border border-stone-300/40 text-xs">
                        <button @click="viewMode = 'notebooks'" type="button"
                            :class="viewMode === 'notebooks' ? 'bg-white text-slate-900 font-semibold shadow-sm' : 'text-stone-600 hover:text-slate-900 font-medium'"
                            class="px-2.5 py-1 rounded-md text-[11px] transition-all">
                            By Notebook
                        </button>
                        <button @click="viewMode = 'stages'" type="button"
                            :class="viewMode === 'stages' ? 'bg-white text-slate-900 font-semibold shadow-sm' : 'text-stone-600 hover:text-slate-900 font-medium'"
                            class="px-2.5 py-1 rounded-md text-[11px] transition-all">
                            Stage Log
                        </button>
                    </div>
                </div>

                <div v-if="loading" class="flex justify-center py-12 bg-stone-50/50 rounded-xl border border-stone-200/70">
                    <div class="animate-spin rounded-full h-6 w-6 border-2 border-stone-300 border-t-slate-900"></div>
                </div>

                <div v-else-if="error" class="p-4 bg-rose-50 border border-rose-200 text-rose-700 rounded-xl text-xs">
                    {{ error }}
                </div>

                <!-- View A: Grouped by Notebook (Default) -->
                <div v-else-if="viewMode === 'notebooks'" class="border border-stone-200/90 rounded-xl overflow-hidden bg-white shadow-sm">
                    <div v-if="notebookSummaries.length === 0" class="px-4 py-8 text-center text-xs text-stone-500">
                        No background processing tasks recorded yet. Sync a <code class="font-mono">.note</code> file to start processing.
                    </div>
                    <ul v-else class="divide-y divide-stone-100">
                        <li v-for="nb in notebookSummaries" :key="nb.fileId"
                            class="px-4 py-3.5 hover:bg-stone-50/70 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
                            <div class="min-w-0 space-y-1.5">
                                <div class="flex items-center gap-2 flex-wrap">
                                    <a :href="'#/file/' + nb.fileId"
                                        @click.prevent="$emit('open-file', nb.fileId)"
                                        class="text-xs sm:text-sm font-bold text-slate-900 hover:underline truncate">
                                        {{ nb.fileName }}
                                    </a>
                                    <span :class="statusClass(nb.status)" class="px-2 py-0.5 inline-flex text-[10px] font-mono font-semibold rounded-md border">
                                        {{ nb.status }}
                                    </span>
                                </div>
                                <div class="flex items-center gap-1.5 flex-wrap">
                                    <span v-for="st in nb.stages" :key="st.taskType"
                                        :class="stageChipClass(st.status)"
                                        class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[11px] font-medium">
                                        <span :class="stageDotClass(st.status)" class="w-1.5 h-1.5 rounded-full"></span>
                                        <span>{{ st.label }}</span>
                                        <span v-if="st.isPageScoped && st.count > 0" class="font-mono text-[10px] opacity-75">
                                            ({{ st.count }}p)
                                        </span>
                                    </span>
                                </div>
                            </div>
                            <div class="flex items-center gap-3 shrink-0 sm:text-right">
                                <span class="font-mono text-[11px] text-stone-500 tabular-nums">
                                    {{ formatSystemTimestamp(nb.latestUpdateTime) }}
                                </span>
                                <button v-if="nb.failedCount > 0" @click="handleRetryFailed(nb.fileId)" :disabled="retryingFileId !== null" type="button"
                                    class="px-2.5 py-1 rounded-lg border border-rose-200 bg-rose-50 hover:bg-rose-100 text-rose-700 text-xs font-semibold">
                                    Retry
                                </button>
                            </div>
                        </li>
                    </ul>
                </div>

                <!-- View B: Granular Stage Log Table -->
                <div v-else class="border border-stone-200/90 rounded-xl overflow-hidden bg-white shadow-sm">
                    <div class="overflow-x-auto">
                        <table class="w-full text-left border-collapse">
                            <thead class="bg-stone-50/90 border-b border-stone-200/80">
                                <tr>
                                    <th class="px-3.5 py-2.5 text-[11px] font-semibold text-stone-500 uppercase tracking-wider">Notebook</th>
                                    <th class="px-3 py-2.5 text-[11px] font-semibold text-stone-500 uppercase tracking-wider">Stage</th>
                                    <th class="px-3 py-2.5 text-[11px] font-semibold text-stone-500 uppercase tracking-wider">Target</th>
                                    <th class="px-3 py-2.5 text-[11px] font-semibold text-stone-500 uppercase tracking-wider">Status</th>
                                    <th class="px-3.5 py-2.5 text-[11px] font-semibold text-stone-500 uppercase tracking-wider text-right">Updated</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-stone-100 text-xs">
                                <tr v-for="task in tasks" :key="task.id" class="hover:bg-stone-50/70 transition-colors">
                                    <td class="px-3.5 py-2.5 font-semibold text-slate-900 whitespace-nowrap">
                                        <a v-if="task.fileId" :href="buildTaskHref(task)"
                                            @click.prevent="$emit('open-file', task.fileId)"
                                            class="text-slate-900 hover:underline">
                                            {{ task.fileName || formatShortId(task.fileId) }}
                                        </a>
                                        <span v-else class="text-stone-500">—</span>
                                    </td>
                                    <td class="px-3 py-2.5 font-medium text-slate-700 whitespace-nowrap" :title="task.taskType">
                                        {{ formatTaskType(task.taskType) }}
                                    </td>
                                    <td class="px-3 py-2.5 font-mono text-stone-600 whitespace-nowrap" :title="task.key">
                                        {{ formatTaskTarget(task) }}
                                    </td>
                                    <td class="px-3 py-2.5 whitespace-nowrap">
                                        <div class="flex items-center gap-1.5">
                                            <span :class="statusClass(task.status)" class="px-2 py-0.5 inline-flex text-[10px] font-mono font-semibold rounded-md border">
                                                {{ task.status }}
                                            </span>
                                            <span v-if="task.retryCount > 0" class="text-[10px] font-mono text-stone-500" :title="'Retries: ' + task.retryCount">
                                                ({{ task.retryCount }}x)
                                            </span>
                                            <span v-if="task.lastError" class="text-[11px] text-rose-600 truncate max-w-[140px]" :title="task.lastError">
                                                {{ task.lastError }}
                                            </span>
                                        </div>
                                    </td>
                                    <td class="px-3.5 py-2.5 whitespace-nowrap text-right font-mono text-[11px] text-stone-500 tabular-nums">
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
    `,
    setup() {
        const loading = ref(true);
        /** @type {import('vue').Ref<string | null>} */
        const error = ref(null);
        /** @type {import('vue').Ref<SystemTaskItem[]>} */
        const tasks = ref([]);
        const queuePaused = ref(false);
        const queueSize = ref(0);
        /** @type {import('vue').Ref<string[]>} */
        const processingFileIds = ref([]);
        /** @type {import('vue').Ref<CapacityInfo | null>} */
        const capacity = ref(null);
        /** @type {import('vue').Ref<AiStatus | null>} */
        const aiStatus = ref(null);
        /** @type {import('vue').Ref<'notebooks' | 'stages'>} */
        const viewMode = ref('notebooks');
        /** @type {import('vue').Ref<string | null>} */
        const retryingFileId = ref(null);

        const usagePercent = computed(() => {
            if (!capacity.value || capacity.value.totalCapacity === 0) return 0;
            return Math.min(
                100,
                (capacity.value.usedCapacity / capacity.value.totalCapacity) * 100,
            );
        });

        const failedTasks = computed(() => tasks.value.filter((t) => t.status === 'FAILED'));

        const activeTasks = computed(() =>
            tasks.value.filter((t) => t.status === 'PROCESSING' || t.status === 'PENDING'),
        );

        const isQueueWorking = computed(
            () => !queuePaused.value && (queueSize.value > 0 || activeTasks.value.length > 0),
        );

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
         * @param {string | null | undefined} rawType
         */
        const formatTaskType = (rawType) => {
            if (!rawType) return 'Task';
            return TASK_TYPE_LABELS[rawType] || rawType;
        };

        /**
         * @param {SystemTaskItem} task
         */
        const formatTaskTarget = (task) => {
            if (typeof task.pageIndex === 'number' && task.pageIndex >= 0) {
                return `Page ${task.pageIndex + 1}`;
            }
            const str = String(task.key || '');
            if (!str || str === 'global') return 'Whole notebook';
            if (str.startsWith('page_') && str.length > 18) {
                return `Page …${str.slice(-6)}`;
            }
            return str;
        };

        /**
         * @param {SystemTaskItem} task
         */
        const buildTaskHref = (task) => {
            if (typeof task.pageIndex === 'number' && task.pageIndex > 0) {
                return `#/file/${task.fileId}?page=${task.pageIndex + 1}`;
            }
            return `#/file/${task.fileId}`;
        };

        /** @type {import('vue').ComputedRef<NotebookActivitySummary[]>} */
        const notebookSummaries = computed(() => {
            /** @type {Map<string, { fileId: string, fileName: string, latestUpdateTime: number, tasks: SystemTaskItem[] }>} */
            const byFile = new Map();
            const inFlightSet = new Set(processingFileIds.value.map(String));

            for (const t of tasks.value) {
                const fid = String(t.fileId);
                let entry = byFile.get(fid);
                if (!entry) {
                    entry = {
                        fileId: fid,
                        fileName: t.fileName || formatShortId(fid),
                        latestUpdateTime: t.updateTime || 0,
                        tasks: [],
                    };
                    byFile.set(fid, entry);
                } else {
                    if (t.fileName && entry.fileName.startsWith('#')) {
                        entry.fileName = t.fileName;
                    }
                    if ((t.updateTime || 0) > entry.latestUpdateTime) {
                        entry.latestUpdateTime = t.updateTime || 0;
                    }
                }
                entry.tasks.push(t);
            }

            /** @type {NotebookActivitySummary[]} */
            const summaries = [];
            for (const entry of byFile.values()) {
                /** @type {Map<string, { count: number, statuses: ProcessingStatus[], isPageScoped: boolean }>} */
                const stageMap = new Map();
                let failedCount = 0;

                for (const t of entry.tasks) {
                    if (t.status === 'FAILED') failedCount++;
                    let st = stageMap.get(t.taskType);
                    if (!st) {
                        st = {
                            count: 0,
                            statuses: [],
                            isPageScoped: t.key !== 'global',
                        };
                        stageMap.set(t.taskType, st);
                    }
                    st.count++;
                    st.statuses.push(t.status);
                }

                const orderedTypes = [
                    ...STAGE_ORDER.filter((k) => stageMap.has(k)),
                    ...[...stageMap.keys()].filter((k) => !STAGE_ORDER.includes(k)),
                ];

                /** @type {NotebookStageRollup[]} */
                const stages = orderedTypes.map((taskType) => {
                    const info = stageMap.get(taskType);
                    const statuses = info ? info.statuses : [];
                    /** @type {ProcessingStatus} */
                    let stageStatus = 'COMPLETED';
                    if (statuses.includes('FAILED')) stageStatus = 'FAILED';
                    else if (statuses.includes('PROCESSING')) stageStatus = 'PROCESSING';
                    else if (statuses.includes('PENDING')) stageStatus = 'PENDING';
                    return {
                        taskType,
                        label: formatTaskType(taskType),
                        count: info ? info.count : 0,
                        isPageScoped: Boolean(info?.isPageScoped),
                        status: stageStatus,
                    };
                });

                /** @type {ProcessingStatus} */
                let overallStatus = 'COMPLETED';
                if (failedCount > 0) {
                    overallStatus = 'FAILED';
                } else if (
                    inFlightSet.has(entry.fileId) ||
                    stages.some((s) => s.status === 'PROCESSING')
                ) {
                    overallStatus = 'PROCESSING';
                } else if (stages.some((s) => s.status === 'PENDING')) {
                    overallStatus = 'PENDING';
                }

                summaries.push({
                    fileId: entry.fileId,
                    fileName: entry.fileName,
                    status: overallStatus,
                    latestUpdateTime: entry.latestUpdateTime,
                    stages,
                    failedCount,
                });
            }

            const statusRank = { FAILED: 0, PROCESSING: 1, PENDING: 2, COMPLETED: 3 };
            return summaries.sort((a, b) => {
                const rDiff = (statusRank[a.status] ?? 3) - (statusRank[b.status] ?? 3);
                if (rDiff !== 0) return rDiff;
                return b.latestUpdateTime - a.latestUpdateTime;
            });
        });

        const queueHeadline = computed(() => {
            if (loading.value) return 'Checking processing queue…';
            if (queuePaused.value) return 'Background processing is paused';
            if (isQueueWorking.value) {
                const activeCount = Math.max(
                    queueSize.value,
                    new Set(activeTasks.value.map((t) => t.fileId)).size,
                );
                return `Processing ${activeCount} notebook${activeCount === 1 ? '' : 's'}…`;
            }
            if (failedTasks.value.length > 0) {
                const failedNotebooks = new Set(failedTasks.value.map((t) => t.fileId)).size;
                return `${failedNotebooks} notebook${failedNotebooks === 1 ? ' needs' : 's need'} attention`;
            }
            return 'All notebooks up to date';
        });

        const queueSubtext = computed(() => {
            if (loading.value) return 'Loading worker status and recent notebook activity.';
            if (queuePaused.value) {
                return queueSize.value > 0
                    ? `${queueSize.value} notebook(s) queued and waiting to resume.`
                    : 'New notebook syncs will wait until the queue is resumed.';
            }
            if (isQueueWorking.value) {
                const current = activeTasks.value[0];
                if (current) {
                    const name = current.fileName || formatShortId(current.fileId);
                    return `Currently running ${formatTaskType(current.taskType)} on ${name} (${formatTaskTarget(current)}).`;
                }
                return `${queueSize.value} notebook(s) queued for background processing.`;
            }
            if (failedTasks.value.length > 0) {
                return `${failedTasks.value.length} stage(s) failed during background processing. Review errors below or click Retry.`;
            }
            if (notebookSummaries.value.length === 0) {
                return 'Worker queue is idle. Sync a notebook from your Supernote to trigger OCR and summaries.';
            }
            return `Worker queue is idle. ${notebookSummaries.value.length} recent notebook(s) processed cleanly.`;
        });

        const queueBadgeLabel = computed(() => {
            if (queuePaused.value) return 'PAUSED';
            if (isQueueWorking.value) return 'WORKING';
            if (failedTasks.value.length > 0) return 'FAILED';
            return 'IDLE';
        });

        const queueBannerClasses = computed(() => {
            if (queuePaused.value) return 'bg-amber-50/70 border-amber-200';
            if (isQueueWorking.value) return 'bg-sky-50/70 border-sky-200';
            if (failedTasks.value.length > 0) return 'bg-rose-50/60 border-rose-200';
            return 'bg-stone-50/80 border-stone-200/80';
        });

        const queueDotClass = computed(() => {
            if (queuePaused.value) return 'bg-amber-500';
            if (failedTasks.value.length > 0) return 'bg-rose-500';
            return 'bg-emerald-500';
        });

        const queueBadgeClass = computed(() => {
            if (queuePaused.value) return 'bg-amber-100 text-amber-800 border-amber-200';
            if (isQueueWorking.value) return 'bg-sky-100 text-sky-800 border-sky-200';
            if (failedTasks.value.length > 0) return 'bg-rose-100 text-rose-800 border-rose-200';
            return 'bg-emerald-50 text-emerald-700 border-emerald-200';
        });

        const loadData = async () => {
            loading.value = true;
            error.value = null;
            try {
                const [overviewResult, capacityResult, aiStatusResult] = await Promise.all([
                    fetchSystemQueueOverview(),
                    fetchCapacity(),
                    fetchAiStatus(),
                ]);

                tasks.value = overviewResult.tasks;
                queuePaused.value = overviewResult.paused;
                queueSize.value = overviewResult.queueSize;
                processingFileIds.value = overviewResult.processingFileIds;
                capacity.value = capacityResult;
                aiStatus.value = aiStatusResult;
            } catch (e) {
                error.value = getErrorMessage(e);
            } finally {
                loading.value = false;
            }
        };

        /**
         * @param {string | number | null} fileId
         */
        const handleRetryFailed = async (fileId = null) => {
            if (retryingFileId.value !== null) return;
            retryingFileId.value = fileId === null ? 'all' : String(fileId);
            try {
                const retried = await retryFailedSystemTasks(fileId);
                showToast(
                    retried.length > 0
                        ? `Queued ${retried.length} notebook${retried.length === 1 ? '' : 's'} for reprocessing`
                        : 'No failed tasks to retry',
                    'success',
                );
                await loadData();
            } catch (e) {
                showToast(getErrorMessage(e));
            } finally {
                retryingFileId.value = null;
            }
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

        /**
         * @param {string} status
         */
        const stageChipClass = (status) => {
            /** @type {Record<string, string>} */
            const classes = {
                PENDING: 'bg-amber-50/70 text-amber-800 border-amber-200',
                PROCESSING: 'bg-sky-50/70 text-sky-800 border-sky-200',
                COMPLETED: 'bg-stone-100/80 text-slate-700 border-stone-200/80',
                FAILED: 'bg-rose-50 text-rose-700 border-rose-200',
            };
            return classes[status] || 'bg-stone-100 text-stone-600 border-stone-200';
        };

        /**
         * @param {string} status
         */
        const stageDotClass = (status) => {
            /** @type {Record<string, string>} */
            const classes = {
                PENDING: 'bg-amber-500',
                PROCESSING: 'bg-sky-500',
                COMPLETED: 'bg-emerald-500',
                FAILED: 'bg-rose-500',
            };
            return classes[status] || 'bg-stone-400';
        };

        onMounted(() => {
            loadData();
            window.addEventListener('supernote:file-sync', loadData);
        });

        onUnmounted(() => {
            window.removeEventListener('supernote:file-sync', loadData);
        });

        return {
            loading,
            error,
            tasks,
            failedTasks,
            notebookSummaries,
            viewMode,
            retryingFileId,
            isQueueWorking,
            queueHeadline,
            queueSubtext,
            queueBadgeLabel,
            queueBannerClasses,
            queueDotClass,
            queueBadgeClass,
            capacity,
            aiStatus,
            usagePercent,
            formatSize,
            formatSystemTimestamp,
            loadData,
            handleRetryFailed,
            formatTaskType,
            formatTaskTarget,
            buildTaskHref,
            formatShortId,
            statusClass,
            stageChipClass,
            stageDotClass,
        };
    },
};
