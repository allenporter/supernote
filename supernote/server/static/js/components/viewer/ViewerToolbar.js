import { computed } from 'vue';
import { formatSize } from '../../utils/format.js';
import { ZOOM_STEPS } from './noteMeta.js';

const MIN_ZOOM = ZOOM_STEPS[0];
const MAX_ZOOM = ZOOM_STEPS[ZOOM_STEPS.length - 1];

export default {
    name: 'ViewerToolbar',
    props: {
        file: { type: Object, default: null },
        fileExt: { type: String, default: '' },
        fileCategory: { type: String, default: 'unsupported' },
        equipment: { type: String, default: null },
        pageCount: { type: Number, default: 0 },
        activePageIndex: { type: Number, default: 0 },
        zoomPercent: { type: Number, default: 100 },
        downloading: { type: Boolean, default: false },
        canExportPdf: { type: Boolean, default: false },
        exportingPdf: { type: Boolean, default: false },
        showSidePanel: { type: Boolean, default: false },
        isMobileSidePanelOpen: { type: Boolean, default: false },
    },
    emits: [
        'close',
        'prev-page',
        'next-page',
        'zoom-in',
        'zoom-out',
        'reset-zoom',
        'download',
        'export-pdf',
        'toggle-side-panel',
    ],
    /**
     * @param {{ file?: Partial<FileItem> | null }} props
     */
    setup(props) {
        const formattedSize = computed(() => formatSize(props.file?.size));
        return { formattedSize, MIN_ZOOM, MAX_ZOOM };
    },
    template: `
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
                        <span v-if="equipment" class="font-semibold text-stone-600">{{ equipment }}</span>
                        <span v-if="equipment && (pageCount > 0 || formattedSize)"> · </span>
                        <span v-if="pageCount > 0">{{ pageCount }} {{ pageCount === 1 ? 'page' : 'pages' }}</span>
                        <span v-if="pageCount > 0 && formattedSize"> · </span>
                        <span v-if="formattedSize">{{ formattedSize }}</span>
                    </p>
                </div>
            </div>

            <!-- Center: Notebook Page Stepper & Zoom Controls (Desktop) -->
            <div v-if="fileCategory === 'note' && pageCount > 0" class="hidden sm:flex items-center gap-2">
                <!-- Page Jumper -->
                <div class="flex items-center bg-stone-100 rounded-lg p-0.5 border border-stone-200/60">
                    <button @click="$emit('prev-page')" :disabled="activePageIndex <= 0" type="button"
                        aria-label="Previous page"
                        class="p-1 rounded-md text-stone-600 hover:text-slate-900 hover:bg-white disabled:opacity-35 disabled:hover:bg-transparent transition-all"
                        title="Previous page">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path>
                        </svg>
                    </button>
                    <span class="px-2.5 text-xs font-mono font-medium text-slate-800 tabular-nums">
                        Page {{ activePageIndex + 1 }} / {{ pageCount }}
                    </span>
                    <button @click="$emit('next-page')" :disabled="activePageIndex >= pageCount - 1" type="button"
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
                    <button @click="$emit('zoom-out')" :disabled="zoomPercent <= MIN_ZOOM" type="button"
                        aria-label="Zoom out"
                        class="px-2 py-0.5 rounded-md text-xs font-mono font-bold text-stone-600 hover:text-slate-900 hover:bg-white disabled:opacity-35 transition-all"
                        title="Zoom out">−</button>
                    <button @click="$emit('reset-zoom')" type="button"
                        aria-label="Reset zoom"
                        class="px-2 py-0.5 text-[11px] font-mono font-medium text-stone-600 hover:text-slate-900 tabular-nums"
                        title="Reset zoom">
                        {{ zoomPercent }}%
                    </button>
                    <button @click="$emit('zoom-in')" :disabled="zoomPercent >= MAX_ZOOM" type="button"
                        aria-label="Zoom in"
                        class="px-2 py-0.5 rounded-md text-xs font-mono font-bold text-stone-600 hover:text-slate-900 hover:bg-white disabled:opacity-35 transition-all"
                        title="Zoom in">+</button>
                </div>
            </div>

            <!-- Right: Export PDF, Download & Mobile Insights Toggle -->
            <div class="flex items-center gap-1.5 sm:gap-2 shrink-0">
                <button v-if="fileCategory === 'note' && canExportPdf" @click="$emit('export-pdf')"
                    :disabled="exportingPdf" :aria-busy="exportingPdf" type="button"
                    :aria-label="exportingPdf ? 'Exporting PDF…' : 'Export PDF'"
                    :title="exportingPdf ? 'Exporting PDF…' : 'Export PDF'"
                    class="flex items-center gap-1.5 p-2 md:px-3 md:py-1.5 bg-stone-100 hover:bg-stone-200/80 text-slate-800 rounded-lg text-xs font-semibold transition-colors disabled:opacity-50 disabled:cursor-wait">
                    <svg aria-hidden="true" class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 13h6M9 17h4"></path>
                    </svg>
                    <span class="hidden md:inline">{{ exportingPdf ? 'Exporting…' : 'Export PDF' }}</span>
                </button>
                <button @click="$emit('download')" :disabled="downloading" type="button"
                    aria-label="Download file"
                    :title="downloading ? 'Downloading…' : 'Download'"
                    class="flex items-center gap-1.5 p-2 sm:px-3 sm:py-1.5 bg-stone-100 hover:bg-stone-200/80 text-slate-800 rounded-lg text-xs font-semibold transition-colors disabled:opacity-50 disabled:cursor-wait">
                    <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"></path>
                    </svg>
                    <span class="hidden sm:inline">{{ downloading ? 'Downloading…' : 'Download' }}</span>
                </button>
                <button v-if="showSidePanel" @click="$emit('toggle-side-panel')" type="button"
                    :aria-expanded="isMobileSidePanelOpen"
                    class="md:hidden px-2.5 sm:px-3 py-1.5 bg-slate-900 text-white rounded-lg text-xs font-semibold">
                    {{ isMobileSidePanelOpen ? 'Hide Panel' : 'Transcript' }}
                </button>
            </div>
        </div>

        <!-- Mobile Notebook Secondary Control Bar -->
        <div v-if="fileCategory === 'note' && pageCount > 0"
            class="flex sm:hidden items-center justify-between px-3 py-1.5 bg-stone-50 border-b border-stone-200/80 gap-2 z-20">
            <!-- Mobile Page Stepper -->
            <div class="flex items-center bg-white rounded-lg p-0.5 border border-stone-200/80 shadow-sm">
                <button @click="$emit('prev-page')" :disabled="activePageIndex <= 0" type="button"
                    aria-label="Previous page"
                    class="p-1 rounded-md text-stone-600 hover:text-slate-900 hover:bg-stone-100 disabled:opacity-35 transition-all">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path>
                    </svg>
                </button>
                <span class="px-2 text-[11px] font-mono font-medium text-slate-800 tabular-nums">
                    Page {{ activePageIndex + 1 }} / {{ pageCount }}
                </span>
                <button @click="$emit('next-page')" :disabled="activePageIndex >= pageCount - 1" type="button"
                    aria-label="Next page"
                    class="p-1 rounded-md text-stone-600 hover:text-slate-900 hover:bg-stone-100 disabled:opacity-35 transition-all">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                    </svg>
                </button>
            </div>

            <!-- Mobile Zoom Controls -->
            <div class="flex items-center bg-white rounded-lg p-0.5 border border-stone-200/80 shadow-sm">
                <button @click="$emit('zoom-out')" :disabled="zoomPercent <= 75" type="button"
                    aria-label="Zoom out"
                    class="px-2 py-0.5 rounded-md text-xs font-mono font-bold text-stone-600 hover:text-slate-900 disabled:opacity-35 transition-all">−</button>
                <button @click="$emit('reset-zoom')" type="button"
                    aria-label="Reset zoom"
                    class="px-1.5 py-0.5 text-[11px] font-mono font-medium text-stone-600 hover:text-slate-900 tabular-nums">
                    {{ zoomPercent }}%
                </button>
            <button @click="$emit('zoom-in')" :disabled="zoomPercent >= MAX_ZOOM" type="button"
                aria-label="Zoom in"
                class="px-2 py-0.5 rounded-md text-xs font-mono font-bold text-stone-600 hover:text-slate-900 disabled:opacity-35 transition-all">+</button>
        </div>
    </div>
    `,
};
