import { ref, watch, onMounted } from 'vue';
import { convertNoteToPng } from '../api/client.js';
import SummaryPanel from './SummaryPanel.js';

export default {
    components: {
        SummaryPanel
    },
    props: {
        file: {
            type: Object,
            required: true
        }
    },
    emits: ['close'],
    setup(props) {
        const pages = ref([]);
        const isLoading = ref(false);
        const error = ref(null);
        const showDetails = ref(false);

        const loadPages = async () => {
            if (!props.file) return;

            // Only convert .note files. For others, just show placeholder for now.
            // In a real app, we'd handle PDF/PNG native viewing here too.
            // But our goal is .note conversion.
            if (!props.file.name.endsWith('.note')) {
                error.value = "Preview not available for this file type.";
                return;
            }

            isLoading.value = true;
            error.value = null;
            pages.value = [];

            try {
                const result = await convertNoteToPng(props.file.id);
                if (result && result.length > 0) {
                    pages.value = result.sort((a, b) => a.pageNo - b.pageNo);
                } else {
                    error.value = "No pages found. The note might still be processing.";
                }
            } catch (e) {
                console.error(e);
                error.value = "Failed to load note preview.";
            } finally {
                isLoading.value = false;
            }
        };

        onMounted(loadPages);
        watch(() => props.file, loadPages);

        return {
            pages,
            isLoading,
            error,
            showDetails
        };
    },
    template: `
    <div class="bg-gray-100 h-full flex flex-col overflow-hidden relative">
        <!-- Header (Fixed) -->
        <div class="flex-none bg-white p-4 shadow-sm z-10 flex items-center justify-between px-8">
            <div class="flex items-center gap-3">
                <div class="bg-indigo-100 p-2 rounded-lg text-indigo-600">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                </div>
                <div>
                    <h2 class="text-lg font-bold text-slate-800">{{ file.name }}</h2>
                    <p class="text-xs text-slate-500">{{ pages.length }} Pages</p>
                </div>
            </div>
            <div class="flex items-center gap-2">
                <button @click="showDetails = !showDetails"
                    :class="{'bg-indigo-50 text-indigo-600 border-indigo-200': showDetails, 'text-slate-600 hover:bg-slate-50 border-slate-200': !showDetails}"
                    class="px-4 py-2 text-sm font-medium rounded-lg transition-colors border flex items-center gap-2">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                    Insights
                </button>
                <button @click="$emit('close')"
                    class="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 rounded-lg transition-colors border border-slate-200">
                    Close
                </button>
            </div>
        </div>

        <!-- Main Content Area -->
        <div class="flex-1 overflow-hidden relative flex">
            <!-- Pages (Scrollable) -->
            <div class="flex-1 overflow-y-auto p-4 sm:p-8">
                <div class="max-w-4xl mx-auto">
                    <!-- Error State -->
                    <div v-if="error" class="bg-white p-12 rounded-xl shadow-sm text-center">
                        <div class="text-red-500 mb-2">
                            <svg class="w-12 h-12 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                        </div>
                        <h3 class="text-lg font-medium text-slate-900">Unable to load preview</h3>
                        <p class="text-slate-500 mt-1">{{ error }}</p>
                    </div>

                    <!-- Loading State -->
                    <div v-if="isLoading" class="flex flex-col items-center justify-center p-20 bg-white rounded-xl shadow-sm">
                        <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-indigo-600 mb-4"></div>
                        <p class="text-slate-500 animate-pulse">Converting note...</p>
                    </div>

                    <!-- Pages List -->
                    <div v-if="!isLoading && !error && pages.length > 0" class="space-y-6">
                        <div v-for="page in pages" :key="page.pageNo" class="bg-white rounded-xl shadow-md overflow-hidden transition-transform hover:scale-[1.005] duration-300">
                            <div class="border-b border-slate-100 p-3 bg-slate-50 flex justify-between items-center text-xs text-slate-400 font-mono">
                                <span>Page {{ page.pageNo }}</span>
                            </div>
                            <img :src="page.url" loading="lazy" class="w-full h-auto block" alt="Note Page" />
                        </div>
                    </div>
                </div>
            </div>

            <!-- Sidebar (Animated) -->
            <transition
                enter-active-class="transform transition ease-out duration-300"
                enter-from-class="translate-x-full"
                enter-to-class="translate-x-0"
                leave-active-class="transform transition ease-in duration-300"
                leave-from-class="translate-x-0"
                leave-to-class="translate-x-full"
            >
                <div v-if="showDetails" class="w-96 border-l border-slate-200 shadow-xl z-20 absolute right-0 top-0 bottom-0 bg-white md:relative">
                    <summary-panel :file-id="file.id" @close="showDetails = false"></summary-panel>
                </div>
            </transition>
        </div>
    </div>
    `
}
