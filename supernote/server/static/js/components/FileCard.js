import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { downloadFile, fetchDownloadUrl, fetchNoteCover } from '../api/client.js';
import { showToast } from '../composables/useToast.js';
import { formatShortDate, formatSize, getErrorMessage, resolveFileExt } from '../utils/format.js';
import { IMAGE_EXTENSIONS } from './viewer/noteMeta.js';

const DOCUMENT_EXTENSIONS = new Set([
    'epub',
    'doc',
    'docx',
    'txt',
    'md',
    'csv',
    'json',
    'yaml',
    'yml',
    'log',
]);

export default {
    props: ['file', 'isSelected', 'processingStatus', 'layout', 'selectionMode'],
    emits: ['open', 'select', 'rename'],
    /**
     * @param {Record<string, any>} props
     */
    setup(props) {
        /** @type {import('vue').Ref<HTMLElement | null>} */
        const cardRef = ref(null);
        /** @type {import('vue').Ref<string | null>} */
        const coverUrl = ref(null);
        const downloading = ref(false);
        const isInViewport = ref(false);
        /** @type {IntersectionObserver | null} */
        let visibilityObserver = null;
        let activeCoverSeq = 0;

        const fileExt = computed(() => resolveFileExt(props.file));

        const iconType = computed(() => {
            const ext = fileExt.value;
            if (ext === 'note') return 'note';
            if (ext === 'pdf') return 'pdf';
            if (IMAGE_EXTENSIONS.has(ext)) return 'image';
            if (DOCUMENT_EXTENSIONS.has(ext)) return 'document';
            return 'generic';
        });

        const download = async () => {
            if (downloading.value) return;
            downloading.value = true;
            try {
                await downloadFile(props.file.id);
            } catch (e) {
                showToast(`Failed to download: ${getErrorMessage(e)}`);
            } finally {
                downloading.value = false;
            }
        };

        const teardownObserver = () => {
            if (visibilityObserver) {
                visibilityObserver.disconnect();
                visibilityObserver = null;
            }
        };

        const loadCover = async () => {
            const seq = ++activeCoverSeq;
            if (!props.file || props.file.isDirectory || props.layout === 'list') {
                coverUrl.value = null;
                return;
            }
            const ext = fileExt.value;
            if (ext !== 'note' && !IMAGE_EXTENSIONS.has(ext)) {
                coverUrl.value = null;
                return;
            }
            if (!isInViewport.value) return;

            const targetId = props.file.id;
            try {
                const resolvedUrl =
                    ext === 'note'
                        ? await fetchNoteCover(targetId)
                        : await fetchDownloadUrl(targetId);
                if (seq === activeCoverSeq && String(props.file?.id) === String(targetId)) {
                    coverUrl.value = resolvedUrl;
                }
            } catch {
                if (seq === activeCoverSeq) {
                    coverUrl.value = null;
                }
            }
        };

        const observeCardVisibility = () => {
            teardownObserver();
            if (props.layout === 'list' || props.file?.isDirectory) {
                return;
            }
            if (typeof IntersectionObserver !== 'function' || !cardRef.value) {
                isInViewport.value = true;
                loadCover();
                return;
            }
            const observer = new IntersectionObserver(
                (entries) => {
                    if (entries.some((entry) => entry.isIntersecting)) {
                        isInViewport.value = true;
                        teardownObserver();
                        loadCover();
                    }
                },
                { rootMargin: '200px' },
            );
            visibilityObserver = observer;
            observer.observe(cardRef.value);
        };

        const formattedSize = computed(() => formatSize(props.file?.size));
        const formattedDate = computed(() => formatShortDate(props.file?.updatedAt));
        const compactDate = computed(() =>
            formatShortDate(props.file?.updatedAt, { includeTime: false }),
        );

        onMounted(observeCardVisibility);
        onUnmounted(teardownObserver);
        watch(
            () => [props.file?.id, props.layout],
            () => {
                coverUrl.value = null;
                isInViewport.value = false;
                observeCardVisibility();
            },
            { flush: 'post' },
        );
        watch(
            () => props.processingStatus,
            (newStatus, oldStatus) => {
                if (newStatus === 'COMPLETED' && oldStatus !== 'COMPLETED' && !coverUrl.value) {
                    loadCover();
                }
            },
        );

        return {
            cardRef,
            coverUrl,
            downloading,
            download,
            fileExt,
            iconType,
            formattedSize,
            formattedDate,
            compactDate,
        };
    },
    template: `
    <!-- 1. LIST ROW LAYOUT -->
    <div v-if="layout === 'list'" ref="cardRef" tabindex="0"
        :aria-label="'Open ' + file.name"
        @click="$emit('open', file)"
        @keydown.enter.self.prevent="$emit('open', file)"
        @keydown.space.self.prevent="$emit('open', file)"
        :class="isSelected ? 'bg-stone-100/90' : 'hover:bg-stone-50/90'"
        class="group file-card grid grid-cols-12 items-center gap-4 px-4 py-2.5 transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-slate-900">
        <div class="col-span-7 sm:col-span-5 flex items-center gap-3 min-w-0">
            <input type="checkbox" :checked="isSelected" @click.stop @change.stop="$emit('select', file.id)"
                :aria-label="'Select ' + file.name"
                class="w-4 h-4 rounded border-stone-300 text-slate-900 focus:ring-slate-900 cursor-pointer shrink-0">
            <div class="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                :class="file.isDirectory ? 'bg-amber-50 text-amber-600 border border-amber-200/60' : 'bg-stone-100 text-slate-700 border border-stone-200/70'">
                <svg v-if="file.isDirectory" class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z"></path>
                </svg>
                <svg v-else-if="iconType === 'note'" class="w-4 h-4 text-slate-800" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.75" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
                </svg>
                <svg v-else-if="iconType === 'pdf'" class="w-4 h-4 text-rose-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.75" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                </svg>
                <svg v-else class="w-4 h-4 text-stone-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.75" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                </svg>
            </div>
            <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 min-w-0">
                    <h3 class="font-semibold text-slate-900 truncate text-xs sm:text-sm" :title="file.name">{{ file.name }}</h3>
                    <span v-if="processingStatus && processingStatus !== 'COMPLETED' && processingStatus !== 'NONE'"
                        class="px-1.5 py-0.5 rounded bg-amber-50 border border-amber-200 text-[10px] font-mono font-semibold text-amber-700 uppercase shrink-0">
                        {{ processingStatus }}
                    </span>
                </div>
                <p v-if="formattedDate" class="sm:hidden text-[11px] font-mono text-stone-500 truncate mt-0.5 tabular-nums">
                    {{ formattedDate }}
                </p>
            </div>
        </div>
        <div class="hidden sm:block sm:col-span-3 text-xs font-mono text-stone-500 truncate tabular-nums">
            {{ formattedDate || '—' }}
        </div>
        <div class="col-span-3 sm:col-span-2 text-right text-xs font-mono text-stone-500 tabular-nums">
            {{ formattedSize || '—' }}
        </div>
        <div class="col-span-2 flex items-center justify-end gap-1" @click.stop>
            <button v-if="!file.isDirectory" @click.stop="download" :disabled="downloading"
                :aria-label="'Download ' + file.name"
                :title="downloading ? 'Preparing download…' : 'Download'"
                class="p-1.5 rounded-lg text-stone-500 hover:text-slate-900 hover:bg-stone-200/60 transition-colors disabled:opacity-40">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"></path>
                </svg>
            </button>
            <button @click.stop="$emit('rename', file)" title="Rename" :aria-label="'Rename ' + file.name"
                class="p-1.5 rounded-lg text-stone-500 hover:text-slate-900 hover:bg-stone-200/60 transition-colors">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path>
                </svg>
            </button>
        </div>
    </div>

    <!-- 2. COMPACT FOLDER PILL LAYOUT -->
    <div v-else-if="file.isDirectory" ref="cardRef" tabindex="0"
        :aria-label="'Open folder ' + file.name"
        @click="$emit('open', file)"
        @keydown.enter.self.prevent="$emit('open', file)"
        @keydown.space.self.prevent="$emit('open', file)"
        :class="isSelected
            ? 'ring-2 ring-slate-900 bg-stone-100/80 border-slate-900'
            : 'bg-white border-stone-200/90 hover:border-stone-300 hover:shadow-md'"
        class="group file-card rounded-xl border px-3.5 py-3 shadow-sm transition-all cursor-pointer flex items-center justify-between gap-3 relative focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900">
        <div class="flex items-center gap-3 min-w-0 flex-1">
            <!-- Folder Icon -->
            <div class="w-9 h-9 rounded-lg bg-amber-50/90 border border-amber-200/60 text-amber-600 flex items-center justify-center shrink-0 group-hover:bg-amber-100/70 transition-colors">
                <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z"></path>
                </svg>
            </div>
            <div class="min-w-0 flex-1">
                <h3 class="font-semibold text-slate-900 text-sm truncate leading-tight" :title="file.name">{{ file.name }}</h3>
                <p class="text-[11px] font-mono text-stone-500 mt-0.5 truncate tabular-nums" :title="formattedDate || undefined">
                    <template v-if="formattedSize && compactDate">{{ formattedSize }} · {{ compactDate }}</template>
                    <template v-else-if="formattedSize">{{ formattedSize }}</template>
                    <template v-else-if="compactDate">{{ compactDate }}</template>
                    <template v-else>Folder</template>
                </p>
            </div>
        </div>

        <div class="flex items-center gap-1 shrink-0" @click.stop>
            <button @click.stop="$emit('rename', file)" title="Rename folder" :aria-label="'Rename ' + file.name"
                class="p-1.5 rounded-lg text-stone-500 hover:text-slate-900 hover:bg-stone-100 hover-reveal transition-colors">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path>
                </svg>
            </button>
            <div class="hover-reveal p-1" :class="{'is-visible': isSelected || selectionMode}">
                <input type="checkbox" :checked="isSelected" @change.stop="$emit('select', file.id)"
                    :aria-label="'Select ' + file.name"
                    class="w-4 h-4 rounded border-stone-300 text-slate-900 focus:ring-slate-900 cursor-pointer">
            </div>
        </div>
    </div>

    <!-- 3. PORTRAIT (3:4) NOTEBOOK / FILE CARD LAYOUT -->
    <div v-else ref="cardRef" tabindex="0"
        :aria-label="'Open ' + file.name"
        @click="$emit('open', file)"
        @keydown.enter.self.prevent="$emit('open', file)"
        @keydown.space.self.prevent="$emit('open', file)"
        :class="isSelected
            ? 'ring-2 ring-slate-900 border-slate-900 bg-stone-50'
            : 'bg-white border-stone-200/90 hover:border-stone-300 hover:shadow-md hover:-translate-y-0.5'"
        class="group file-card rounded-2xl border shadow-sm transition-all duration-200 cursor-pointer overflow-hidden flex flex-col relative focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900">
        <!-- Selection Checkbox -->
        <div class="absolute top-3 left-3 z-20 hover-reveal" :class="{'is-visible': isSelected || selectionMode}" @click.stop>
            <div class="bg-white/90 backdrop-blur-sm rounded-md p-0.5 shadow-sm border border-stone-200/80 flex items-center justify-center">
                <input type="checkbox" :checked="isSelected" @change.stop="$emit('select', file.id)"
                    :aria-label="'Select ' + file.name"
                    class="w-4 h-4 rounded border-stone-300 text-slate-900 focus:ring-slate-900 cursor-pointer">
            </div>
        </div>

        <!-- File Format Pill Badge (Top Right) -->
        <div class="absolute top-3 right-3 z-20 pointer-events-none">
            <span class="px-2 py-0.5 rounded-md text-[10px] font-mono font-semibold uppercase tracking-wider bg-white/90 backdrop-blur-sm text-stone-600 border border-stone-200/80 shadow-sm">
                {{ fileExt || 'FILE' }}
            </span>
        </div>

        <!-- Portrait 3:4 Paper Preview Container -->
        <div class="aspect-[3/4] paper-surface p-3 flex items-center justify-center relative overflow-hidden border-b border-stone-200/70">

            <!-- Full Portrait Notebook/Image Cover -->
            <div v-if="coverUrl" class="w-full h-full bg-white rounded-lg notebook-page-shadow overflow-hidden flex items-center justify-center">
                <img :src="coverUrl" loading="lazy" decoding="async"
                    @error="coverUrl = null"
                    class="w-full h-full object-contain transition-transform duration-200 group-hover:scale-[1.02]"
                    alt="Cover Preview" />
            </div>

            <!-- Vector Stationery Placeholder when no cover image -->
            <div v-else class="w-full h-full bg-white/80 rounded-lg border border-stone-200/70 flex flex-col items-center justify-center gap-2.5 p-4 text-center">
                <div v-if="iconType === 'note'" class="w-11 h-11 rounded-xl bg-stone-100 text-slate-800 flex items-center justify-center">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
                    </svg>
                </div>
                <div v-else-if="iconType === 'pdf'" class="w-11 h-11 rounded-xl bg-rose-50 text-rose-600 flex items-center justify-center">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 13h6m-6 4h4"></path>
                    </svg>
                </div>
                <div v-else-if="iconType === 'image'" class="w-11 h-11 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                    </svg>
                </div>
                <div v-else-if="iconType === 'document'" class="w-11 h-11 rounded-xl bg-sky-50 text-sky-600 flex items-center justify-center">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path>
                    </svg>
                </div>
                <div v-else class="w-11 h-11 rounded-xl bg-stone-100 text-stone-500 flex items-center justify-center">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                    </svg>
                </div>
            </div>

            <!-- Background Processing Status Overlay -->
            <div v-if="processingStatus && processingStatus !== 'COMPLETED' && processingStatus !== 'NONE'"
                class="absolute inset-0 bg-white/85 backdrop-blur-[2px] flex items-center justify-center z-10">
                <div class="flex flex-col items-center gap-1.5 bg-white px-3 py-2 rounded-xl border border-stone-200 shadow-sm">
                    <div class="animate-spin rounded-full h-4 w-4 border-2 border-stone-300 border-t-slate-900"></div>
                    <span class="text-[10px] font-mono font-semibold text-slate-800 uppercase tracking-wider">{{ processingStatus }}</span>
                </div>
            </div>
        </div>

        <!-- Card Footer -->
        <div class="p-3 bg-white flex justify-between items-start gap-2">
            <div class="min-w-0 flex-1">
                <h3 class="font-semibold text-slate-900 truncate text-xs sm:text-[13px] leading-snug" :title="file.name">{{ file.name }}</h3>
                <p class="text-[11px] font-mono text-stone-500 mt-0.5 truncate tabular-nums" :title="formattedDate || undefined">
                    <template v-if="formattedSize && compactDate">{{ formattedSize }}<span class="hidden sm:inline"> · {{ compactDate }}</span></template>
                    <template v-else-if="formattedSize">{{ formattedSize }}</template>
                    <template v-else-if="compactDate">{{ compactDate }}</template>
                    <template v-else>{{ fileExt ? fileExt.toUpperCase() : 'FILE' }}</template>
                </p>
            </div>
            <div class="flex items-center gap-0.5 shrink-0" @click.stop>
                <button @click.stop="download" :disabled="downloading"
                    :aria-label="'Download ' + file.name"
                    :title="downloading ? 'Preparing download…' : 'Download'"
                    class="p-1 rounded-md text-stone-500 hover:text-slate-900 hover:bg-stone-100 transition-colors hover-reveal disabled:opacity-50 disabled:cursor-wait">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"></path>
                    </svg>
                </button>
                <button @click.stop="$emit('rename', file)" title="Rename" :aria-label="'Rename ' + file.name"
                    class="p-1 rounded-md text-stone-500 hover:text-slate-900 hover:bg-stone-100 transition-colors hover-reveal">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path>
                    </svg>
                </button>
            </div>
        </div>
    </div>
    `,
};
