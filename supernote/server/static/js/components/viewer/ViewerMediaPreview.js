import { computed } from 'vue';
import { formatSize } from '../../utils/format.js';

export default {
    name: 'ViewerMediaPreview',
    props: {
        file: { type: Object, default: null },
        fileExt: { type: String, default: '' },
        fileCategory: { type: String, default: 'unsupported' },
        previewUrl: { type: String, default: null },
        textContent: { type: String, default: '' },
        isTextTooLarge: { type: Boolean, default: false },
        downloading: { type: Boolean, default: false },
    },
    emits: ['download'],
    /**
     * @param {{ file?: Partial<FileItem> | null }} props
     */
    setup(props) {
        const formattedSize = computed(() => formatSize(props.file?.size));
        return { formattedSize };
    },
    template: `
    <!-- Image Preview -->
    <div v-if="fileCategory === 'image'" class="max-w-4xl w-full mx-auto my-auto flex items-center justify-center bg-white rounded-2xl notebook-page-shadow border border-stone-200/80 p-4 sm:p-6">
        <img v-if="previewUrl" :src="previewUrl" :alt="file?.name || 'Image Preview'"
            class="max-w-full max-h-[72vh] object-contain rounded-lg" />
    </div>

    <!-- PDF Preview -->
    <div v-else-if="fileCategory === 'pdf'" class="max-w-5xl w-full mx-auto flex-1 flex flex-col min-h-[72vh]">
        <iframe v-if="previewUrl" :src="previewUrl" :title="file?.name || 'PDF Preview'"
            class="w-full flex-1 min-h-[72vh] h-full rounded-xl border border-stone-200 bg-white shadow-sm"></iframe>
    </div>

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
                    This file ({{ formattedSize || 'large' }}) exceeds the 2 MB inline preview limit.
                </p>
            </div>
            <button @click="$emit('download')" :disabled="downloading" type="button"
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
    <div v-else class="bg-white border border-stone-200/90 p-8 rounded-2xl shadow-sm text-center max-w-md w-full mx-auto my-auto space-y-5">
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
            <p v-if="formattedSize" class="text-xs text-stone-500 font-mono tabular-nums">{{ formattedSize }}</p>
            <p class="text-xs text-stone-500 pt-1">
                Inline preview is not available for this file format.
            </p>
        </div>
        <button @click="$emit('download')" :disabled="downloading" type="button"
            class="inline-flex items-center justify-center gap-2 w-full px-4 py-2.5 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-semibold transition-colors shadow-sm disabled:opacity-50 disabled:cursor-wait">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"></path>
            </svg>
            <span>{{ downloading ? 'Preparing download…' : 'Download File' }}</span>
        </button>
    </div>
    `,
};
