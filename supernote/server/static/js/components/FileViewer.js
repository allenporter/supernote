import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import {
    convertNoteToPng,
    downloadFile,
    fetchAiStatus,
    fetchDownloadUrl,
    fetchNoteMetadata,
    fetchSummaries,
    fetchTranscript,
    searchFiles,
} from '../api/client.js';
import { useCanvasScrollSync } from '../composables/useCanvasScrollSync.js';
import { showToast } from '../composables/useToast.js';
import { getErrorMessage } from '../utils/format.js';
import {
    buildDisplayTranscriptPages,
    formatPageStyle,
    MAX_TEXT_PREVIEW_BYTES,
    normalizeTranscriptPages,
    resolveFileCategory,
    resolveFileExt,
} from './viewer/noteMeta.js';
import ViewerMediaPreview from './viewer/ViewerMediaPreview.js';
import ViewerSidePanel from './viewer/ViewerSidePanel.js';
import ViewerToolbar from './viewer/ViewerToolbar.js';

export default {
    name: 'FileViewer',
    components: {
        ViewerToolbar,
        ViewerMediaPreview,
        ViewerSidePanel,
    },
    props: ['file', 'initialPage', 'pageJumpSeq'],
    emits: ['close', 'page-change', 'open-file', 'search'],
    /**
     * @param {Record<string, any>} props
     * @param {{ emit: (event: string, ...args: any[]) => void }} context
     */
    setup(props, { emit }) {
        const pages = ref([]);
        const previewUrl = ref(null);
        const textContent = ref('');
        const isTextTooLarge = ref(false);
        const isLoading = ref(true);
        const error = ref(null);
        const downloading = ref(false);

        const activeRightTab = ref('transcription'); // 'transcription' | 'insights'
        const isMobileSidePanelOpen = ref(false);
        /** @type {import('vue').Ref<TranscriptPage[]>} */
        const transcriptPages = ref([]);
        /** @type {import('vue').Ref<NoteMetadata | null>} */
        const noteMetadata = ref(null);
        /** @type {import('vue').Ref<Record<string, any>[]>} */
        const realSummaries = ref([]);
        /** @type {import('vue').Ref<AiStatus | null>} */
        const aiStatus = ref(null);
        const isLoadingTranscript = ref(false);

        const {
            activePageIndex,
            leftScrollPane,
            sidePanelRef,
            zoomPercent,
            canvasMaxWidthPx,
            zoomIn,
            zoomOut,
            resetZoom,
            prevPage,
            nextPage,
            jumpToTargetPage,
            scrollToCanvasPage,
            scrollTranscriptToPage,
            handlePageImageLoad,
            updateActivePageFromScroll,
            setupPageObserver,
            teardownPageObserver,
            clearPendingTargetPage,
        } = useCanvasScrollSync({ pages, transcriptPages });

        let activeLoadSeq = 0;

        const fileExt = computed(() => resolveFileExt(props.file));
        const fileCategory = computed(() => resolveFileCategory(fileExt.value));

        const showSidePanel = computed(() => {
            return (
                fileCategory.value === 'note' ||
                transcriptPages.value.length > 0 ||
                realSummaries.value.length > 0
            );
        });

        const pageMetaByIndex = computed(() => {
            /** @type {Map<number, NotePageMeta>} */
            const map = new Map();
            const list = noteMetadata.value?.pages;
            if (Array.isArray(list)) {
                for (const item of list) {
                    if (typeof item.pageIndex === 'number') {
                        map.set(item.pageIndex, item);
                    }
                }
            }
            return map;
        });

        const transcriptByIndex = computed(() => {
            /** @type {Map<number, TranscriptPage>} */
            const map = new Map();
            for (const item of transcriptPages.value) {
                if (typeof item.pageIndex === 'number') {
                    map.set(item.pageIndex, item);
                }
            }
            return map;
        });

        const linksByPageIndex = computed(() => {
            /** @type {Map<number, NoteLink[]>} */
            const map = new Map();
            const list = noteMetadata.value?.links;
            if (Array.isArray(list)) {
                for (const lk of list) {
                    if (typeof lk.pageIndex === 'number') {
                        const arr = map.get(lk.pageIndex) || [];
                        arr.push(lk);
                        map.set(lk.pageIndex, arr);
                    }
                }
            }
            return map;
        });

        /**
         * @param {number} pageIdx
         */
        const getPageMeta = (pageIdx) => pageMetaByIndex.value.get(pageIdx) || null;

        /**
         * @param {number} pageIdx
         */
        const getPageRightMeta = (pageIdx) => {
            const meta = getPageMeta(pageIdx);
            const date = meta?.date || transcriptByIndex.value.get(pageIdx)?.date || null;
            const styleLabel = formatPageStyle(meta?.style);
            const parts = [date, styleLabel].filter(Boolean);
            return parts.length > 0 ? parts.join(' · ') : 'Supernote Canvas';
        };

        const displayTranscriptPages = computed(() =>
            buildDisplayTranscriptPages(
                transcriptPages.value,
                noteMetadata.value,
                pageMetaByIndex.value,
                linksByPageIndex.value,
            ),
        );

        /**
         * @param {string} keyword
         */
        const handleKeywordClick = (keyword) => {
            const trimmed = String(keyword || '').trim();
            if (!trimmed) return;
            isMobileSidePanelOpen.value = false;
            emit('search', trimmed);
        };

        /**
         * @param {string | number} fileId
         * @param {string} fileName
         * @param {number | null | undefined} targetPageIndex
         */
        const buildLinkedFilePayload = (fileId, fileName, targetPageIndex) => ({
            id: String(fileId),
            name: fileName || undefined,
            extension: fileName?.includes('.')
                ? (fileName.split('.').pop() ?? '').toLowerCase()
                : 'note',
            isDirectory: false,
            pageIndex: typeof targetPageIndex === 'number' ? targetPageIndex : 0,
        });

        /**
         * @param {NoteLink | null | undefined} link
         */
        const handleNoteLinkClick = async (link) => {
            if (!link) return;
            if (link.linkType === 'web' && link.target) {
                window.open(link.target, '_blank', 'noopener,noreferrer');
                return;
            }
            const targetBaseName = link.target ? (link.target.split('/').pop() || '').trim() : '';
            if (link.targetFileId && String(link.targetFileId) !== String(props.file?.id)) {
                isMobileSidePanelOpen.value = false;
                emit(
                    'open-file',
                    buildLinkedFilePayload(link.targetFileId, targetBaseName, link.targetPageIndex),
                );
                return;
            }
            if (link.linkType === 'file' && targetBaseName) {
                isMobileSidePanelOpen.value = false;
                try {
                    const matches = await searchFiles(targetBaseName);
                    const exact = Array.isArray(matches)
                        ? matches.find((m) => (m.name || m.fileName) === targetBaseName) ||
                          matches[0]
                        : null;
                    if (exact?.id) {
                        const fileName = exact.name || exact.fileName || targetBaseName;
                        emit(
                            'open-file',
                            buildLinkedFilePayload(exact.id, fileName, link.targetPageIndex),
                        );
                        return;
                    }
                } catch {
                    // Fall back to opening search modal with the target filename
                }
                emit('search', targetBaseName);
                return;
            }
            if (typeof link.targetPageIndex === 'number') {
                scrollToCanvasPage(link.targetPageIndex);
                scrollTranscriptToPage(link.targetPageIndex);
                isMobileSidePanelOpen.value = false;
            }
        };

        const loadingMessage = computed(() => {
            switch (fileCategory.value) {
                case 'note':
                    return 'Rendering notebook pages...';
                case 'image':
                    return 'Loading image preview...';
                case 'pdf':
                    return 'Loading PDF document...';
                case 'text':
                    return 'Loading text content...';
                default:
                    return 'Loading file...';
            }
        });

        const handleDownload = async () => {
            if (!props.file || downloading.value) return;
            downloading.value = true;
            try {
                await downloadFile(props.file.id);
            } catch (e) {
                showToast(`Failed to download: ${getErrorMessage(e)}`);
            } finally {
                downloading.value = false;
            }
        };

        /**
         * @param {string | number} fileId
         * @param {number} seq
         * @param {{ preserveMetaOnNull?: boolean }} [options={}]
         * @returns {Promise<boolean>}
         */
        const fetchAndApplyNoteInsights = async (
            fileId,
            seq,
            { preserveMetaOnNull = false } = {},
        ) => {
            const id = String(fileId);
            isLoadingTranscript.value = true;
            /** @type {[any[], Record<string, any>[], NoteMetadata | null]} */
            const [rawPages, summariesData, metaData] = await Promise.all([
                fetchTranscript(id).catch(() => []),
                fetchSummaries(id).catch(() => []),
                fetchNoteMetadata(id).catch(() => null),
            ]);
            if (seq !== activeLoadSeq) return false;

            transcriptPages.value = normalizeTranscriptPages(rawPages);
            if (!preserveMetaOnNull || metaData) {
                noteMetadata.value = metaData;
            }
            if (summariesData && Array.isArray(summariesData)) {
                realSummaries.value = summariesData.filter(
                    (s) => (s.dataSource || '').toUpperCase() !== 'OCR',
                );
            }
            return true;
        };

        const loadFileContent = async () => {
            if (!props.file) return;
            const seq = ++activeLoadSeq;

            teardownPageObserver();
            clearPendingTargetPage();
            pages.value = [];
            previewUrl.value = null;
            textContent.value = '';
            isTextTooLarge.value = false;
            transcriptPages.value = [];
            noteMetadata.value = null;
            activePageIndex.value =
                typeof props.initialPage === 'number' && props.initialPage >= 0
                    ? props.initialPage
                    : 0;
            realSummaries.value = [];
            isLoading.value = true;
            error.value = null;

            const category = fileCategory.value;

            try {
                if (category === 'note') {
                    const pngPages = await convertNoteToPng(props.file.id);
                    if (seq !== activeLoadSeq) return;
                    pages.value = pngPages;
                } else if (category === 'image') {
                    const signedUrl = await fetchDownloadUrl(props.file.id);
                    if (seq !== activeLoadSeq) return;
                    previewUrl.value = signedUrl;
                } else if (category === 'pdf') {
                    const signedUrl = await fetchDownloadUrl(props.file.id);
                    if (seq !== activeLoadSeq) return;
                    previewUrl.value = signedUrl.includes('?')
                        ? `${signedUrl}&inline=1`
                        : `${signedUrl}?inline=1`;
                } else if (category === 'text') {
                    const fileSize = Number(props.file.size || 0);
                    if (fileSize > MAX_TEXT_PREVIEW_BYTES) {
                        isTextTooLarge.value = true;
                    } else {
                        const signedUrl = await fetchDownloadUrl(props.file.id);
                        if (seq !== activeLoadSeq) return;
                        const resp = await fetch(signedUrl);
                        if (!resp.ok) {
                            throw new Error(`Failed to fetch text file (${resp.status})`);
                        }
                        const contentLength = Number(resp.headers.get('Content-Length') || 0);
                        if (contentLength > MAX_TEXT_PREVIEW_BYTES) {
                            if (resp.body) {
                                await resp.body.cancel().catch(() => {});
                            }
                            isTextTooLarge.value = true;
                        } else {
                            const txt = await resp.text();
                            if (seq !== activeLoadSeq) return;
                            textContent.value = txt;
                        }
                    }
                }

                if (category === 'note') {
                    const applied = await fetchAndApplyNoteInsights(props.file.id, seq);
                    if (!applied) return;
                    activeRightTab.value =
                        displayTranscriptPages.value.length === 0 && realSummaries.value.length > 0
                            ? 'insights'
                            : 'transcription';
                } else {
                    activeRightTab.value = 'transcription';
                }
            } catch (e) {
                if (seq !== activeLoadSeq) return;
                console.error('Failed to load file content:', e);
                error.value =
                    category === 'note'
                        ? 'Failed to render notebook pages.'
                        : `Failed to load file preview: ${getErrorMessage(e)}`;
            } finally {
                if (seq === activeLoadSeq) {
                    isLoading.value = false;
                    isLoadingTranscript.value = false;
                    if (category === 'note' && pages.value.length > 0) {
                        const initialTarget =
                            typeof props.initialPage === 'number' && props.initialPage >= 0
                                ? props.initialPage
                                : 0;
                        await jumpToTargetPage(initialTarget, { smooth: false });
                        await setupPageObserver();
                    } else if (typeof props.initialPage === 'number' && props.initialPage >= 0) {
                        await jumpToTargetPage(props.initialPage, { smooth: false });
                    }
                }
            }
        };

        const refreshInsights = async () => {
            if (!props.file) return;
            if (fileCategory.value !== 'note') {
                transcriptPages.value = [];
                realSummaries.value = [];
                noteMetadata.value = null;
                return;
            }
            const seq = activeLoadSeq;
            try {
                await fetchAndApplyNoteInsights(props.file.id, seq, { preserveMetaOnNull: true });
            } finally {
                if (seq === activeLoadSeq) {
                    isLoadingTranscript.value = false;
                }
            }
        };

        const handleDigestSync = () => {
            refreshInsights();
        };

        /**
         * @param {CustomEvent<any>} event
         */
        const handleFileSync = (event) => {
            if (!props.file) return;
            const entries = event?.detail?.data;
            if (Array.isArray(entries)) {
                const matchesFile = entries.some(
                    (item) =>
                        String(item.id) === String(props.file.id) ||
                        String(item.newId) === String(props.file.id) ||
                        item.messageType === 'STARTSYNC',
                );
                if (matchesFile) {
                    loadFileContent();
                }
            } else {
                loadFileContent();
            }
        };

        onMounted(() => {
            window.addEventListener('supernote:digest-sync', handleDigestSync);
            window.addEventListener('supernote:file-sync', handleFileSync);
            fetchAiStatus()
                .then((status) => {
                    aiStatus.value = status;
                })
                .catch(() => {});
            loadFileContent();
        });

        onUnmounted(() => {
            window.removeEventListener('supernote:digest-sync', handleDigestSync);
            window.removeEventListener('supernote:file-sync', handleFileSync);
        });

        watch(
            () => [props.file?.id, fileCategory.value],
            ([newId, newCategory], [oldId, oldCategory]) => {
                if (newId !== oldId) {
                    isMobileSidePanelOpen.value = false;
                }
                if (newId && (newId !== oldId || newCategory !== oldCategory)) {
                    loadFileContent();
                }
            },
        );

        watch(
            () => [props.initialPage, props.pageJumpSeq],
            ([newPage]) => {
                if (!isLoading.value && typeof newPage === 'number' && newPage >= 0) {
                    jumpToTargetPage(newPage, { smooth: true });
                }
            },
        );

        watch(activePageIndex, (newIdx) => {
            if (!isLoading.value && fileCategory.value === 'note' && pages.value.length > 0) {
                emit('page-change', newIdx);
            }
        });

        return {
            pages,
            previewUrl,
            textContent,
            isTextTooLarge,
            fileExt,
            fileCategory,
            showSidePanel,
            zoomPercent,
            canvasMaxWidthPx,
            zoomOut,
            zoomIn,
            resetZoom,
            prevPage,
            nextPage,
            loadingMessage,
            isLoading,
            error,
            downloading,
            handleDownload,
            isLoadingTranscript,
            activeRightTab,
            isMobileSidePanelOpen,
            transcriptPages,
            displayTranscriptPages,
            noteMetadata,
            pageMetaByIndex,
            linksByPageIndex,
            getPageMeta,
            getPageRightMeta,
            handleKeywordClick,
            handleNoteLinkClick,
            activePageIndex,
            leftScrollPane,
            sidePanelRef,
            scrollToCanvasPage,
            handlePageImageLoad,
            updateActivePageFromScroll,
            realSummaries,
            aiStatus,
        };
    },
    template: `
    <div class="bg-white h-[calc(100vh-8.5rem)] min-h-[480px] sm:min-h-[560px] rounded-2xl border border-stone-200/90 shadow-sm flex flex-col overflow-hidden relative animate-fade-in">
        <ViewerToolbar
            :file="file"
            :file-ext="fileExt"
            :file-category="fileCategory"
            :equipment="noteMetadata?.equipment || null"
            :page-count="pages.length"
            :active-page-index="activePageIndex"
            :zoom-percent="zoomPercent"
            :downloading="downloading"
            :show-side-panel="showSidePanel"
            :is-mobile-side-panel-open="isMobileSidePanelOpen"
            @close="$emit('close')"
            @prev-page="prevPage"
            @next-page="nextPage"
            @zoom-in="zoomIn"
            @zoom-out="zoomOut"
            @reset-zoom="resetZoom"
            @download="handleDownload"
            @toggle-side-panel="isMobileSidePanelOpen = !isMobileSidePanelOpen"
        />

        <!-- Main Split Workspace -->
        <div class="flex-1 flex overflow-hidden relative">
            <!-- Left / Main Pane: Document Canvas -->
            <div ref="leftScrollPane" @scroll.passive="updateActivePageFromScroll"
                class="flex-1 overflow-y-auto paper-surface p-4 sm:p-6 lg:p-8 flex flex-col">
                <div v-if="isLoading" class="flex flex-col items-center justify-center py-20 space-y-3 my-auto">
                    <div class="animate-spin rounded-full h-7 w-7 border-2 border-stone-300 border-t-slate-900"></div>
                    <p class="text-xs text-stone-500 font-mono">{{ loadingMessage }}</p>
                </div>

                <div v-else-if="error" class="bg-white border border-stone-200 p-6 rounded-2xl text-center text-xs text-stone-600 max-w-md mx-auto my-auto space-y-4 shadow-sm">
                    <p class="font-medium text-slate-900">{{ error }}</p>
                    <button @click="handleDownload" :disabled="downloading" type="button"
                        class="inline-flex items-center gap-2 px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-semibold transition-colors shadow-sm disabled:opacity-50">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"></path>
                        </svg>
                        Download File
                    </button>
                </div>

                <!-- Notebook (.note) Preview -->
                <template v-else-if="fileCategory === 'note'">
                    <div v-if="pages.length === 0" class="bg-white border border-stone-200/90 rounded-2xl p-8 flex flex-col items-center justify-center text-center max-w-md mx-auto space-y-2 my-auto shadow-sm">
                        <p class="text-sm font-bold text-slate-900">No page previews available</p>
                        <p class="text-xs text-stone-500 leading-relaxed">Page rendering may still be queued or disabled on this server. Check the panel on the right for transcripts and summaries.</p>
                    </div>

                    <div v-else class="w-full mx-auto space-y-6" :style="{ maxWidth: canvasMaxWidthPx + 'px' }">
                        <div v-for="(page, idx) in pages" :key="page.pageNo ?? idx"
                            :data-page-index="idx"
                            :class="activePageIndex === idx
                                ? 'ring-2 ring-slate-900/80 border-slate-900'
                                : 'border-stone-200/90'"
                            class="bg-white rounded-xl notebook-page-shadow border overflow-hidden transition-all">
                            <div class="border-b border-stone-100 px-3.5 py-1.5 bg-stone-50/70 flex justify-between items-center gap-2 text-[11px] text-stone-500 font-mono tabular-nums">
                                <div class="flex items-center gap-1.5 min-w-0">
                                    <span class="font-medium text-stone-600">Page {{ idx + 1 }} of {{ pages.length }}</span>
                                    <span v-if="getPageMeta(idx)?.hasFiveStar"
                                        class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200/80 text-[10px] font-semibold"
                                        title="Starred page">
                                        ★ Starred
                                    </span>
                                </div>
                                <span class="text-stone-500 shrink-0">{{ getPageRightMeta(idx) }}</span>
                            </div>
                            <img :src="page.url" loading="lazy" class="w-full h-auto min-h-[240px] sm:min-h-[360px] block bg-white" alt="Handwriting Page" @load="handlePageImageLoad" />
                        </div>
                    </div>
                </template>

                <!-- Image, PDF, Text, and Fallback Previews -->
                <ViewerMediaPreview
                    v-else
                    :file="file"
                    :file-ext="fileExt"
                    :file-category="fileCategory"
                    :preview-url="previewUrl"
                    :text-content="textContent"
                    :is-text-too-large="isTextTooLarge"
                    :downloading="downloading"
                    @download="handleDownload"
                />
            </div>

            <!-- Right Pane: OCR Transcript & Summaries -->
            <ViewerSidePanel
                v-if="showSidePanel"
                ref="sidePanelRef"
                :file-id="file?.id ?? null"
                :is-open-mobile="isMobileSidePanelOpen"
                :active-tab="activeRightTab"
                :active-page-index="activePageIndex"
                :has-canvas-pages="pages.length > 0"
                :is-loading-transcript="isLoadingTranscript"
                :transcript-pages="transcriptPages"
                :display-transcript-pages="displayTranscriptPages"
                :page-meta-by-index="pageMetaByIndex"
                :links-by-page-index="linksByPageIndex"
                :summaries="realSummaries"
                :ai-status="aiStatus"
                @update:active-tab="activeRightTab = $event"
                @close-mobile="isMobileSidePanelOpen = false"
                @select-page="scrollToCanvasPage"
                @keyword-click="handleKeywordClick"
                @link-click="handleNoteLinkClick"
            />
        </div>
    </div>
    `,
};
