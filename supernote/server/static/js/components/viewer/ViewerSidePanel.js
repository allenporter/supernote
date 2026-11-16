import { computed, nextTick, onUnmounted, ref, watch } from 'vue';
import { useModalEscape } from '../../composables/useModalEscape.js';
import { showToast } from '../../composables/useToast.js';
import { copyTextToClipboard } from '../../utils/clipboard.js';
import { renderMarkdown } from '../../utils/markdown.js';
import { formatContent, formatLinkLabel, hasCopyablePageText } from './noteMeta.js';

export default {
    name: 'ViewerSidePanel',
    props: {
        fileId: { type: [String, Number], default: null },
        isOpenMobile: { type: Boolean, default: false },
        activeTab: { type: String, default: 'transcription' },
        activePageIndex: { type: Number, default: 0 },
        hasCanvasPages: { type: Boolean, default: false },
        isLoadingTranscript: { type: Boolean, default: false },
        transcriptPages: { type: Array, default: () => [] },
        displayTranscriptPages: { type: Array, default: () => [] },
        pageMetaByIndex: { type: Map, default: () => new Map() },
        linksByPageIndex: { type: Map, default: () => new Map() },
        summaries: { type: Array, default: () => [] },
        aiStatus: { type: Object, default: null },
    },
    emits: ['update:activeTab', 'close-mobile', 'select-page', 'keyword-click', 'link-click'],
    /**
     * @param {{
     *   fileId: string | number | null,
     *   isOpenMobile: boolean,
     *   activeTab: string,
     *   activePageIndex: number,
     *   hasCanvasPages: boolean,
     *   isLoadingTranscript: boolean,
     *   transcriptPages: TranscriptPage[],
     *   displayTranscriptPages: TranscriptPage[],
     *   pageMetaByIndex: Map<number, NotePageMeta>,
     *   linksByPageIndex: Map<number, NoteLink[]>,
     *   summaries: NoteSummary[],
     *   aiStatus: AiStatus | null
     * }} props
     * @param {{
     *   expose: (exposed: Record<string, any>) => void,
     *   emit: (event: string, ...args: any[]) => void
     * }} context
     */
    setup(props, { expose, emit }) {
        /** @type {import('vue').Ref<HTMLElement | null>} */
        const transcriptScrollPane = ref(null);
        /** @type {import('vue').Ref<string | null>} */
        const copiedPageKey = ref(null);
        /** @type {ReturnType<typeof setTimeout> | null} */
        let copyResetTimer = null;

        function clearCopiedState() {
            if (copyResetTimer) {
                clearTimeout(copyResetTimer);
                copyResetTimer = null;
            }
            copiedPageKey.value = null;
        }

        /**
         * @param {number} pageIndex
         * @param {{ behavior?: ScrollBehavior }} [options={}]
         */
        function scrollToPage(pageIndex, options = {}) {
            const behavior = options.behavior || 'smooth';
            const pane = transcriptScrollPane.value;
            if (!pane) return;
            const cardEl = pane.querySelector(`[data-transcript-page="${pageIndex}"]`);
            if (!cardEl) return;

            if (pane.scrollHeight > pane.clientHeight) {
                const paneRect = pane.getBoundingClientRect();
                const cardRect = cardEl.getBoundingClientRect();
                if (cardRect.top < paneRect.top + 8 || cardRect.bottom > paneRect.bottom - 8) {
                    const targetTop = pane.scrollTop + (cardRect.top - paneRect.top) - 16;
                    pane.scrollTo({ top: Math.max(0, targetTop), behavior });
                }
            }
        }

        watch(
            () => props.activeTab,
            (tab) => {
                if (tab === 'transcription') {
                    nextTick(() => scrollToPage(props.activePageIndex));
                }
            },
        );

        watch(
            () => props.fileId,
            () => {
                clearCopiedState();
            },
        );

        useModalEscape(
            () => emit('close-mobile'),
            () => props.isOpenMobile,
        );

        onUnmounted(() => {
            clearCopiedState();
        });

        /**
         * @param {number} pageIdx
         */
        const getPageMeta = (pageIdx) => props.pageMetaByIndex.get(pageIdx) || null;
        /**
         * @param {number} pageIdx
         */
        const getPageKeywords = (pageIdx) => {
            const kws = getPageMeta(pageIdx)?.keywords;
            return Array.isArray(kws) ? kws : [];
        };
        /**
         * @param {number} pageIdx
         */
        const getPageLinks = (pageIdx) => props.linksByPageIndex.get(pageIdx) || [];
        /**
         * @param {NoteLink | null | undefined} link
         */
        const renderLinkLabel = (link) => formatLinkLabel(link, props.fileId);

        /**
         * @param {number} pageIndex
         */
        const isPageCopied = (pageIndex) => copiedPageKey.value === `page-${pageIndex}`;

        /**
         * @param {TranscriptPage} pageItem
         */
        async function copyPageTranscript(pageItem) {
            const text = formatContent(pageItem?.text);
            if (!text.trim()) return;
            const ok = await copyTextToClipboard(text);
            if (!ok) {
                showToast('Failed to copy transcript to clipboard', 'error');
                return;
            }
            const key = `page-${pageItem.pageIndex}`;
            copiedPageKey.value = key;
            if (copyResetTimer) clearTimeout(copyResetTimer);
            copyResetTimer = setTimeout(() => {
                if (copiedPageKey.value === key) {
                    copiedPageKey.value = null;
                }
                copyResetTimer = null;
            }, 2000);
        }

        const renderedSummaries = computed(() =>
            props.summaries.map((s, idx) => ({
                id: s.id || String(idx),
                name: s.name || null,
                html: renderMarkdown(s.content || ''),
            })),
        );

        expose({ scrollToPage });

        return {
            transcriptScrollPane,
            getPageMeta,
            getPageKeywords,
            getPageLinks,
            renderLinkLabel,
            formatContent,
            hasCopyablePageText,
            isPageCopied,
            copyPageTranscript,
            renderedSummaries,
        };
    },
    template: `
    <!-- Mobile Overlay Drawer Backdrop -->
    <div v-if="isOpenMobile" @click="$emit('close-mobile')" class="fixed inset-0 z-[60] bg-black/30 md:hidden"></div>

        <!-- Right Pane: Notebook Outline, OCR Transcript & Summaries -->
        <div :class="isOpenMobile ? 'translate-y-0 visible pointer-events-auto' : 'translate-y-full invisible pointer-events-none md:translate-y-0 md:visible md:pointer-events-auto'"
            class="fixed md:static inset-x-0 bottom-0 z-[70] md:z-10 h-[65vh] md:h-full w-full max-w-[100vw] md:max-w-none md:w-80 lg:w-96 border-t md:border-t-0 md:border-l border-stone-200/80 bg-white flex flex-col shadow-2xl md:shadow-none transition-transform duration-200 ease-in-out flex-shrink-0 rounded-t-2xl md:rounded-none">

            <!-- Segmented Tab Selector -->
            <div class="p-2 border-b border-stone-200/80 grid grid-cols-2 gap-1 bg-stone-100/70">
                <button @click="$emit('update:activeTab', 'transcription')" type="button"
                    :class="activeTab === 'transcription'
                        ? 'bg-white text-slate-900 shadow-sm font-semibold'
                        : 'text-stone-600 hover:text-slate-900 font-medium'"
                    class="py-1.5 px-2 rounded-lg text-xs transition-all flex items-center justify-center gap-1.5">
                    <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                    </svg>
                    <span>OCR Transcript</span>
                </button>
                <button @click="$emit('update:activeTab', 'insights')" type="button"
                    :class="activeTab === 'insights'
                        ? 'bg-white text-slate-900 shadow-sm font-semibold'
                        : 'text-stone-600 hover:text-slate-900 font-medium'"
                    class="py-1.5 px-2 rounded-lg text-xs transition-all flex items-center justify-center gap-1.5">
                    <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"></path>
                    </svg>
                    <span>Summaries</span>
                </button>
            </div>

            <!-- Tab 1: Real OCR Transcript -->
            <div v-if="activeTab === 'transcription'" ref="transcriptScrollPane" class="p-4 flex-1 overflow-y-auto space-y-3">
                <div class="flex items-center justify-between gap-2">
                    <div class="flex items-center gap-2 min-w-0">
                        <span class="text-[11px] font-bold text-stone-500 uppercase tracking-wider shrink-0">OCR Transcript</span>
                        <span v-if="aiStatus?.ocrEnabled && aiStatus?.model"
                            class="px-1.5 py-0.5 rounded bg-stone-100 text-[10px] font-mono text-stone-600 truncate"
                            :title="aiStatus.model">
                            {{ aiStatus.model }}
                        </span>
                        <span v-if="transcriptPages.length > 0" class="px-1.5 py-0.5 rounded bg-stone-100 text-[10px] font-mono text-stone-500 shrink-0 tabular-nums">
                            {{ transcriptPages.length }} {{ transcriptPages.length === 1 ? 'page' : 'pages' }}
                        </span>
                    </div>
                    <button @click="$emit('close-mobile')" type="button" class="md:hidden shrink-0 text-xs text-stone-500 hover:text-slate-700">Done</button>
                </div>

                <div v-if="isLoadingTranscript" class="py-12 text-center text-stone-500 text-xs">
                    <div class="animate-spin rounded-full h-5 w-5 border-2 border-stone-300 border-t-slate-900 mx-auto mb-2"></div>
                    Fetching OCR transcript...
                </div>

                <div v-else-if="displayTranscriptPages.length > 0" class="space-y-3">
                    <div v-for="pageItem in displayTranscriptPages" :key="pageItem.pageId || pageItem.pageIndex"
                        :data-transcript-page="pageItem.pageIndex"
                        :class="activePageIndex === pageItem.pageIndex
                            ? 'border-slate-900 ring-1 ring-slate-900/15 bg-stone-50/70'
                            : 'border-stone-200/80 bg-white'"
                        class="rounded-xl border overflow-hidden transition-all">
                        <div class="w-full px-3.5 py-2 border-b border-stone-100 flex items-center justify-between gap-2">
                            <button v-if="hasCanvasPages" type="button"
                                @click="$emit('select-page', pageItem.pageIndex)"
                                class="flex items-center justify-between gap-2 flex-1 min-w-0 text-left rounded-md -ml-1.5 px-1.5 py-0.5 hover:bg-stone-100/80 transition-colors cursor-pointer">
                                <div class="flex items-center gap-1.5 min-w-0">
                                    <span :class="activePageIndex === pageItem.pageIndex
                                        ? 'bg-slate-900 text-white'
                                        : 'bg-stone-200/80 text-stone-700'"
                                        class="px-2 py-0.5 rounded-md text-[11px] font-bold font-mono transition-colors tabular-nums shrink-0">
                                        Page {{ pageItem.pageIndex + 1 }}
                                    </span>
                                    <span v-if="pageItem.date || getPageMeta(pageItem.pageIndex)?.date" class="text-[11px] text-stone-500 font-mono tabular-nums truncate">
                                        {{ pageItem.date || getPageMeta(pageItem.pageIndex)?.date }}
                                    </span>
                                    <span v-if="getPageMeta(pageItem.pageIndex)?.hasFiveStar" class="text-xs text-amber-600 font-bold shrink-0" title="Starred page">★</span>
                                </div>
                                <span class="text-[10px] font-semibold text-stone-500 shrink-0">
                                    {{ activePageIndex === pageItem.pageIndex ? 'Viewing' : 'Jump →' }}
                                </span>
                            </button>
                            <div v-else class="flex items-center gap-1.5 min-w-0 flex-1">
                                <span class="px-2 py-0.5 rounded-md text-[11px] font-bold font-mono bg-stone-200/80 text-stone-700 tabular-nums shrink-0">
                                    Page {{ pageItem.pageIndex + 1 }}
                                </span>
                                <span v-if="pageItem.date || getPageMeta(pageItem.pageIndex)?.date" class="text-[11px] text-stone-500 font-mono tabular-nums truncate">
                                    {{ pageItem.date || getPageMeta(pageItem.pageIndex)?.date }}
                                </span>
                                <span v-if="getPageMeta(pageItem.pageIndex)?.hasFiveStar" class="text-xs text-amber-600 font-bold shrink-0" title="Starred page">★</span>
                            </div>

                            <button v-if="hasCopyablePageText(pageItem)"
                                type="button"
                                @click="copyPageTranscript(pageItem)"
                                :data-copy-page="pageItem.pageIndex"
                                :aria-label="isPageCopied(pageItem.pageIndex) ? ('Copied Page ' + (pageItem.pageIndex + 1) + ' transcript') : ('Copy Page ' + (pageItem.pageIndex + 1) + ' transcript')"
                                :title="isPageCopied(pageItem.pageIndex) ? 'Copied!' : ('Copy Page ' + (pageItem.pageIndex + 1) + ' transcript')"
                                :class="isPageCopied(pageItem.pageIndex)
                                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                                    : 'bg-white hover:bg-stone-100 text-stone-600 hover:text-slate-900 border-stone-200/90'"
                                class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[10px] font-semibold transition-colors shrink-0 cursor-pointer">
                                <svg v-if="isPageCopied(pageItem.pageIndex)" class="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.25" d="M5 13l4 4L19 7"></path>
                                </svg>
                                <svg v-else class="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path>
                                </svg>
                                <span>{{ isPageCopied(pageItem.pageIndex) ? 'Copied' : 'Copy' }}</span>
                            </button>
                        </div>

                        <!-- Per-Page Keywords & Outgoing Links -->
                        <div v-if="getPageKeywords(pageItem.pageIndex).length > 0 || getPageLinks(pageItem.pageIndex).length > 0"
                            class="px-3.5 py-2 bg-stone-50/50 border-b border-stone-100 flex flex-wrap items-center gap-1.5">
                            <button v-for="kw in getPageKeywords(pageItem.pageIndex)" :key="'kw-' + pageItem.pageIndex + '-' + kw"
                                type="button"
                                @click.stop="$emit('keyword-click', kw)"
                                :title="'Search notebooks for #' + kw"
                                class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-50 hover:bg-amber-100/90 text-amber-900 border border-amber-200/80 text-[11px] font-mono font-semibold transition-colors cursor-pointer">
                                <span>#{{ kw }}</span>
                            </button>
                            <button v-for="(link, lIdx) in getPageLinks(pageItem.pageIndex)" :key="'lk-' + pageItem.pageIndex + '-' + lIdx"
                                type="button"
                                @click.stop="$emit('link-click', link)"
                                :title="link.target || renderLinkLabel(link)"
                                class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-sky-50 hover:bg-sky-100/90 text-sky-900 border border-sky-200/80 text-[11px] font-mono font-semibold transition-colors cursor-pointer">
                                <svg class="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"></path>
                                </svg>
                                <span class="truncate max-w-[180px]">{{ renderLinkLabel(link) }}</span>
                            </button>
                        </div>

                        <div v-if="pageItem.hasTranscript" class="p-3.5 font-mono text-xs text-slate-800 whitespace-pre-wrap leading-relaxed select-text">
                            <template v-if="pageItem.text">{{ formatContent(pageItem.text) }}</template>
                            <span v-else class="italic text-stone-500 font-sans">No text recognized on this page.</span>
                        </div>
                    </div>

                    <div v-if="transcriptPages.length === 0" class="bg-stone-50/80 p-4 rounded-xl border border-stone-200/70 text-center text-xs text-stone-500 leading-relaxed">
                        <template v-if="aiStatus && !aiStatus.ocrEnabled">
                            OCR is not enabled on this server. Configure an AI provider to automatically transcribe handwritten pages.
                        </template>
                        <template v-else>
                            No OCR transcript available for this notebook yet. Background processing may still be running.
                        </template>
                    </div>
                </div>

                <div v-else class="bg-stone-50/80 p-5 rounded-xl border border-stone-200/70 text-center text-xs text-stone-500 leading-relaxed">
                    <template v-if="aiStatus && !aiStatus.ocrEnabled">
                        OCR is not enabled on this server. Configure an AI provider to automatically transcribe handwritten pages.
                    </template>
                    <template v-else>
                        No OCR transcript available for this notebook yet. Background processing may still be running.
                    </template>
                </div>
            </div>

            <!-- Tab 2: Real Summaries -->
            <div v-if="activeTab === 'insights'" class="p-4 flex-1 overflow-y-auto space-y-3">
                <div class="flex items-center justify-between gap-2">
                    <h4 class="text-[11px] font-bold text-stone-500 uppercase tracking-wider truncate">Notebook Summaries</h4>
                    <button @click="$emit('close-mobile')" type="button" class="md:hidden shrink-0 text-xs text-stone-500 hover:text-slate-700">Done</button>
                </div>

                <div v-if="renderedSummaries.length > 0" class="space-y-3">
                    <div v-for="s in renderedSummaries" :key="s.id"
                        data-summary-card
                        class="p-3.5 bg-stone-50 rounded-xl border border-stone-200/80 text-xs text-slate-800 leading-relaxed select-text">
                        <p v-if="s.name" class="font-bold text-slate-900 mb-2">{{ s.name }}</p>
                        <div v-if="s.html" class="markdown-prose" v-html="s.html"></div>
                        <p v-else class="italic text-stone-500">No summary content.</p>
                    </div>
                </div>

                <div v-else class="bg-stone-50/80 p-5 rounded-xl border border-stone-200/70 text-center text-xs text-stone-500 leading-relaxed">
                    No summaries generated yet for this notebook.
                </div>
            </div>
        </div>
    `,
};
