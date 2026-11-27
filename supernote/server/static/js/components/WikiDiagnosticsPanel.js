/**
 * Live LLM Wiki Diagnostics & Read-Only Dry-Run Compile Inspector.
 */

import { computed, onMounted, ref } from 'vue';
import {
    fetchWikiDiagnostics,
    formatDryRunDropReason,
    formatPageKindLabel,
    runWikiDryRun,
} from '../api/wiki.js';
import { useToast } from '../composables/useToast.js';
import { getErrorMessage } from '../utils/format.js';

export default {
    name: 'WikiDiagnosticsPanel',
    emits: ['close', 'select-slug', 'open-file'],
    /**
     * @param {Record<string, never>} _props
     * @param {{
     *   emit: {
     *     (event: 'close'): void,
     *     (event: 'select-slug', slug: string): void,
     *     (event: 'open-file', target: { id: string, pageIndex?: number | null }): void,
     *   }
     * }} ctx
     */
    setup(_props, { emit }) {
        const { showToast } = useToast();

        const isLoadingCoverage = ref(false);
        const coverageError = ref('');
        /** @type {import('vue').Ref<import('../api/wiki.js').WikiNotebookCoverage[]>} */
        const notebooks = ref([]);

        const selectedFileId = ref('');
        const startDate = ref('');
        const offsetPages = ref(0);
        const maxPages = ref(8);

        const isRunningDryRun = ref(false);
        const dryRunError = ref('');
        /** @type {import('vue').Ref<import('../api/wiki.js').WikiDryRunReport | null>} */
        const dryRunResult = ref(null);
        /** @type {import('vue').Ref<Record<string, boolean>>} */
        const expandedPages = ref({});
        /** @type {import('vue').Ref<Record<string, boolean>>} */
        const expandedOps = ref({});

        let loadSeq = 0;

        const keptOpsCount = computed(
            () => (dryRunResult.value?.ops || []).filter((op) => !op.drop_reason).length,
        );
        const droppedOpsCount = computed(
            () => (dryRunResult.value?.ops || []).filter((op) => Boolean(op.drop_reason)).length,
        );

        const sentPageByKey = computed(() => {
            /** @type {Record<string, import('../api/wiki.js').WikiDryRunPage>} */
            const map = {};
            for (const p of dryRunResult.value?.pages_sent || []) {
                if (p.source_key) {
                    map[p.source_key] = p;
                }
            }
            return map;
        });

        const dryRunVerdict = computed(() => {
            const res = dryRunResult.value;
            if (!res) return null;
            const sentCount = res.pages_sent.length;
            const pageWord = sentCount === 1 ? 'page' : 'pages';
            if (sentCount === 0) {
                return {
                    tone: 'neutral',
                    text: 'No transcribed pages matched this slice. Try clearing the start date or lowering the offset.',
                };
            }
            if (res.ops.length === 0) {
                return {
                    tone: 'warn',
                    text: `The AI read ${sentCount} ${pageWord} and returned 0 wiki updates. Expand a source page below to check whether the OCR text was sparse/garbled or if real insights were ignored.`,
                };
            }
            if (keptOpsCount.value === 0) {
                return {
                    tone: 'warn',
                    text: `The AI proposed ${res.ops.length} ${res.ops.length === 1 ? 'update' : 'updates'}, but the server skipped all of them. See the skip reasons below.`,
                };
            }
            const skippedNote =
                droppedOpsCount.value > 0
                    ? ` (${droppedOpsCount.value} skipped by server rules)`
                    : '';
            return {
                tone: 'ok',
                text: `The AI would save ${keptOpsCount.value} wiki ${keptOpsCount.value === 1 ? 'page' : 'pages'} from ${sentCount} ${pageWord}${skippedNote}. Read-only preview — nothing was modified.`,
            };
        });

        /**
         * @param {import('../api/wiki.js').WikiNotebookCoverage} nb
         * @returns {number}
         */
        function coveragePercent(nb) {
            return Math.round((nb.cited_pages / Math.max(1, nb.ocr_pages)) * 100);
        }

        /**
         * @param {import('../api/wiki.js').WikiNotebookCoverage} nb
         * @returns {string}
         */
        function coverageBadgeClass(nb) {
            const pct = coveragePercent(nb);
            if (pct === 0) return 'bg-amber-50 text-amber-800 border-amber-200';
            if (pct >= 80) return 'bg-emerald-50 text-emerald-700 border-emerald-200';
            return 'bg-stone-100 text-stone-700 border-stone-200';
        }

        /**
         * Format a resolved `source_key` using the human-readable page sent in this turn when available.
         *
         * @param {string} refKey
         * @returns {string}
         */
        function formatResolvedCitation(refKey) {
            const sent = sentPageByKey.value[refKey];
            if (sent) {
                const handle = sent.source_id ? `${sent.source_id} · ` : '';
                return `${handle}${sent.file_path} p.${sent.page_index + 1}`;
            }
            return refKey;
        }

        /**
         * @param {string} key
         */
        function togglePageText(key) {
            expandedPages.value = {
                ...expandedPages.value,
                [key]: !expandedPages.value[key],
            };
        }

        /**
         * @param {string} key
         */
        function toggleOpDraft(key) {
            expandedOps.value = {
                ...expandedOps.value,
                [key]: !expandedOps.value[key],
            };
        }

        async function loadCoverage() {
            const seq = ++loadSeq;
            isLoadingCoverage.value = true;
            coverageError.value = '';
            try {
                const list = await fetchWikiDiagnostics();
                if (seq !== loadSeq) return;
                notebooks.value = list;
            } catch (err) {
                if (seq === loadSeq) {
                    coverageError.value = getErrorMessage(err);
                }
            } finally {
                if (seq === loadSeq) {
                    isLoadingCoverage.value = false;
                }
            }
        }

        async function handleDryRun() {
            if (isRunningDryRun.value) return;
            isRunningDryRun.value = true;
            dryRunError.value = '';
            try {
                const safeOffset = Math.max(0, Number(offsetPages.value) || 0);
                const safeMax = Math.min(20, Math.max(1, Number(maxPages.value) || 8));
                offsetPages.value = safeOffset;
                maxPages.value = safeMax;
                dryRunResult.value = await runWikiDryRun({
                    fileId: selectedFileId.value || null,
                    startDate: startDate.value || null,
                    offsetPages: safeOffset,
                    maxPages: safeMax,
                });
                expandedPages.value = {};
                expandedOps.value = {};
            } catch (err) {
                const msg = getErrorMessage(err);
                dryRunError.value = msg;
                showToast(msg, 'error');
            } finally {
                isRunningDryRun.value = false;
            }
        }

        /**
         * @param {string} fileId
         */
        async function dryRunNotebook(fileId) {
            selectedFileId.value = fileId;
            offsetPages.value = 0;
            await handleDryRun();
        }

        async function handleNextSlice() {
            offsetPages.value =
                Math.max(0, Number(offsetPages.value) || 0) +
                Math.max(1, Number(maxPages.value) || 8);
            await handleDryRun();
        }

        onMounted(() => {
            loadCoverage();
        });

        return {
            emit,
            formatDryRunDropReason,
            formatPageKindLabel,
            isLoadingCoverage,
            coverageError,
            notebooks,
            selectedFileId,
            startDate,
            offsetPages,
            maxPages,
            isRunningDryRun,
            dryRunError,
            dryRunResult,
            dryRunVerdict,
            expandedPages,
            expandedOps,
            keptOpsCount,
            droppedOpsCount,
            coveragePercent,
            coverageBadgeClass,
            formatResolvedCitation,
            togglePageText,
            toggleOpDraft,
            loadCoverage,
            handleDryRun,
            dryRunNotebook,
            handleNextSlice,
        };
    },
    template: `
        <section aria-label="Wiki Diagnostics"
            class="bg-white border border-stone-200/80 rounded-xl p-4 shadow-sm space-y-4">
            <div class="flex items-start justify-between gap-2">
                <div class="min-w-0">
                    <h3 class="text-xs font-semibold text-slate-900">Wiki Diagnostics</h3>
                    <p class="text-xs text-stone-500 mt-0.5">
                        See which transcribed notebooks are cited in your wiki, and test what the AI would generate from any slice without saving.
                    </p>
                </div>
                <div class="flex items-center gap-2 shrink-0">
                    <button type="button" @click="loadCoverage" :disabled="isLoadingCoverage"
                        class="px-2.5 py-1 rounded-md text-xs font-medium bg-white border border-stone-200 text-slate-700 hover:bg-stone-50 disabled:opacity-50 transition-colors">
                        {{ isLoadingCoverage ? 'Refreshing…' : 'Refresh' }}
                    </button>
                    <button type="button" @click="emit('close')" aria-label="Close diagnostics"
                        class="text-stone-400 hover:text-slate-700 px-1.5 py-0.5 rounded text-sm leading-none transition-colors">
                        &times;
                    </button>
                </div>
            </div>

            <!-- Coverage Table -->
            <div v-if="coverageError"
                class="rounded-lg bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-800">
                {{ coverageError }}
            </div>
            <div v-else-if="isLoadingCoverage && notebooks.length === 0"
                class="text-xs text-stone-500 py-2">
                Loading notebook coverage…
            </div>
            <div v-else-if="notebooks.length === 0"
                class="text-xs text-stone-500 py-2">
                No transcribed notebooks found yet.
            </div>
            <div v-else class="overflow-x-auto border border-stone-200/80 rounded-lg">
                <table class="w-full text-left border-collapse text-xs">
                    <thead>
                        <tr class="bg-stone-50 border-b border-stone-200/80 text-[11px] font-medium text-stone-500">
                            <th class="py-2 px-3">Notebook</th>
                            <th class="py-2 px-3 whitespace-nowrap">Cited / OCR</th>
                            <th class="hidden sm:table-cell py-2 px-3 whitespace-nowrap">Avg Chars</th>
                            <th class="hidden md:table-cell py-2 px-3">Cited Wiki Pages</th>
                            <th class="py-2 px-3 text-right">Inspect</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-stone-100">
                        <tr v-for="nb in notebooks" :key="nb.file_id"
                            :class="selectedFileId === nb.file_id ? 'bg-stone-50/90' : 'hover:bg-stone-50/50'">
                            <td class="py-2 px-3 max-w-[140px] sm:max-w-[220px]">
                                <button type="button"
                                    @click="emit('open-file', { id: nb.file_id })"
                                    class="font-medium text-slate-800 hover:text-slate-950 hover:underline truncate block max-w-full text-left"
                                    :title="nb.file_name + ' (#' + nb.file_id + ')'">
                                    {{ nb.file_name || ('#' + nb.file_id) }}
                                </button>
                                <span class="text-[10px] text-stone-400 font-mono">#{{ nb.file_id }}</span>
                            </td>
                            <td class="py-2 px-3 whitespace-nowrap">
                                <span :class="coverageBadgeClass(nb)"
                                    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-medium">
                                    {{ nb.cited_pages }}/{{ nb.ocr_pages }} ({{ coveragePercent(nb) }}%)
                                </span>
                            </td>
                            <td class="hidden sm:table-cell py-2 px-3 whitespace-nowrap text-stone-600 tabular-nums">
                                {{ nb.avg_chars_per_page }}
                            </td>
                            <td class="hidden md:table-cell py-2 px-3">
                                <div v-if="nb.cited_slugs.length > 0" class="flex flex-wrap gap-1">
                                    <button v-for="slug in nb.cited_slugs.slice(0, 3)" :key="slug"
                                        type="button" @click="emit('select-slug', slug)"
                                        class="px-1.5 py-0.5 rounded bg-white border border-stone-200 hover:border-slate-300 text-[11px] text-slate-700 transition-colors">
                                        {{ slug }}
                                    </button>
                                    <span v-if="nb.cited_slugs.length > 3"
                                        class="text-[11px] text-stone-400 self-center">
                                        +{{ nb.cited_slugs.length - 3 }}
                                    </span>
                                </div>
                                <span v-else class="text-stone-400">—</span>
                            </td>
                            <td class="py-2 px-3 text-right whitespace-nowrap">
                                <button type="button" @click="dryRunNotebook(nb.file_id)"
                                    :disabled="isRunningDryRun"
                                    class="px-2.5 py-1 rounded-md text-[11px] font-medium bg-white border border-stone-200 text-slate-700 hover:bg-stone-100 disabled:opacity-50 transition-colors">
                                    Dry-Run
                                </button>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- Dry-Run Compile Controls -->
            <form @submit.prevent="handleDryRun"
                class="rounded-lg bg-stone-50 border border-stone-200/80 p-3 space-y-3">
                <div class="flex flex-wrap items-end gap-2.5">
                    <label class="flex flex-col gap-1 min-w-[180px] flex-1">
                        <span class="text-[11px] font-medium text-stone-600">Notebook</span>
                        <select v-model="selectedFileId"
                            class="px-2.5 py-1.5 rounded-lg text-xs bg-white border border-stone-200 text-slate-800 focus:outline-none focus:border-slate-400">
                            <option value="">All notebooks (chronological)</option>
                            <option v-for="nb in notebooks" :key="nb.file_id" :value="nb.file_id">
                                {{ nb.file_name }} ({{ nb.ocr_pages }}p)
                            </option>
                        </select>
                    </label>
                    <label class="flex flex-col gap-1">
                        <span class="text-[11px] font-medium text-stone-600">Start date</span>
                        <input type="date" v-model="startDate"
                            class="px-2.5 py-1.5 rounded-lg text-xs bg-white border border-stone-200 text-slate-800 focus:outline-none focus:border-slate-400" />
                    </label>
                    <label class="flex flex-col gap-1 w-20">
                        <span class="text-[11px] font-medium text-stone-600">Offset</span>
                        <input type="number" min="0" v-model.number="offsetPages"
                            class="px-2.5 py-1.5 rounded-lg text-xs bg-white border border-stone-200 text-slate-800 focus:outline-none focus:border-slate-400" />
                    </label>
                    <label class="flex flex-col gap-1 w-20">
                        <span class="text-[11px] font-medium text-stone-600">Pages</span>
                        <input type="number" min="1" max="20" v-model.number="maxPages"
                            class="px-2.5 py-1.5 rounded-lg text-xs bg-white border border-stone-200 text-slate-800 focus:outline-none focus:border-slate-400" />
                    </label>
                    <div class="flex items-center gap-2">
                        <button type="submit" :disabled="isRunningDryRun"
                            class="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50 transition-colors">
                            {{ isRunningDryRun ? 'Running…' : 'Run Dry-Run' }}
                        </button>
                        <button v-if="dryRunResult && dryRunResult.pages_sent.length > 0"
                            type="button" @click="handleNextSlice" :disabled="isRunningDryRun"
                            class="px-2.5 py-1.5 rounded-lg text-xs font-medium bg-white border border-stone-200 text-slate-700 hover:bg-stone-100 disabled:opacity-50 transition-colors">
                            Next Slice &rarr;
                        </button>
                    </div>
                </div>

                <div v-if="dryRunError"
                    class="rounded-md bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-800">
                    {{ dryRunError }}
                </div>

                <!-- Dry-Run Output -->
                <div v-if="dryRunResult" class="space-y-3 pt-2 border-t border-stone-200/80">
                    <!-- Plain-English Verdict -->
                    <div v-if="dryRunVerdict"
                        :class="{
                            'bg-emerald-50 border-emerald-200 text-emerald-900': dryRunVerdict.tone === 'ok',
                            'bg-amber-50 border-amber-200 text-amber-900': dryRunVerdict.tone === 'warn',
                            'bg-white border-stone-200 text-stone-700': dryRunVerdict.tone === 'neutral',
                        }"
                        class="rounded-lg border px-3 py-2 text-xs flex flex-wrap items-center justify-between gap-2">
                        <span>{{ dryRunVerdict.text }}</span>
                        <span class="text-[11px] opacity-75 shrink-0">{{ dryRunResult.elapsed_ms }} ms</span>
                    </div>

                    <!-- Source Pages Read by AI -->
                    <div v-if="dryRunResult.pages_sent.length > 0" class="space-y-1.5">
                        <div class="text-[11px] font-semibold text-stone-500 uppercase tracking-wide">
                            Source Pages Read by AI ({{ dryRunResult.pages_sent.length }})
                        </div>
                        <div class="space-y-1.5">
                            <div v-for="p in dryRunResult.pages_sent"
                                :key="p.file_id + ':' + p.page_index + ':' + p.source_id"
                                class="bg-white border border-stone-200/70 rounded-md px-2.5 py-2 text-xs space-y-1.5">
                                <div class="flex flex-wrap items-center justify-between gap-2">
                                    <div class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 min-w-0">
                                        <span class="font-mono text-[11px] font-semibold text-slate-700">
                                            {{ p.source_id || '?' }}
                                        </span>
                                        <span class="text-[11px] text-stone-500 tabular-nums">
                                            {{ p.page_date || 'undated' }}
                                        </span>
                                        <button type="button"
                                            @click="emit('open-file', { id: p.file_id, pageIndex: p.page_index })"
                                            class="font-medium text-slate-800 hover:underline">
                                            {{ p.file_path }} p.{{ p.page_index + 1 }}
                                        </button>
                                        <span class="text-[11px] text-stone-400">({{ p.chars }} chars)</span>
                                    </div>
                                    <button v-if="p.text_content"
                                        type="button"
                                        @click="togglePageText(p.file_id + ':' + p.page_index)"
                                        class="text-[11px] font-medium text-slate-600 hover:text-slate-900 underline shrink-0">
                                        {{ expandedPages[p.file_id + ':' + p.page_index] ? 'Hide OCR' : 'Show OCR' }}
                                    </button>
                                </div>
                                <p v-if="!expandedPages[p.file_id + ':' + p.page_index]"
                                    class="text-stone-600 truncate">
                                    {{ p.snippet }}
                                </p>
                                <pre v-else
                                    class="whitespace-pre-wrap break-words font-sans text-xs text-slate-700 bg-stone-50 border border-stone-200/70 rounded p-2.5 max-h-60 overflow-y-auto">{{ p.text_content }}</pre>
                            </div>
                        </div>
                    </div>

                    <!-- Existing Wiki Pages Given as Context -->
                    <div v-if="dryRunResult.candidate_slugs.length > 0" class="flex flex-wrap items-center gap-1.5">
                        <span class="text-[11px] font-semibold text-stone-500 uppercase tracking-wide mr-1">
                            Existing Wiki Pages Given as Context:
                        </span>
                        <button v-for="slug in dryRunResult.candidate_slugs" :key="slug"
                            type="button" @click="emit('select-slug', slug)"
                            class="px-2 py-0.5 rounded-md bg-white border border-stone-200 hover:border-slate-300 text-[11px] text-slate-700 transition-colors">
                            {{ slug }}
                        </button>
                    </div>

                    <!-- What the AI Would Write -->
                    <div v-if="dryRunResult.ops.length > 0" class="space-y-1.5">
                        <div class="text-[11px] font-semibold text-stone-500 uppercase tracking-wide">
                            What the AI Would Write ({{ keptOpsCount }} saved, {{ droppedOpsCount }} skipped)
                        </div>
                        <div v-for="op in dryRunResult.ops" :key="op.slug + ':' + op.title"
                            class="rounded-md bg-white border border-stone-200/80 p-3 space-y-2 text-xs">
                            <div class="flex flex-wrap items-center justify-between gap-2">
                                <div class="flex flex-wrap items-center gap-2 min-w-0">
                                    <span :class="op.drop_reason ? 'bg-amber-50 text-amber-800 border-amber-200' : 'bg-emerald-50 text-emerald-700 border-emerald-200'"
                                        class="px-2 py-0.5 rounded border text-[11px] font-medium">
                                        {{ op.drop_reason ? formatDryRunDropReason(op.drop_reason) : 'Would save' }}
                                    </span>
                                    <span class="font-semibold text-slate-900">{{ op.title || op.slug }}</span>
                                    <span class="font-mono text-[11px] text-stone-400">{{ op.slug }}</span>
                                    <span class="px-1.5 py-0.5 rounded bg-stone-100 text-[10px] text-stone-600">
                                        {{ formatPageKindLabel(op.page_kind) }}
                                    </span>
                                    <span class="text-[11px] text-stone-400">({{ op.body_chars }} chars)</span>
                                </div>
                                <button v-if="op.body_md"
                                    type="button"
                                    @click="toggleOpDraft(op.slug + ':' + op.title)"
                                    class="text-[11px] font-medium text-slate-600 hover:text-slate-900 underline shrink-0">
                                    {{ expandedOps[op.slug + ':' + op.title] ? 'Hide draft' : 'Show draft' }}
                                </button>
                            </div>
                            <p v-if="op.summary" class="text-stone-600">{{ op.summary }}</p>
                            <pre v-if="op.body_md && expandedOps[op.slug + ':' + op.title]"
                                class="whitespace-pre-wrap break-words font-sans text-xs text-slate-700 bg-stone-50 border border-stone-200/70 rounded p-2.5 max-h-64 overflow-y-auto">{{ op.body_md }}</pre>
                            <div v-if="op.resolved_source_keys.length > 0 || op.dropped_source_keys.length > 0"
                                class="flex flex-wrap items-center gap-1.5 text-[11px]">
                                <span class="text-stone-400 mr-0.5">Cited:</span>
                                <span v-for="refKey in op.resolved_source_keys" :key="'r:' + refKey"
                                    class="px-1.5 py-0.5 rounded bg-stone-100 text-stone-700">
                                    {{ formatResolvedCitation(refKey) }}
                                </span>
                                <span v-for="badKey in op.dropped_source_keys" :key="'d:' + badKey"
                                    class="px-1.5 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200">
                                    Unrecognized citation: {{ badKey }}
                                </span>
                            </div>
                        </div>
                    </div>
                </div>
            </form>
        </section>
    `,
};
