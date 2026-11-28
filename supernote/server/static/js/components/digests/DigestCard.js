import { computed, onUnmounted, ref, watch } from 'vue';
import { fetchDigestHandwritingPages, isAiSummaryDigest } from '../../api/digests.js';
import { formatShortDate, getErrorMessage } from '../../utils/format.js';
import { renderMarkdown } from '../../utils/markdown.js';

export default {
    name: 'DigestCard',
    props: {
        digest: {
            type: Object,
            required: true,
        },
        categoryName: {
            type: String,
            default: null,
        },
        isResolvingSource: {
            type: Boolean,
            default: false,
        },
    },
    emits: ['open-source', 'copy', 'edit', 'delete'],
    /**
     * @param {Record<string, any>} props
     */
    setup(props) {
        const renderedContent = computed(() => renderMarkdown(props.digest.content || ''));
        const renderedHandwritingTranscript = computed(() =>
            props.digest.handwriting?.transcript
                ? renderMarkdown(props.digest.handwriting.transcript)
                : '',
        );
        const displayDate = computed(() =>
            formatShortDate(props.digest.lastModifiedTime || props.digest.creationTime),
        );
        const isAiSummary = computed(() => isAiSummaryDigest(props.digest, props.categoryName));
        const aiSummaryTitle = computed(() =>
            props.digest.dataSource && isAiSummaryDigest(props.digest, null)
                ? `AI Notebook Summary (${props.digest.dataSource})`
                : 'AI Notebook Summary',
        );
        const hasSourceLink = computed(() =>
            Boolean(props.digest.fileId || props.digest.sourcePath),
        );
        const handwritingPreviewId = computed(
            () => `handwriting-preview-${props.digest.id || props.digest.uniqueIdentifier}`,
        );

        const showHandwritingPreview = ref(false);
        /** @type {import('vue').Ref<NotePngPage[]>} */
        const handwritingPages = ref([]);
        const isLoadingHandwriting = ref(false);
        /** @type {import('vue').Ref<string | null>} */
        const handwritingError = ref(null);
        let handwritingLoadSeq = 0;

        watch(
            () => [
                props.digest.id,
                props.digest.hasHandwriting,
                props.digest.handwriting?.md5 ?? null,
            ],
            () => {
                handwritingLoadSeq += 1;
                showHandwritingPreview.value = false;
                handwritingPages.value = [];
                isLoadingHandwriting.value = false;
                handwritingError.value = null;
            },
        );

        onUnmounted(() => {
            handwritingLoadSeq += 1;
        });

        async function loadHandwritingPreview() {
            if (!props.digest.id || isLoadingHandwriting.value) return;
            const seq = ++handwritingLoadSeq;
            isLoadingHandwriting.value = true;
            handwritingError.value = null;
            try {
                const pages = await fetchDigestHandwritingPages(props.digest.id);
                if (seq === handwritingLoadSeq) {
                    handwritingPages.value = pages;
                }
            } catch (e) {
                if (seq === handwritingLoadSeq) {
                    handwritingError.value = getErrorMessage(e);
                }
            } finally {
                if (seq === handwritingLoadSeq) {
                    isLoadingHandwriting.value = false;
                }
            }
        }

        function handleHandwritingImageError() {
            if (!isLoadingHandwriting.value) {
                handwritingError.value = 'Handwriting preview image could not be loaded.';
            }
        }

        function toggleHandwritingPreview() {
            if (showHandwritingPreview.value) {
                showHandwritingPreview.value = false;
                return;
            }
            showHandwritingPreview.value = true;
            loadHandwritingPreview().catch(() => {});
        }

        return {
            renderedContent,
            renderedHandwritingTranscript,
            displayDate,
            isAiSummary,
            aiSummaryTitle,
            hasSourceLink,
            handwritingPreviewId,
            showHandwritingPreview,
            handwritingPages,
            isLoadingHandwriting,
            handwritingError,
            loadHandwritingPreview,
            handleHandwritingImageError,
            toggleHandwritingPreview,
        };
    },
    template: `
    <article data-digest-card
        class="bg-white rounded-2xl border border-stone-200/90 shadow-sm p-5 space-y-3.5 transition-shadow hover:shadow-md">
        <!-- Header Metadata & Actions -->
        <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex flex-wrap items-center gap-1.5 min-w-0">
                <span class="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border"
                    :class="categoryName ? 'bg-stone-100 text-stone-700 border-stone-200/80' : 'bg-stone-50 text-stone-500 border-stone-200/60'">
                    {{ categoryName || 'Uncategorized' }}
                </span>
                <span v-if="isAiSummary"
                    data-digest-ai-badge
                    :title="aiSummaryTitle"
                    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium bg-indigo-50 text-indigo-700 border border-indigo-200/70">
                    AI Summary
                </span>
                <span v-if="digest.hasHandwriting"
                    data-digest-handwriting-badge
                    title="Contains handwritten annotation ink"
                    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium bg-amber-50 text-amber-800 border border-amber-200/80">
                    <svg aria-hidden="true" class="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path>
                    </svg>
                    Handwritten
                </span>
                <span v-if="displayDate" class="text-[11px] text-stone-500 ml-1 tabular-nums">
                    {{ displayDate }}
                </span>
            </div>

            <div class="flex items-center gap-1.5 shrink-0">
                <button v-if="hasSourceLink"
                    @click="$emit('open-source', digest)"
                    :disabled="isResolvingSource"
                    type="button"
                    class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium text-slate-700 bg-stone-100 hover:bg-stone-200/80 hover:text-slate-900 disabled:opacity-60 transition-colors">
                    <svg aria-hidden="true" class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path>
                    </svg>
                    <span>{{ isResolvingSource ? 'Opening…' : 'Open Source' }}</span>
                </button>
                <button @click="$emit('copy', digest)" type="button"
                    aria-label="Copy digest"
                    title="Copy Markdown"
                    class="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-stone-600 hover:text-slate-900 hover:bg-stone-100 transition-colors">
                    <svg aria-hidden="true" class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path>
                    </svg>
                    <span class="hidden sm:inline">Copy</span>
                </button>
                <button @click="$emit('edit', digest)" type="button"
                    aria-label="Edit digest"
                    title="Edit Digest"
                    class="p-1.5 rounded-lg text-stone-500 hover:text-slate-900 hover:bg-stone-100 transition-colors">
                    <svg aria-hidden="true" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
                    </svg>
                </button>
                <button @click="$emit('delete', digest)" type="button"
                    aria-label="Delete digest"
                    title="Delete Digest"
                    class="p-1.5 rounded-lg text-stone-500 hover:text-rose-600 hover:bg-rose-50 transition-colors">
                    <svg aria-hidden="true" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                    </svg>
                </button>
            </div>
        </div>

        <!-- Primary Digest Content -->
        <div v-if="digest.content"
            class="markdown-prose text-sm text-slate-800 leading-relaxed break-words"
            v-html="renderedContent"></div>
        <p v-else class="text-sm italic text-stone-500">No digest content.</p>

        <!-- Optional Typed Comment -->
        <div v-if="digest.commentStr"
            class="border-l-2 border-stone-300 bg-stone-50/80 rounded-r-xl px-3.5 py-2.5 text-xs text-slate-700 leading-relaxed whitespace-pre-wrap break-words">
            {{ digest.commentStr }}
        </div>

        <!-- Optional Handwritten Annotation Transcript & Inline Ink Preview -->
        <div v-if="renderedHandwritingTranscript || digest.hasHandwriting"
            :data-digest-handwriting-transcript="renderedHandwritingTranscript ? '' : null"
            class="border-l-2 border-amber-400 bg-amber-50/60 rounded-r-xl px-3.5 py-2.5 space-y-2">
            <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="flex items-center gap-1.5 text-[11px] font-medium text-amber-900/90">
                    <svg aria-hidden="true" class="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path>
                    </svg>
                    <span>Handwritten annotation</span>
                </div>
                <button v-if="digest.hasHandwriting && digest.id"
                    @click="toggleHandwritingPreview"
                    type="button"
                    data-digest-view-handwriting
                    :aria-expanded="showHandwritingPreview"
                    :aria-controls="handwritingPreviewId"
                    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium text-amber-900 bg-amber-100/80 hover:bg-amber-200/80 transition-colors">
                    <svg aria-hidden="true" class="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path>
                    </svg>
                    <span>{{ showHandwritingPreview ? 'Hide Handwriting' : 'View Handwriting' }}</span>
                </button>
            </div>

            <div v-if="renderedHandwritingTranscript"
                class="markdown-prose text-xs text-slate-700 leading-relaxed break-words"
                v-html="renderedHandwritingTranscript"></div>
            <p v-else
                data-digest-handwriting-pending
                class="text-[11px] italic text-stone-600">
                Handwritten annotation attached — transcript pending.
            </p>

            <div v-if="showHandwritingPreview"
                :id="handwritingPreviewId"
                data-digest-handwriting-preview
                class="pt-2 border-t border-amber-200/70 space-y-2">
                <div v-if="isLoadingHandwriting"
                    role="status"
                    class="flex items-center gap-2 text-xs text-amber-900/80 py-2">
                    <span aria-hidden="true" class="w-3.5 h-3.5 border-2 border-amber-700/30 border-t-amber-800 rounded-full animate-spin"></span>
                    <span>Rendering handwriting…</span>
                </div>
                <div v-else-if="handwritingError"
                    class="flex flex-wrap items-center justify-between gap-2 text-xs text-rose-700 bg-rose-50 border border-rose-200/80 rounded-lg px-3 py-2">
                    <span>{{ handwritingError }}</span>
                    <button @click="loadHandwritingPreview" type="button"
                        class="px-2 py-0.5 rounded bg-rose-100 hover:bg-rose-200 text-rose-900 font-semibold transition-colors">
                        Retry
                    </button>
                </div>
                <p v-else-if="handwritingPages.length === 0"
                    class="text-xs italic text-stone-500">
                    No handwritten ink pages available.
                </p>
                <div v-else
                    :class="handwritingPages.length > 1 ? 'grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-h-[34rem] overflow-y-auto pr-1' : 'space-y-2'">
                    <figure v-for="(page, index) in handwritingPages" :key="page.pageNo + '-' + index"
                        class="bg-white rounded-xl border border-amber-200/80 p-2 space-y-1">
                        <img :src="page.url"
                            :alt="'Handwritten annotation page ' + (index + 1)"
                            loading="lazy"
                            @error="handleHandwritingImageError"
                            :class="handwritingPages.length > 1 ? 'w-full max-h-72 object-contain rounded-lg bg-white' : 'w-full max-h-[28rem] object-contain rounded-lg bg-white'" />
                        <figcaption v-if="handwritingPages.length > 1"
                            class="text-[10px] text-stone-500 text-right tabular-nums">
                            Page {{ index + 1 }} of {{ handwritingPages.length }}
                        </figcaption>
                    </figure>
                </div>
            </div>
        </div>

        <!-- Footer Provenance -->
        <div v-if="digest.author || digest.sourcePath || (digest.tags && digest.tags.length > 0)"
            class="flex flex-wrap items-center gap-x-3 gap-y-1.5 pt-2 border-t border-stone-100 text-[11px] text-stone-500">
            <span v-if="digest.author" class="font-medium text-stone-700">
                {{ digest.author }}
            </span>
            <span v-if="digest.sourcePath" class="font-mono text-stone-500 truncate max-w-full" :title="digest.sourcePath">
                {{ digest.sourcePath }}
            </span>
            <div v-if="digest.tags && digest.tags.length > 0" class="flex flex-wrap items-center gap-1">
                <span v-for="tag in digest.tags" :key="tag"
                    class="px-1.5 py-0.5 rounded bg-stone-100 text-stone-600 text-[10px] font-medium">
                    #{{ tag }}
                </span>
            </div>
        </div>
    </article>
    `,
};
