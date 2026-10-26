import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import { convertNoteToPng, fetchTranscript, fetchSummaries, fetchDownloadUrl, downloadFile } from '../api/client.js';
import { showToast } from '../composables/useToast.js';

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg']);
const TEXT_EXTENSIONS = new Set(['txt', 'md', 'csv', 'json', 'yaml', 'yml', 'log']);
const MAX_TEXT_PREVIEW_BYTES = 2 * 1024 * 1024; // 2 MB

export default {
    name: 'FileViewer',
    props: ['file'],
    emits: ['close'],
    setup(props) {
        const pages = ref([]);
        const previewUrl = ref(null);
        const textContent = ref('');
        const isTextTooLarge = ref(false);
        const isLoading = ref(true);
        const error = ref(null);
        const downloading = ref(false);

        const activeRightTab = ref('transcription'); // 'transcription' | 'insights'
        const isMobileSidePanelOpen = ref(false);
        const realTranscript = ref('');
        const realSummaries = ref([]);
        const isLoadingTranscript = ref(false);

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
                Boolean(realTranscript.value) ||
                realSummaries.value.length > 0
            );
        });

        const loadingMessage = computed(() => {
            switch (fileCategory.value) {
                case 'note':
                    return 'Converting notebook vector pages to HD PNG...';
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

        const formatSize = (bytes) => {
            if (!bytes || bytes === '0' || bytes === 0) return '';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        };

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

            pages.value = [];
            previewUrl.value = null;
            textContent.value = '';
            isTextTooLarge.value = false;
            realTranscript.value = '';
            realSummaries.value = [];
            isLoading.value = true;
            error.value = null;

            const category = fileCategory.value;

            try {
                if (category === 'note') {
                    const pngPages = await convertNoteToPng(props.file.id);
                    pages.value = pngPages;
                } else if (category === 'image') {
                    const signedUrl = await fetchDownloadUrl(props.file.id);
                    previewUrl.value = signedUrl;
                } else if (category === 'pdf') {
                    const signedUrl = await fetchDownloadUrl(props.file.id);
                    previewUrl.value = signedUrl.includes('?') ? `${signedUrl}&inline=1` : `${signedUrl}?inline=1`;
                } else if (category === 'text') {
                    const fileSize = Number(props.file.size || 0);
                    if (fileSize > MAX_TEXT_PREVIEW_BYTES) {
                        isTextTooLarge.value = true;
                    } else {
                        const signedUrl = await fetchDownloadUrl(props.file.id);
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
                            textContent.value = await resp.text();
                        }
                    }
                }

                // Fetch real OCR transcript & summaries from extended APIs
                isLoadingTranscript.value = true;
                const [transcriptData, summariesData] = await Promise.all([
                    fetchTranscript(props.file.id).catch(() => null),
                    fetchSummaries(props.file.id).catch(() => [])
                ]);

                if (typeof transcriptData === 'string') {
                    realTranscript.value = transcriptData;
                } else if (transcriptData && (transcriptData.transcript || transcriptData.text)) {
                    realTranscript.value = transcriptData.transcript || transcriptData.text;
                } else {
                    realTranscript.value = '';
                }

                if (summariesData && Array.isArray(summariesData)) {
                    realSummaries.value = summariesData.filter(s => (s.dataSource || '').toUpperCase() !== 'OCR');
                }
            } catch (e) {
                console.error("Failed to load file content:", e);
                error.value = category === 'note'
                    ? "Failed to render notebook pages."
                    : `Failed to load file preview: ${e.message || 'Unknown error'}`;
            } finally {
                isLoading.value = false;
                isLoadingTranscript.value = false;
            }
        };

        const refreshInsights = async () => {
            if (!props.file) return;
            isLoadingTranscript.value = true;
            try {
                const [transcriptData, summariesData] = await Promise.all([
                    fetchTranscript(props.file.id).catch(() => null),
                    fetchSummaries(props.file.id).catch(() => [])
                ]);

                if (typeof transcriptData === 'string') {
                    realTranscript.value = transcriptData;
                } else if (transcriptData && (transcriptData.transcript || transcriptData.text)) {
                    realTranscript.value = transcriptData.transcript || transcriptData.text;
                } else {
                    realTranscript.value = '';
                }

                if (summariesData && Array.isArray(summariesData)) {
                    realSummaries.value = summariesData.filter(s => (s.dataSource || '').toUpperCase() !== 'OCR');
                }
            } finally {
                isLoadingTranscript.value = false;
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
            loadFileContent();
        });
        onUnmounted(() => {
            window.removeEventListener('supernote:digest-sync', handleDigestSync);
            window.removeEventListener('supernote:file-sync', handleFileSync);
        });
        watch(() => props.file?.id, (newId) => {
            if (newId) loadFileContent();
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
            loadingMessage,
            isLoading,
            error,
            downloading,
            handleDownload,
            formatSize,
            isLoadingTranscript,
            activeRightTab,
            isMobileSidePanelOpen,
            realTranscript,
            realSummaries,
            formatContent
        };
    },
    template: `
    <div class="bg-slate-100 dark:bg-slate-950 h-full flex flex-col overflow-hidden relative transition-colors animate-fade-in">
        <!-- Top Fixed Header -->
        <div class="flex-none bg-white/90 dark:bg-slate-900/90 backdrop-blur-md p-3.5 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between px-4 sm:px-6 z-20">
            <div class="flex items-center space-x-3 min-w-0">
                <button @click="$emit('close')" class="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-200/60 dark:hover:bg-slate-800 transition-colors">
                    ← Back
                </button>
                <div class="truncate">
                    <h3 class="text-sm font-bold text-slate-800 dark:text-slate-100 truncate">{{ file?.name || 'File Viewer' }}</h3>
                    <p class="text-[11px] text-slate-400 font-mono">
                        ID: {{ file?.id }}<span v-if="formatSize(file?.size)"> · {{ formatSize(file?.size) }}</span>
                    </p>
                </div>
            </div>
            <div class="flex items-center gap-2">
                <button @click="handleDownload" :disabled="downloading"
                    class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 rounded-lg text-xs font-semibold transition-colors disabled:opacity-50 disabled:cursor-wait">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"></path>
                    </svg>
                    <span>{{ downloading ? 'Downloading…' : 'Download' }}</span>
                </button>
                <button v-if="showSidePanel" @click="isMobileSidePanelOpen = !isMobileSidePanelOpen" class="md:hidden px-3 py-1.5 bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 rounded-lg text-xs font-semibold">
                    {{ isMobileSidePanelOpen ? 'Hide Insights' : 'Show Insights' }}
                </button>
            </div>
        </div>

        <!-- Main Content Area -->
        <div class="flex-1 flex overflow-hidden relative">
            <!-- Left / Main Pane: Document Viewport -->
            <div class="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 flex flex-col">
                <div v-if="isLoading" class="flex flex-col items-center justify-center py-20 space-y-3 my-auto">
                    <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
                    <p class="text-xs text-slate-400 font-mono">{{ loadingMessage }}</p>
                </div>

                <div v-else-if="error" class="bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900 p-6 rounded-xl text-center text-xs text-amber-700 dark:amber-400 max-w-md mx-auto my-12 space-y-4">
                    <p>{{ error }}</p>
                    <button @click="handleDownload" :disabled="downloading"
                        class="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold transition-colors shadow-sm disabled:opacity-50">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"></path>
                        </svg>
                        Download File
                    </button>
                </div>

                <!-- Notebook (.note) Preview -->
                <template v-else-if="fileCategory === 'note'">
                    <div v-if="pages.length === 0" class="flex flex-col items-center justify-center py-20 text-center max-w-md mx-auto space-y-2 my-auto">
                        <p class="text-sm font-medium text-slate-500 dark:text-slate-400">No page previews available for this notebook.</p>
                        <p class="text-xs text-slate-400 font-mono">Page previews may be disabled on this server, or the notebook has no pages. Use the tabs on the right to view transcripts and summaries.</p>
                    </div>

                    <div v-else class="max-w-4xl w-full mx-auto space-y-6">
                        <div v-for="(page, idx) in pages" :key="page.pageNo"
                            class="bg-white dark:bg-slate-900 rounded-2xl shadow-md border border-slate-200/80 dark:border-slate-800 overflow-hidden">
                            <div class="border-b border-slate-100 dark:border-slate-800 px-4 py-2 bg-slate-50 dark:bg-slate-800/50 flex justify-between items-center text-xs text-slate-400 font-mono">
                                <span>Page {{ idx + 1 }} of {{ pages.length }}</span>
                                <span class="text-indigo-600 dark:text-indigo-400 font-semibold">Dot Grid Canvas</span>
                            </div>
                            <img :src="page.url" loading="lazy" class="w-full h-auto block" alt="Handwriting Page" />
                        </div>
                    </div>
                </template>

                <!-- Image Preview -->
                <template v-else-if="fileCategory === 'image'">
                    <div class="max-w-5xl w-full mx-auto my-auto flex items-center justify-center bg-white/80 dark:bg-slate-900/80 rounded-2xl shadow-sm border border-slate-200/80 dark:border-slate-800 p-4 sm:p-6">
                        <img v-if="previewUrl" :src="previewUrl" :alt="file?.name || 'Image Preview'"
                            class="max-w-full max-h-[75vh] object-contain rounded-lg" />
                    </div>
                </template>

                <!-- PDF Preview -->
                <template v-else-if="fileCategory === 'pdf'">
                    <div class="max-w-6xl w-full mx-auto flex-1 flex flex-col min-h-[75vh]">
                        <iframe v-if="previewUrl" :src="previewUrl" :title="file?.name || 'PDF Preview'"
                            class="w-full flex-1 min-h-[75vh] h-full rounded-xl border border-slate-200 dark:border-slate-800 bg-white shadow-sm"></iframe>
                    </div>
                </template>

                <!-- Text / Markdown Preview -->
                <template v-else-if="fileCategory === 'text'">
                    <div v-if="isTextTooLarge" class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-8 rounded-2xl shadow-sm text-center max-w-md mx-auto my-auto space-y-4">
                        <div class="w-12 h-12 bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 rounded-xl flex items-center justify-center mx-auto">
                            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                            </svg>
                        </div>
                        <div class="space-y-1">
                            <h4 class="text-sm font-bold text-slate-900 dark:text-white">{{ file?.name }}</h4>
                            <p class="text-xs text-slate-500 dark:text-slate-400">
                                This file ({{ formatSize(file?.size) || 'large' }}) exceeds the 2 MB inline preview limit.
                            </p>
                        </div>
                        <button @click="handleDownload" :disabled="downloading"
                            class="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold transition-colors shadow-sm disabled:opacity-50">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"></path>
                            </svg>
                            Download File
                        </button>
                    </div>

                    <div v-else class="max-w-4xl w-full mx-auto bg-white dark:bg-slate-900 rounded-2xl shadow-sm border border-slate-200/80 dark:border-slate-800 overflow-hidden">
                        <div class="border-b border-slate-100 dark:border-slate-800 px-4 py-2 bg-slate-50 dark:bg-slate-800/50 flex justify-between items-center text-xs text-slate-400 font-mono">
                            <span>{{ file?.name }}</span>
                            <span class="uppercase font-semibold text-indigo-600 dark:text-indigo-400">{{ fileExt }}</span>
                        </div>
                        <pre class="p-4 sm:p-6 font-mono text-xs text-slate-800 dark:text-slate-200 whitespace-pre-wrap break-words leading-relaxed select-text overflow-x-auto">{{ textContent }}</pre>
                    </div>
                </template>

                <!-- Unsupported Formats Fallback Card -->
                <template v-else>
                    <div class="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 p-8 rounded-2xl shadow-sm text-center max-w-md w-full mx-auto my-auto space-y-5">
                        <div class="w-14 h-14 bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 rounded-2xl flex items-center justify-center mx-auto">
                            <svg class="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                            </svg>
                        </div>
                        <div class="space-y-1.5">
                            <div class="inline-flex items-center px-2.5 py-0.5 rounded-md text-[11px] font-bold uppercase tracking-wider bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400">
                                {{ fileExt || 'FILE' }}
                            </div>
                            <h4 class="text-base font-bold text-slate-900 dark:text-white break-all">{{ file?.name }}</h4>
                            <p v-if="formatSize(file?.size)" class="text-xs text-slate-400 font-mono">{{ formatSize(file?.size) }}</p>
                            <p class="text-xs text-slate-500 dark:text-slate-400 pt-1">
                                Inline preview is not available for this file format.
                            </p>
                        </div>
                        <button @click="handleDownload" :disabled="downloading"
                            class="inline-flex items-center justify-center gap-2 w-full px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold transition-colors shadow-sm disabled:opacity-50 disabled:cursor-wait">
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
                class="fixed md:static inset-x-0 bottom-0 z-40 md:z-10 h-[65vh] md:h-full w-full md:w-80 lg:w-96 border-t md:border-t-0 md:border-l border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col shadow-2xl md:shadow-none transition-transform duration-200 ease-in-out flex-shrink-0 rounded-t-2xl md:rounded-none">

                <!-- Workspace Tab Selector & Mobile Handle -->
                <div class="p-2.5 border-b border-slate-100 dark:border-slate-800 grid grid-cols-2 gap-1 bg-slate-50 dark:bg-slate-800/40 relative">
                    <button @click="activeRightTab = 'transcription'"
                        :class="activeRightTab === 'transcription' ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-sm font-bold' : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'"
                        class="py-1.5 rounded-lg text-xs transition-all">
                        📝 OCR Transcript
                    </button>
                    <button @click="activeRightTab = 'insights'"
                        :class="activeRightTab === 'insights' ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-sm font-bold' : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'"
                        class="py-1.5 rounded-lg text-xs transition-all">
                        ✨ Summaries
                    </button>
                </div>

                <!-- Tab 1: Real OCR Transcript -->
                <div v-if="activeRightTab === 'transcription'" class="p-4 flex-1 overflow-y-auto space-y-3">
                    <div class="flex items-center justify-between">
                        <span class="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Gemini Vision OCR</span>
                        <button @click="isMobileSidePanelOpen = false" class="md:hidden text-xs text-slate-400 hover:text-slate-700">Done ✕</button>
                    </div>

                    <div v-if="isLoadingTranscript" class="py-12 text-center text-slate-400 text-xs">
                        <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-indigo-600 mx-auto mb-2"></div>
                        Fetching OCR transcript...
                    </div>

                    <div v-else-if="realTranscript"
                        class="bg-slate-50 dark:bg-slate-800/50 p-3.5 rounded-xl border border-slate-200/80 dark:border-slate-800 font-mono text-xs text-slate-800 dark:text-slate-200 whitespace-pre-wrap leading-relaxed select-text">
                        {{ formatContent(realTranscript) }}
                    </div>

                    <div v-else class="bg-slate-50 dark:bg-slate-800/50 p-6 rounded-xl border border-slate-200/80 dark:border-slate-800 text-center text-xs text-slate-400">
                        No OCR transcript found for this notebook yet. Ensure background processor is running or Gemini API key is configured.
                    </div>
                </div>

                <!-- Tab 2: Real Summaries -->
                <div v-if="activeRightTab === 'insights'" class="p-4 flex-1 overflow-y-auto space-y-3">
                    <div class="flex items-center justify-between">
                        <h4 class="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Notebook Summaries</h4>
                        <button @click="isMobileSidePanelOpen = false" class="md:hidden text-xs text-slate-400 hover:text-slate-700">Done ✕</button>
                    </div>

                    <div v-if="realSummaries.length > 0" class="space-y-3">
                        <div v-for="s in realSummaries" :key="s.id"
                            class="p-3.5 bg-indigo-50/60 dark:bg-indigo-950/40 rounded-xl border border-indigo-100 dark:border-indigo-900/60 text-xs text-slate-800 dark:text-slate-200 leading-relaxed whitespace-pre-wrap">
                            <p v-if="s.title" class="font-bold text-indigo-700 dark:text-indigo-300 mb-1.5">{{ s.title }}</p>
                            {{ formatContent(s.content || s.summary) }}
                        </div>
                    </div>

                    <div v-else class="bg-slate-50 dark:bg-slate-800/50 p-6 rounded-xl border border-slate-200/80 dark:border-slate-800 text-center text-xs text-slate-400">
                        No summaries generated yet for this notebook.
                    </div>
                </div>
            </div>
        </div>
    </div>
    `
};
