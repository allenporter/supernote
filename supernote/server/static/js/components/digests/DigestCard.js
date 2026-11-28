import { computed } from 'vue';
import { formatShortDate } from '../../utils/format.js';
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
        const isAiSummary = computed(() => {
            const ds = String(props.digest.dataSource || '').toUpperCase();
            return ds === 'GEMINI' || ds === 'AI' || ds === 'OPENAI' || ds === 'LLM';
        });
        const hasSourceLink = computed(() =>
            Boolean(props.digest.fileId || props.digest.sourcePath),
        );

        return {
            renderedContent,
            renderedHandwritingTranscript,
            displayDate,
            isAiSummary,
            hasSourceLink,
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
                    <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path>
                    </svg>
                    <span>{{ isResolvingSource ? 'Opening…' : 'Open Source' }}</span>
                </button>
                <button @click="$emit('copy', digest)" type="button"
                    aria-label="Copy digest"
                    title="Copy Markdown"
                    class="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium text-stone-600 hover:text-slate-900 hover:bg-stone-100 transition-colors">
                    <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path>
                    </svg>
                    <span class="hidden sm:inline">Copy</span>
                </button>
                <button @click="$emit('edit', digest)" type="button"
                    aria-label="Edit digest"
                    title="Edit Digest"
                    class="p-1.5 rounded-lg text-stone-500 hover:text-slate-900 hover:bg-stone-100 transition-colors">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
                    </svg>
                </button>
                <button @click="$emit('delete', digest)" type="button"
                    aria-label="Delete digest"
                    title="Delete Digest"
                    class="p-1.5 rounded-lg text-stone-500 hover:text-rose-600 hover:bg-rose-50 transition-colors">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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

        <!-- Optional Handwritten Annotation Transcript -->
        <div v-if="renderedHandwritingTranscript"
            data-digest-handwriting-transcript
            class="border-l-2 border-amber-400 bg-amber-50/60 rounded-r-xl px-3.5 py-2.5 space-y-1">
            <div class="flex items-center gap-1.5 text-[11px] font-medium text-amber-900/90">
                <svg aria-hidden="true" class="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path>
                </svg>
                <span>Handwritten annotation</span>
            </div>
            <div class="markdown-prose text-xs text-slate-700 leading-relaxed break-words"
                v-html="renderedHandwritingTranscript"></div>
        </div>
        <p v-else-if="digest.hasHandwriting"
            data-digest-handwriting-pending
            class="text-[11px] italic text-stone-500">
            Handwritten annotation attached — transcript pending.
        </p>

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
