import { ref, onMounted } from 'vue';
import { convertNoteToPng, fetchTranscript, fetchSummaries } from '../api/client.js';

export default {
    name: 'FileViewer',
    props: ['file'],
    emits: ['close'],
    setup(props) {
        const pages = ref([]);
        const isLoading = ref(true);
        const error = ref(null);

        const activeRightTab = ref('transcription'); // 'transcription' | 'insights'
        const isMobileSidePanelOpen = ref(false);
        const realTranscript = ref('');
        const realSummaries = ref([]);
        const isLoadingTranscript = ref(false);

        const loadNoteContent = async () => {
            if (!props.file) return;

            isLoading.value = true;
            error.value = null;

            try {
                // Fetch page PNGs
                if (props.file.extension === 'note') {
                    const pngPages = await convertNoteToPng(props.file.id);
                    pages.value = pngPages;
                } else {
                    error.value = "Preview not available for this file type.";
                }

                // Fetch real OCR transcript & summaries from extended APIs
                isLoadingTranscript.value = true;
                const [transcriptData, summariesData] = await Promise.all([
                    fetchTranscript(props.file.id).catch(() => null),
                    fetchSummaries(props.file.id).catch(() => [])
                ]);

                if (transcriptData && transcriptData.transcript) {
                    realTranscript.value = transcriptData.transcript;
                } else if (transcriptData && transcriptData.text) {
                    realTranscript.value = transcriptData.text;
                }

                if (summariesData && Array.isArray(summariesData)) {
                    realSummaries.value = summariesData;
                }
            } catch (e) {
                console.error("Failed to load notebook content:", e);
                error.value = "Failed to render notebook pages.";
            } finally {
                isLoading.value = false;
                isLoadingTranscript.value = false;
            }
        };

        onMounted(loadNoteContent);

        return {
            pages,
            isLoading,
            error,
            isLoadingTranscript,
            activeRightTab,
            isMobileSidePanelOpen,
            realTranscript,
            realSummaries
        };
    },
    template: `
    <div class="bg-slate-100 dark:bg-slate-950 h-full flex flex-col overflow-hidden relative transition-colors animate-fade-in">
        <!-- Top Fixed Header -->
        <div class="flex-none bg-white/90 dark:bg-slate-900/90 backdrop-blur-md p-3.5 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between px-4 sm:px-6 z-20">
            <div class="flex items-center gap-3 min-w-0">
                <div class="w-8 h-8 bg-indigo-600 text-white rounded-lg flex items-center justify-center font-bold text-xs shadow-sm flex-shrink-0">
                    📄
                </div>
                <div class="min-w-0">
                    <h2 class="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2 truncate">
                        {{ file.name }}
                    </h2>
                    <p class="text-[11px] text-slate-400 font-mono">{{ pages.length }} Pages Total</p>
                </div>
            </div>

            <div class="flex items-center gap-2">
                <!-- Mobile OCR Toggle Button -->
                <button @click="isMobileSidePanelOpen = !isMobileSidePanelOpen"
                    class="md:hidden px-3 py-1.5 bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 text-xs font-semibold rounded-xl border border-indigo-200/60">
                    📝 OCR & Insights
                </button>

                <button @click="$emit('close')"
                    class="px-3.5 py-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl transition-colors border border-slate-200 dark:border-slate-700">
                    ✕ Close
                </button>
            </div>
        </div>

        <!-- Main Dual Pane Workspace -->
        <div class="flex-1 flex overflow-hidden relative">
            <!-- Left Pane: Rendered Notebook Canvas (Takes 100% space when mobile side panel is closed) -->
            <div class="flex-1 overflow-y-auto p-4 sm:p-8 flex flex-col items-center">
                <div class="max-w-3xl w-full space-y-6">
                    <!-- Error State -->
                    <div v-if="error" class="bg-white dark:bg-slate-900 p-12 rounded-2xl shadow-sm text-center border border-slate-200 dark:border-slate-800">
                        <p class="text-slate-500 dark:text-slate-400 text-sm">{{ error }}</p>
                    </div>

                    <!-- Loading State -->
                    <div v-if="isLoading" class="flex flex-col items-center justify-center p-20 bg-white dark:bg-slate-900 rounded-2xl shadow-sm">
                        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 mb-3"></div>
                        <p class="text-slate-500 animate-pulse text-xs">Converting notebook pages...</p>
                    </div>

                    <!-- Rendered Note Canvas Pages -->
                    <div v-if="!isLoading && !error && pages.length > 0" class="space-y-6">
                        <div v-for="(page, idx) in pages" :key="page.pageNo"
                            class="bg-white dark:bg-slate-900 rounded-2xl shadow-md border border-slate-200/80 dark:border-slate-800 overflow-hidden">
                            <div class="border-b border-slate-100 dark:border-slate-800 px-4 py-2 bg-slate-50 dark:bg-slate-800/50 flex justify-between items-center text-xs text-slate-400 font-mono">
                                <span>Page {{ page.pageNo }} of {{ pages.length }}</span>
                                <span class="text-indigo-600 dark:text-indigo-400 font-semibold">Dot Grid Canvas</span>
                            </div>
                            <img :src="page.url" loading="lazy" class="w-full h-auto block" alt="Handwriting Page" />
                        </div>
                    </div>
                </div>
            </div>

            <!-- Mobile Overlay Drawer Backdrop -->
            <div v-if="isMobileSidePanelOpen" @click="isMobileSidePanelOpen = false" class="fixed inset-0 z-30 bg-black/30 md:hidden"></div>

            <!-- Right Pane: Real OCR Transcript & Summaries -->
            <!-- Desktop: Fixed Side Panel | Mobile: Slide-Up Bottom Sheet Drawer -->
            <div :class="isMobileSidePanelOpen ? 'translate-y-0' : 'translate-y-full md:translate-y-0'"
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
                        {{ realTranscript }}
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
                            class="p-3 bg-indigo-50/60 dark:bg-indigo-950/40 rounded-xl border border-indigo-100 dark:border-indigo-900/60 text-xs text-slate-800 dark:text-slate-200 leading-relaxed">
                            <p class="font-bold text-indigo-700 dark:text-indigo-300 mb-1">{{ s.title || 'Summary' }}</p>
                            {{ s.content || s.summary }}
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
}
