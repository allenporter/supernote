import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue';
import { convertNoteToPng, fetchTranscript, fetchSummaries, fetchAiStatus, fetchDownloadUrl, downloadFile } from '../api/client.js';
import { showToast } from '../composables/useToast.js';
import { formatSize } from '../utils/format.js';

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg']);
const TEXT_EXTENSIONS = new Set(['txt', 'md', 'csv', 'json', 'yaml', 'yml', 'log']);
const MAX_TEXT_PREVIEW_BYTES = 2 * 1024 * 1024; // 2 MB
const ZOOM_STEPS = [75, 100, 125, 150];

export default {
    name: 'FileViewer',
    props: ['file', 'initialPage', 'pageJumpSeq'],
    emits: ['close', 'page-change'],
    setup(props, { emit }) {
        const pages = ref([]);
        const previewUrl = ref(null);
        const textContent = ref('');
        const isTextTooLarge = ref(false);
        const isLoading = ref(true);
        const error = ref(null);
        const downloading = ref(false);
        const zoomPercent = ref(100);

        const activeRightTab = ref('transcription'); // 'transcription' | 'insights'
        const isMobileSidePanelOpen = ref(false);
        const transcriptPages = ref([]);
        const activePageIndex = ref(0);
        const realSummaries = ref([]);
        const aiStatus = ref(null);
        const isLoadingTranscript = ref(false);

        const leftScrollPane = ref(null);
        const transcriptScrollPane = ref(null);
        let pageObserver = null;
        let isProgrammaticScroll = false;
        let programmaticScrollTimer = null;
        let pendingTargetPage = null;
        let pendingTargetTimer = null;
        let activeLoadSeq = 0;

        const fileExt = computed(() => {
            if (!props.file) return '';
            if (props.file.extension) return String(props.file.extension).toLowerCase();
            if (props.file.name && props.file.name.includes('.')) {
                return props.file.name.split('.').pop().toLowerCase();
            }
            return '';
        });

        const fileCategory = computed(() => {
            const ext = fileExt.value;
            if (ext === 'note') return 'note';
            if (IMAGE_EXTENSIONS.has(ext)) return 'image';
            if (ext === 'pdf') return 'pdf';
            if (TEXT_EXTENSIONS.has(ext)) return 'text';
            return 'unsupported';
        });

        const showSidePanel = computed(() => {
            return (
                fileCategory.value === 'note' ||
                transcriptPages.value.length > 0 ||
                realSummaries.value.length > 0
            );
        });

        const canvasMaxWidthPx = computed(() => {
            return Math.round(540 * (zoomPercent.value / 100));
        });

        const zoomOut = () => {
            const idx = ZOOM_STEPS.indexOf(zoomPercent.value);
            if (idx > 0) zoomPercent.value = ZOOM_STEPS[idx - 1];
        };

        const zoomIn = () => {
            const idx = ZOOM_STEPS.indexOf(zoomPercent.value);
            if (idx !== -1 && idx < ZOOM_STEPS.length - 1) {
                zoomPercent.value = ZOOM_STEPS[idx + 1];
            }
        };

        const resetZoom = () => {
            zoomPercent.value = 100;
        };

        const normalizeTranscriptPages = (rawPages) => {
            if (!Array.isArray(rawPages)) return [];
            return rawPages.map((p, idx) => ({
                pageIndex: typeof p.pageIndex === 'number'
                    ? p.pageIndex
                    : (typeof p.page_index === 'number' ? p.page_index : idx),
                pageId: p.pageId || p.page_id || `page-${idx}`,
                text: p.text ?? '',
                date: p.date || null
            }));
        };

        const clearPendingTargetPage = () => {
            pendingTargetPage = null;
            if (pendingTargetTimer) {
                clearTimeout(pendingTargetTimer);
                pendingTargetTimer = null;
            }
        };

        const armPendingTargetPage = (pageIndex) => {
            clearPendingTargetPage();
            pendingTargetPage = pageIndex;
            pendingTargetTimer = setTimeout(() => {
                pendingTargetPage = null;
                pendingTargetTimer = null;
            }, 2000);
        };

        const armProgrammaticScrollRelease = () => {
            if (programmaticScrollTimer) clearTimeout(programmaticScrollTimer);
            programmaticScrollTimer = setTimeout(() => {
                isProgrammaticScroll = false;
                programmaticScrollTimer = null;
            }, 180);
        };

        const scrollTranscriptToPage = (pageIndex, options = {}) => {
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
        };

        const scrollToCanvasPage = (pageIndex, options = {}) => {
            const behavior = options.behavior || 'smooth';
            if (!options.keepAnchor) {
                armPendingTargetPage(pageIndex);
            }
            activePageIndex.value = pageIndex;
            const pane = leftScrollPane.value;
            if (!pane) return;
            const pageEl = pane.querySelector(`[data-page-index="${pageIndex}"]`);
            if (!pageEl) return;

            isProgrammaticScroll = true;
            armProgrammaticScrollRelease();

            if (pane.scrollHeight > pane.clientHeight) {
                const paneRect = pane.getBoundingClientRect();
                const elRect = pageEl.getBoundingClientRect();
                const targetTop = pageIndex === 0 ? 0 : pane.scrollTop + (elRect.top - paneRect.top) - 16;
                pane.scrollTo({ top: Math.max(0, targetTop), behavior });
            } else if (pane.scrollTop !== 0) {
                pane.scrollTo({ top: 0, behavior: 'auto' });
            }
        };

        const prevPage = () => {
            if (activePageIndex.value > 0) {
                const target = activePageIndex.value - 1;
                scrollToCanvasPage(target);
                scrollTranscriptToPage(target);
            }
        };

        const nextPage = () => {
            if (activePageIndex.value < pages.value.length - 1) {
                const target = activePageIndex.value + 1;
                scrollToCanvasPage(target);
                scrollTranscriptToPage(target);
            }
        };

        const jumpToTargetPage = async (rawPageIndex, { smooth = false } = {}) => {
            if (typeof rawPageIndex !== 'number' || Number.isNaN(rawPageIndex) || rawPageIndex < 0) {
                return;
            }
            const maxPageIdx = pages.value.length > 0
                ? pages.value.length - 1
                : (transcriptPages.value.length > 0 ? transcriptPages.value.length - 1 : rawPageIndex);
            const targetIdx = Math.max(0, Math.min(rawPageIndex, maxPageIdx));
            const behavior = smooth ? 'smooth' : 'auto';

            activePageIndex.value = targetIdx;
            await nextTick();
            if (pages.value.length > 0) {
                scrollToCanvasPage(targetIdx, { behavior });
            }
            scrollTranscriptToPage(targetIdx, { behavior });
        };

        const handlePageImageLoad = () => {
            if (pendingTargetPage !== null) {
                scrollToCanvasPage(pendingTargetPage, { behavior: 'auto', keepAnchor: true });
                scrollTranscriptToPage(pendingTargetPage, { behavior: 'auto' });
            }
        };

        const updateActivePageFromScroll = () => {
            if (isProgrammaticScroll || pendingTargetPage !== null) {
                if (isProgrammaticScroll) armProgrammaticScrollRelease();
                return;
            }
            if (!leftScrollPane.value) return;
            const pane = leftScrollPane.value;
            const paneRect = pane.getBoundingClientRect();
            const cards = pane.querySelectorAll('[data-page-index]');
            if (!cards.length) return;

            let bestIdx = activePageIndex.value;
            let bestScore = -Infinity;

            cards.forEach((card) => {
                const idx = Number(card.getAttribute('data-page-index'));
                if (Number.isNaN(idx)) return;
                const rect = card.getBoundingClientRect();
                const visibleTop = Math.max(rect.top, paneRect.top);
                const visibleBottom = Math.min(rect.bottom, paneRect.bottom);
                const visibleHeight = Math.max(0, visibleBottom - visibleTop);
                if (visibleHeight > 0) {
                    const topOffset = Math.max(0, visibleTop - paneRect.top);
                    const score = visibleHeight - topOffset * 0.25;
                    if (score > bestScore) {
                        bestScore = score;
                        bestIdx = idx;
                    }
                }
            });

            if (bestScore > -Infinity && bestIdx !== activePageIndex.value) {
                activePageIndex.value = bestIdx;
                scrollTranscriptToPage(bestIdx);
            }
        };

        const teardownPageObserver = () => {
            if (pageObserver) {
                pageObserver.disconnect();
                pageObserver = null;
            }
        };

        const setupPageObserver = async () => {
            teardownPageObserver();
            await nextTick();
            if (!leftScrollPane.value || typeof IntersectionObserver === 'undefined') return;
            const cards = leftScrollPane.value.querySelectorAll('[data-page-index]');
            if (!cards.length) return;

            pageObserver = new IntersectionObserver(
                (entries) => {
                    if (isProgrammaticScroll || pendingTargetPage !== null) return;
                    let updated = false;
                    if (leftScrollPane.value) {
                        const paneRect = leftScrollPane.value.getBoundingClientRect();
                        if (paneRect.height > 0) {
                            updateActivePageFromScroll();
                            updated = true;
                        }
                    }
                    if (!updated) {
                        let bestEntry = null;
                        for (const entry of entries) {
                            if (entry.isIntersecting) {
                                if (!bestEntry || entry.intersectionRatio > bestEntry.intersectionRatio) {
                                    bestEntry = entry;
                                }
                            }
                        }
                        if (bestEntry) {
                            const idx = Number(bestEntry.target.getAttribute('data-page-index'));
                            if (!Number.isNaN(idx) && idx !== activePageIndex.value) {
                                activePageIndex.value = idx;
                                scrollTranscriptToPage(idx);
                            }
                        }
                    }
                },
                {
                    root: leftScrollPane.value,
                    threshold: [0, 0.15, 0.3, 0.5, 0.75, 1.0]
                }
            );

            cards.forEach((card) => pageObserver.observe(card));
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
                showToast("Failed to download: " + e.message);
            } finally {
                downloading.value = false;
            }
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
            activePageIndex.value = (typeof props.initialPage === 'number' && props.initialPage >= 0)
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
                    previewUrl.value = signedUrl.includes('?') ? `${signedUrl}&inline=1` : `${signedUrl}?inline=1`;
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

                // Fetch real OCR transcript & summaries from extended APIs
                isLoadingTranscript.value = true;
                const [rawPages, summariesData] = await Promise.all([
                    fetchTranscript(props.file.id).catch(() => []),
                    fetchSummaries(props.file.id).catch(() => [])
                ]);
                if (seq !== activeLoadSeq) return;

                transcriptPages.value = normalizeTranscriptPages(rawPages);

                if (summariesData && Array.isArray(summariesData)) {
                    realSummaries.value = summariesData.filter(s => (s.dataSource || '').toUpperCase() !== 'OCR');
                }
            } catch (e) {
                if (seq !== activeLoadSeq) return;
                console.error("Failed to load file content:", e);
                error.value = category === 'note'
                    ? "Failed to render notebook pages."
                    : `Failed to load file preview: ${e.message || 'Unknown error'}`;
            } finally {
                if (seq === activeLoadSeq) {
                    isLoading.value = false;
                    isLoadingTranscript.value = false;
                    if (category === 'note' && pages.value.length > 0) {
                        const initialTarget = (typeof props.initialPage === 'number' && props.initialPage >= 0)
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
            const seq = activeLoadSeq;
            isLoadingTranscript.value = true;
            try {
                const [rawPages, summariesData] = await Promise.all([
                    fetchTranscript(props.file.id).catch(() => []),
                    fetchSummaries(props.file.id).catch(() => [])
                ]);
                if (seq !== activeLoadSeq) return;

                transcriptPages.value = normalizeTranscriptPages(rawPages);

                if (summariesData && Array.isArray(summariesData)) {
                    realSummaries.value = summariesData.filter(s => (s.dataSource || '').toUpperCase() !== 'OCR');
                }
            } finally {
                if (seq === activeLoadSeq) {
                    isLoadingTranscript.value = false;
                }
            }
        };

        const handleDigestSync = () => {
            refreshInsights();
        };

        const handleFileSync = (event) => {
            if (!props.file) return;
            const entries = event?.detail?.data;
            if (Array.isArray(entries)) {
                const matchesFile = entries.some(item =>
                    String(item.id) === String(props.file.id) ||
                    String(item.newId) === String(props.file.id) ||
                    item.messageType === 'STARTSYNC'
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
            window.addEventListener('wheel', clearPendingTargetPage, { passive: true });
            window.addEventListener('touchstart', clearPendingTargetPage, { passive: true });
            window.addEventListener('pointerdown', clearPendingTargetPage, { passive: true });
            fetchAiStatus().then((status) => {
                aiStatus.value = status;
            }).catch(() => {});
            loadFileContent();
        });
        onUnmounted(() => {
            window.removeEventListener('supernote:digest-sync', handleDigestSync);
            window.removeEventListener('supernote:file-sync', handleFileSync);
            window.removeEventListener('wheel', clearPendingTargetPage);
            window.removeEventListener('touchstart', clearPendingTargetPage);
            window.removeEventListener('pointerdown', clearPendingTargetPage);
            teardownPageObserver();
            clearPendingTargetPage();
            if (programmaticScrollTimer) clearTimeout(programmaticScrollTimer);
        });
        watch(() => props.file?.id, (newId) => {
            if (newId) loadFileContent();
        });
        watch(
            () => [props.initialPage, props.pageJumpSeq],
            ([newPage]) => {
                if (!isLoading.value && typeof newPage === 'number' && newPage >= 0) {
                    jumpToTargetPage(newPage, { smooth: true });
                }
            }
        );
        watch(activeRightTab, (tab) => {
            if (tab === 'transcription') {
                nextTick(() => scrollTranscriptToPage(activePageIndex.value));
            }
        });
        watch(activePageIndex, (newIdx) => {
            if (!isLoading.value && fileCategory.value === 'note' && pages.value.length > 0) {
                emit('page-change', newIdx);
            }
        });

        const formatContent = (str) => {
            if (!str) return '';
            return str.replaceAll('\\n', '\n');
        };

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
            formatSize,
            isLoadingTranscript,
            activeRightTab,
            isMobileSidePanelOpen,
            transcriptPages,
            activePageIndex,
            leftScrollPane,
            transcriptScrollPane,
            scrollToCanvasPage,
            handlePageImageLoad,
            updateActivePageFromScroll,
            realSummaries,
            aiStatus,
            formatContent
        };
    },
    template: `
    <div class="bg-white h-[calc(100vh-8.5rem)] min-h-[480px] sm:min-h-[560px] rounded-2xl border border-stone-200/90 shadow-sm flex flex-col overflow-hidden relative animate-fade-in">
        <!-- Top Viewer Header Bar -->
        <div class="flex-none bg-white border-b border-stone-200/80 px-3 sm:px-4 py-2.5 flex items-center justify-between gap-2 sm:gap-3 z-20">
            <!-- Left: Back Button & File Title -->
            <div class="flex items-center gap-2 sm:gap-3 min-w-0">
                <button @click="$emit('close')" type="button" aria-label="Back to files" title="Back to files"
                    class="inline-flex items-center gap-1.5 p-2 sm:px-2.5 sm:py-1.5 rounded-lg text-xs font-semibold text-stone-600 hover:text-slate-900 bg-stone-100 hover:bg-stone-200/70 transition-colors shrink-0">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path>
                    </svg>
                    <span class="hidden sm:inline">Back</span>
                </button>
                <div class="min-w-0" :title="'ID: ' + (file?.id || '')">
                    <div class="flex items-center gap-2">
                        <h3 class="text-sm font-bold text-slate-900 truncate">{{ file?.name || 'Document Viewer' }}</h3>
                        <span v-if="fileExt" class="px-1.5 py-0.5 rounded bg-stone-100 text-stone-600 text-[10px] font-mono font-semibold uppercase tracking-wider shrink-0">
                            {{ fileExt }}
                        </span>
                    </div>
                    <p class="text-[11px] font-mono text-stone-500 tabular-nums truncate">
                        <span v-if="pages.length > 0">{{ pages.length }} {{ pages.length === 1 ? 'page' : 'pages' }}</span>
                        <span v-if="pages.length > 0 && formatSize(file?.size)"> · </span>
                        <span v-if="formatSize(file?.size)">{{ formatSize(file?.size) }}</span>
                    </p>
                </div>
            </div>

            <!-- Center: Notebook Page Stepper & Zoom Controls (Desktop) -->
            <div v-if="fileCategory === 'note' && pages.length > 0" class="hidden sm:flex items-center gap-2">
                <!-- Page Jumper -->
                <div class="flex items-center bg-stone-100 rounded-lg p-0.5 border border-stone-200/60">
                    <button @click="prevPage" :disabled="activePageIndex <= 0" type="button"
                        aria-label="Previous page"
                        class="p-1 rounded-md text-stone-600 hover:text-slate-900 hover:bg-white disabled:opacity-35 disabled:hover:bg-transparent transition-all"
                        title="Previous page">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path>
                        </svg>
                    </button>
                    <span class="px-2.5 text-xs font-mono font-medium text-slate-800 tabular-nums">
                        Page {{ activePageIndex + 1 }} / {{ pages.length }}
                    </span>
                    <button @click="nextPage" :disabled="activePageIndex >= pages.length - 1" type="button"
                        aria-label="Next page"
                        class="p-1 rounded-md text-stone-600 hover:text-slate-900 hover:bg-white disabled:opacity-35 disabled:hover:bg-transparent transition-all"
                        title="Next page">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                        </svg>
                    </button>
                </div>

                <!-- Zoom Control -->
                <div class="flex items-center bg-stone-100 rounded-lg p-0.5 border border-stone-200/60">
                    <button @click="zoomOut" :disabled="zoomPercent <= 75" type="button"
                        aria-label="Zoom out"
                        class="px-2 py-0.5 rounded-md text-xs font-mono font-bold text-stone-600 hover:text-slate-900 hover:bg-white disabled:opacity-35 transition-all"
                        title="Zoom out">−</button>
                    <button @click="resetZoom" type="button"
                        aria-label="Reset zoom"
                        class="px-2 py-0.5 text-[11px] font-mono font-medium text-stone-600 hover:text-slate-900 tabular-nums"
                        title="Reset zoom">
                        {{ zoomPercent }}%
                    </button>
                    <button @click="zoomIn" :disabled="zoomPercent >= 150" type="button"
                        aria-label="Zoom in"
                        class="px-2 py-0.5 rounded-md text-xs font-mono font-bold text-stone-600 hover:text-slate-900 hover:bg-white disabled:opacity-35 transition-all"
                        title="Zoom in">+</button>
                </div>
            </div>

            <!-- Right: Download & Mobile Insights Toggle -->
            <div class="flex items-center gap-1.5 sm:gap-2 shrink-0">
                <button @click="handleDownload" :disabled="downloading" type="button"
                    aria-label="Download file"
                    :title="downloading ? 'Downloading…' : 'Download'"
                    class="flex items-center gap-1.5 p-2 sm:px-3 sm:py-1.5 bg-stone-100 hover:bg-stone-200/80 text-slate-800 rounded-lg text-xs font-semibold transition-colors disabled:opacity-50 disabled:cursor-wait">
                    <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"></path>
                    </svg>
                    <span class="hidden sm:inline">{{ downloading ? 'Downloading…' : 'Download' }}</span>
                </button>
                <button v-if="showSidePanel" @click="isMobileSidePanelOpen = !isMobileSidePanelOpen" type="button"
                    class="md:hidden px-2.5 sm:px-3 py-1.5 bg-slate-900 text-white rounded-lg text-xs font-semibold">
                    {{ isMobileSidePanelOpen ? 'Hide Panel' : 'Transcript' }}
                </button>
            </div>
        </div>

        <!-- Mobile Notebook Secondary Control Bar -->
        <div v-if="fileCategory === 'note' && pages.length > 0"
            class="flex sm:hidden items-center justify-between px-3 py-1.5 bg-stone-50 border-b border-stone-200/80 gap-2 z-20">
            <!-- Mobile Page Stepper -->
            <div class="flex items-center bg-white rounded-lg p-0.5 border border-stone-200/80 shadow-sm">
                <button @click="prevPage" :disabled="activePageIndex <= 0" type="button"
                    aria-label="Previous page"
                    class="p-1 rounded-md text-stone-600 hover:text-slate-900 hover:bg-stone-100 disabled:opacity-35 transition-all">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path>
                    </svg>
                </button>
                <span class="px-2 text-[11px] font-mono font-medium text-slate-800 tabular-nums">
                    Page {{ activePageIndex + 1 }} / {{ pages.length }}
                </span>
                <button @click="nextPage" :disabled="activePageIndex >= pages.length - 1" type="button"
                    aria-label="Next page"
                    class="p-1 rounded-md text-stone-600 hover:text-slate-900 hover:bg-stone-100 disabled:opacity-35 transition-all">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                    </svg>
                </button>
            </div>

            <!-- Mobile Zoom Controls -->
            <div class="flex items-center bg-white rounded-lg p-0.5 border border-stone-200/80 shadow-sm">
                <button @click="zoomOut" :disabled="zoomPercent <= 75" type="button"
                    aria-label="Zoom out"
                    class="px-2 py-0.5 rounded-md text-xs font-mono font-bold text-stone-600 hover:text-slate-900 disabled:opacity-35 transition-all">−</button>
                <button @click="resetZoom" type="button"
                    aria-label="Reset zoom"
                    class="px-1.5 py-0.5 text-[11px] font-mono font-medium text-stone-600 hover:text-slate-900 tabular-nums">
                    {{ zoomPercent }}%
                </button>
                <button @click="zoomIn" :disabled="zoomPercent >= 150" type="button"
                    aria-label="Zoom in"
                    class="px-2 py-0.5 rounded-md text-xs font-mono font-bold text-stone-600 hover:text-slate-900 disabled:opacity-35 transition-all">+</button>
            </div>
        </div>

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
                            <div class="border-b border-stone-100 px-3.5 py-1.5 bg-stone-50/70 flex justify-between items-center text-[11px] text-stone-500 font-mono tabular-nums">
                                <span class="font-medium text-stone-600">Page {{ idx + 1 }} of {{ pages.length }}</span>
                                <span>Supernote Canvas</span>
                            </div>
                            <img :src="page.url" loading="lazy" class="w-full h-auto min-h-[240px] sm:min-h-[360px] block bg-white" alt="Handwriting Page" @load="handlePageImageLoad" />
                        </div>
                    </div>
                </template>

                <!-- Image Preview -->
                <template v-else-if="fileCategory === 'image'">
                    <div class="max-w-4xl w-full mx-auto my-auto flex items-center justify-center bg-white rounded-2xl notebook-page-shadow border border-stone-200/80 p-4 sm:p-6">
                        <img v-if="previewUrl" :src="previewUrl" :alt="file?.name || 'Image Preview'"
                            class="max-w-full max-h-[72vh] object-contain rounded-lg" />
                    </div>
                </template>

                <!-- PDF Preview -->
                <template v-else-if="fileCategory === 'pdf'">
                    <div class="max-w-5xl w-full mx-auto flex-1 flex flex-col min-h-[72vh]">
                        <iframe v-if="previewUrl" :src="previewUrl" :title="file?.name || 'PDF Preview'"
                            class="w-full flex-1 min-h-[72vh] h-full rounded-xl border border-stone-200 bg-white shadow-sm"></iframe>
                    </div>
                </template>

                <!-- Text / Markdown Preview -->
                <template v-else-if="fileCategory === 'text'">
                    <div v-if="isTextTooLarge" class="bg-white border border-stone-200 p-8 rounded-2xl shadow-sm text-center max-w-md mx-auto my-auto space-y-4">
                        <div class="w-12 h-12 bg-amber-50 text-amber-600 rounded-xl flex items-center justify-center mx-auto">
                            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                            </svg>
                        </div>
                        <div class="space-y-1">
                            <h4 class="text-sm font-bold text-slate-900">{{ file?.name }}</h4>
                            <p class="text-xs text-stone-500">
                                This file ({{ formatSize(file?.size) || 'large' }}) exceeds the 2 MB inline preview limit.
                            </p>
                        </div>
                        <button @click="handleDownload" :disabled="downloading" type="button"
                            class="inline-flex items-center gap-2 px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-semibold transition-colors shadow-sm disabled:opacity-50">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"></path>
                            </svg>
                            Download File
                        </button>
                    </div>

                    <div v-else class="max-w-4xl w-full mx-auto bg-white rounded-2xl notebook-page-shadow border border-stone-200/90 overflow-hidden">
                        <div class="border-b border-stone-100 px-4 py-2 bg-stone-50/70 flex justify-between items-center text-xs text-stone-500 font-mono">
                            <span>{{ file?.name }}</span>
                            <span class="uppercase font-semibold text-slate-700">{{ fileExt }}</span>
                        </div>
                        <pre class="p-4 sm:p-6 font-mono text-xs text-slate-800 whitespace-pre-wrap break-words leading-relaxed select-text overflow-x-auto">{{ textContent }}</pre>
                    </div>
                </template>

                <!-- Unsupported Formats Fallback Card -->
                <template v-else>
                    <div class="bg-white border border-stone-200/90 p-8 rounded-2xl shadow-sm text-center max-w-md w-full mx-auto my-auto space-y-5">
                        <div class="w-12 h-12 bg-stone-100 text-stone-500 rounded-xl flex items-center justify-center mx-auto">
                            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                            </svg>
                        </div>
                        <div class="space-y-1.5">
                            <div class="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-mono font-bold uppercase tracking-wider bg-stone-100 text-stone-600">
                                {{ fileExt || 'FILE' }}
                            </div>
                            <h4 class="text-sm font-bold text-slate-900 break-all">{{ file?.name }}</h4>
                            <p v-if="formatSize(file?.size)" class="text-xs text-stone-500 font-mono tabular-nums">{{ formatSize(file?.size) }}</p>
                            <p class="text-xs text-stone-500 pt-1">
                                Inline preview is not available for this file format.
                            </p>
                        </div>
                        <button @click="handleDownload" :disabled="downloading" type="button"
                            class="inline-flex items-center justify-center gap-2 w-full px-4 py-2.5 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-semibold transition-colors shadow-sm disabled:opacity-50 disabled:cursor-wait">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"></path>
                            </svg>
                            <span>{{ downloading ? 'Preparing download…' : 'Download File' }}</span>
                        </button>
                    </div>
                </template>
            </div>

            <!-- Mobile Overlay Drawer Backdrop -->
            <div v-if="showSidePanel && isMobileSidePanelOpen" @click="isMobileSidePanelOpen = false" class="fixed inset-0 z-30 bg-black/30 md:hidden"></div>

            <!-- Right Pane: Real OCR Transcript & Summaries -->
            <div v-if="showSidePanel" :class="isMobileSidePanelOpen ? 'translate-y-0' : 'translate-y-full md:translate-y-0'"
                class="fixed md:static inset-x-0 bottom-0 z-40 md:z-10 h-[65vh] md:h-full w-full md:w-80 lg:w-96 border-t md:border-t-0 md:border-l border-stone-200/80 bg-white flex flex-col shadow-2xl md:shadow-none transition-transform duration-200 ease-in-out flex-shrink-0 rounded-t-2xl md:rounded-none">

                <!-- Segmented Tab Selector -->
                <div class="p-2 border-b border-stone-200/80 grid grid-cols-2 gap-1 bg-stone-100/70">
                    <button @click="activeRightTab = 'transcription'" type="button"
                        :class="activeRightTab === 'transcription'
                            ? 'bg-white text-slate-900 shadow-sm font-semibold'
                            : 'text-stone-600 hover:text-slate-900 font-medium'"
                        class="py-1.5 px-2 rounded-lg text-xs transition-all flex items-center justify-center gap-1.5">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                        </svg>
                        <span>OCR Transcript</span>
                    </button>
                    <button @click="activeRightTab = 'insights'" type="button"
                        :class="activeRightTab === 'insights'
                            ? 'bg-white text-slate-900 shadow-sm font-semibold'
                            : 'text-stone-600 hover:text-slate-900 font-medium'"
                        class="py-1.5 px-2 rounded-lg text-xs transition-all flex items-center justify-center gap-1.5">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"></path>
                        </svg>
                        <span>Summaries</span>
                    </button>
                </div>

                <!-- Tab 1: Real OCR Transcript -->
                <div v-if="activeRightTab === 'transcription'" ref="transcriptScrollPane" class="p-4 flex-1 overflow-y-auto space-y-3">
                    <div class="flex items-center justify-between">
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
                        <button @click="isMobileSidePanelOpen = false" type="button" class="md:hidden text-xs text-stone-500 hover:text-slate-700">Done</button>
                    </div>

                    <div v-if="isLoadingTranscript" class="py-12 text-center text-stone-500 text-xs">
                        <div class="animate-spin rounded-full h-5 w-5 border-2 border-stone-300 border-t-slate-900 mx-auto mb-2"></div>
                        Fetching OCR transcript...
                    </div>

                    <div v-else-if="transcriptPages.length > 0" class="space-y-3">
                        <div v-for="pageItem in transcriptPages" :key="pageItem.pageId || pageItem.pageIndex"
                            :data-transcript-page="pageItem.pageIndex"
                            :class="activePageIndex === pageItem.pageIndex
                                ? 'border-slate-900 ring-1 ring-slate-900/15 bg-stone-50/70'
                                : 'border-stone-200/80 bg-white'"
                            class="rounded-xl border overflow-hidden transition-all">
                            <button v-if="pages.length > 0" type="button"
                                @click="scrollToCanvasPage(pageItem.pageIndex)"
                                class="w-full px-3.5 py-2 border-b border-stone-100 flex items-center justify-between text-left hover:bg-stone-100/70 transition-colors cursor-pointer">
                                <div class="flex items-center gap-2">
                                    <span :class="activePageIndex === pageItem.pageIndex
                                        ? 'bg-slate-900 text-white'
                                        : 'bg-stone-200/80 text-stone-700'"
                                        class="px-2 py-0.5 rounded-md text-[11px] font-bold font-mono transition-colors tabular-nums">
                                        Page {{ pageItem.pageIndex + 1 }}
                                    </span>
                                    <span v-if="pageItem.date" class="text-[11px] text-stone-500 font-mono tabular-nums">
                                        {{ pageItem.date }}
                                    </span>
                                </div>
                                <span class="text-[10px] font-semibold text-stone-500">
                                    {{ activePageIndex === pageItem.pageIndex ? 'Viewing' : 'Jump →' }}
                                </span>
                            </button>
                            <div v-else class="w-full px-3.5 py-2 border-b border-stone-100 flex items-center justify-between">
                                <div class="flex items-center gap-2">
                                    <span class="px-2 py-0.5 rounded-md text-[11px] font-bold font-mono bg-stone-200/80 text-stone-700 tabular-nums">
                                        Page {{ pageItem.pageIndex + 1 }}
                                    </span>
                                    <span v-if="pageItem.date" class="text-[11px] text-stone-500 font-mono tabular-nums">
                                        {{ pageItem.date }}
                                    </span>
                                </div>
                            </div>
                            <div class="p-3.5 font-mono text-xs text-slate-800 whitespace-pre-wrap leading-relaxed select-text">
                                <template v-if="pageItem.text">{{ formatContent(pageItem.text) }}</template>
                                <span v-else class="italic text-stone-500 font-sans">No text recognized on this page.</span>
                            </div>
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
                <div v-if="activeRightTab === 'insights'" class="p-4 flex-1 overflow-y-auto space-y-3">
                    <div class="flex items-center justify-between">
                        <h4 class="text-[11px] font-bold text-stone-500 uppercase tracking-wider">Notebook Summaries</h4>
                        <button @click="isMobileSidePanelOpen = false" type="button" class="md:hidden text-xs text-stone-500 hover:text-slate-700">Done</button>
                    </div>

                    <div v-if="realSummaries.length > 0" class="space-y-3">
                        <div v-for="s in realSummaries" :key="s.id"
                            class="p-3.5 bg-stone-50 rounded-xl border border-stone-200/80 text-xs text-slate-800 leading-relaxed whitespace-pre-wrap">
                            <p v-if="s.title" class="font-bold text-slate-900 mb-1.5">{{ s.title }}</p>
                            {{ formatContent(s.content || s.summary) }}
                        </div>
                    </div>

                    <div v-else class="bg-stone-50/80 p-5 rounded-xl border border-stone-200/70 text-center text-xs text-stone-500 leading-relaxed">
                        No summaries generated yet for this notebook.
                    </div>
                </div>
            </div>
        </div>
    </div>
    `
};
