import { nextTick, onMounted, ref, watch } from 'vue';
import { useModalEscape } from '../../composables/useModalEscape.js';

export default {
    name: 'DigestEditorModal',
    props: {
        digest: {
            type: Object,
            default: null,
        },
        categories: {
            type: Array,
            default: () => [],
        },
        defaultCategoryUuid: {
            type: String,
            default: '',
        },
        isSubmitting: {
            type: Boolean,
            default: false,
        },
    },
    emits: ['save', 'close'],
    /**
     * @param {Record<string, any>} props
     * @param {{ emit: (event: string, ...args: any[]) => void }} ctx
     */
    setup(props, { emit }) {
        /** @type {import('vue').Ref<HTMLTextAreaElement | null>} */
        const contentInput = ref(null);

        /**
         * @param {DigestItem | null | undefined} item
         */
        function buildForm(item) {
            if (item) {
                return {
                    id: item.id,
                    parentUniqueIdentifier: item.parentUniqueIdentifier || '',
                    content: item.content || '',
                    commentStr: item.commentStr || '',
                    author: item.author || '',
                    sourcePath: item.sourcePath || '',
                };
            }
            return {
                id: null,
                parentUniqueIdentifier: props.defaultCategoryUuid || '',
                content: '',
                commentStr: '',
                author: '',
                sourcePath: '',
            };
        }

        const form = ref(buildForm(props.digest));

        watch(
            () => props.digest,
            (next) => {
                form.value = buildForm(next);
            },
        );

        useModalEscape(() => {
            if (!props.isSubmitting) emit('close');
        });

        onMounted(() => {
            nextTick(() => contentInput.value?.focus());
        });

        function handleSubmit() {
            if (props.isSubmitting || !form.value.content.trim()) return;
            emit('save', {
                id: form.value.id,
                parentUniqueIdentifier: form.value.parentUniqueIdentifier || null,
                content: form.value.content,
                commentStr: form.value.commentStr,
                author: form.value.author,
                sourcePath: form.value.sourcePath,
            });
        }

        return {
            contentInput,
            form,
            handleSubmit,
        };
    },
    template: `
    <div class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm"
        @click.self="!isSubmitting && $emit('close')">
        <div role="dialog" aria-modal="true" :aria-label="digest ? 'Edit Digest' : 'New Digest'"
            class="w-full max-w-lg bg-white rounded-2xl border border-stone-200 shadow-xl overflow-hidden animate-fade-in">
            <div class="flex items-center justify-between px-5 py-4 border-b border-stone-100">
                <h3 class="text-sm font-bold text-slate-900">
                    {{ digest ? 'Edit Digest' : 'New Digest' }}
                </h3>
                <button @click="$emit('close')" :disabled="isSubmitting" type="button"
                    aria-label="Close modal"
                    class="p-1 rounded-lg text-stone-400 hover:text-slate-700 hover:bg-stone-100 transition-colors">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>

            <form @submit.prevent="handleSubmit" class="p-5 space-y-4">
                <div>
                    <label for="digest-category-select" class="block text-xs font-semibold text-stone-700 mb-1.5">Category</label>
                    <select id="digest-category-select" v-model="form.parentUniqueIdentifier"
                        class="w-full px-3 py-2 bg-stone-50 border border-stone-200 rounded-xl text-xs text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400">
                        <option value="">Uncategorized</option>
                        <option v-for="cat in categories" :key="cat.uniqueIdentifier || cat.id" :value="cat.uniqueIdentifier">
                            {{ cat.name }}
                        </option>
                    </select>
                </div>

                <div>
                    <label for="digest-content-input" class="block text-xs font-semibold text-stone-700 mb-1.5">Content</label>
                    <textarea id="digest-content-input" ref="contentInput" v-model="form.content" rows="5" required
                        placeholder="Highlight excerpt or Markdown summary..."
                        class="w-full px-3 py-2 bg-stone-50 border border-stone-200 rounded-xl text-xs text-slate-900 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400 resize-y"></textarea>
                </div>

                <div>
                    <label for="digest-comment-input" class="block text-xs font-semibold text-stone-700 mb-1.5">Comment</label>
                    <textarea id="digest-comment-input" v-model="form.commentStr" rows="2"
                        placeholder="Optional annotation or reflection..."
                        class="w-full px-3 py-2 bg-stone-50 border border-stone-200 rounded-xl text-xs text-slate-900 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400 resize-y"></textarea>
                </div>

                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                        <label for="digest-author-input" class="block text-xs font-semibold text-stone-700 mb-1.5">Author</label>
                        <input id="digest-author-input" v-model="form.author" type="text"
                            placeholder="Optional author"
                            class="w-full px-3 py-2 bg-stone-50 border border-stone-200 rounded-xl text-xs text-slate-900 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400" />
                    </div>
                    <div>
                        <label for="digest-source-input" class="block text-xs font-semibold text-stone-700 mb-1.5">Source Path</label>
                        <input id="digest-source-input" v-model="form.sourcePath" type="text"
                            placeholder="e.g. Document/Book.pdf"
                            class="w-full px-3 py-2 bg-stone-50 border border-stone-200 rounded-xl text-xs font-mono text-slate-900 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400" />
                    </div>
                </div>

                <div class="flex items-center justify-end gap-2 pt-2 border-t border-stone-100">
                    <button @click="$emit('close')" :disabled="isSubmitting" type="button"
                        class="px-3.5 py-2 rounded-xl text-xs font-medium text-stone-600 hover:bg-stone-100 transition-colors">
                        Cancel
                    </button>
                    <button type="submit" :disabled="isSubmitting || !form.content.trim()"
                        class="px-4 py-2 rounded-xl text-xs font-semibold bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50 transition-colors">
                        {{ isSubmitting ? 'Saving…' : (digest ? 'Save Changes' : 'Create Digest') }}
                    </button>
                </div>
            </form>
        </div>
    </div>
    `,
};
