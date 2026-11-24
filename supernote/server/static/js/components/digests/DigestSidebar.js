export default {
    name: 'DigestSidebar',
    props: {
        categories: {
            type: Array,
            required: true,
        },
        availableSources: {
            type: Array,
            default: () => [],
        },
        selectedCategoryFilter: {
            type: String,
            required: true,
        },
        selectedSourcePath: {
            type: String,
            default: null,
        },
        categoryCounts: {
            type: Object,
            default: () => ({ all: 0, uncategorized: 0 }),
        },
    },
    emits: ['select-category', 'select-source'],
    /**
     * @param {Record<string, any>} props
     */
    setup(props) {
        /**
         * @param {string} key
         */
        function getCount(key) {
            return props.categoryCounts?.[key] || 0;
        }

        return { getCount };
    },
    template: `
    <aside class="w-full md:w-64 flex-shrink-0">
        <div class="bg-white rounded-2xl border border-stone-200/90 shadow-sm p-4 space-y-5">
            <!-- Views -->
            <div>
                <h3 class="text-[11px] font-bold text-stone-500 uppercase tracking-wider px-2.5 mb-2">Views</h3>
                <nav class="space-y-1">
                    <button @click="$emit('select-category', 'all')" type="button"
                        :class="selectedCategoryFilter === 'all' ? 'bg-slate-900 text-white font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                        class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors">
                        <span class="flex items-center gap-2.5">
                            <svg class="w-4 h-4 opacity-80 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path>
                            </svg>
                            All Digests
                        </span>
                        <span :class="selectedCategoryFilter === 'all' ? 'bg-white/20 text-white' : 'bg-stone-100 text-stone-600'"
                            class="text-[11px] font-mono px-2 py-0.5 rounded-md tabular-nums">{{ getCount('all') }}</span>
                    </button>

                    <button @click="$emit('select-category', 'uncategorized')" type="button"
                        :class="selectedCategoryFilter === 'uncategorized' ? 'bg-slate-900 text-white font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                        class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors">
                        <span class="flex items-center gap-2.5">
                            <svg class="w-4 h-4 text-stone-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"></path>
                            </svg>
                            Uncategorized
                        </span>
                        <span :class="selectedCategoryFilter === 'uncategorized' ? 'bg-white/20 text-white' : 'bg-stone-100 text-stone-600'"
                            class="text-[11px] font-mono px-2 py-0.5 rounded-md tabular-nums">{{ getCount('uncategorized') }}</span>
                    </button>
                </nav>
            </div>

            <!-- Categories -->
            <div class="border-t border-stone-100 pt-4">
                <h3 class="text-[11px] font-bold text-stone-500 uppercase tracking-wider px-2.5 mb-2">Categories</h3>
                <nav v-if="categories.length > 0" class="space-y-1">
                    <button v-for="cat in categories" :key="cat.uniqueIdentifier || cat.id"
                        @click="$emit('select-category', cat.uniqueIdentifier)" type="button"
                        :class="selectedCategoryFilter === cat.uniqueIdentifier ? 'bg-stone-200/80 text-slate-900 font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                        class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors text-left">
                        <span class="truncate">{{ cat.name }}</span>
                        <span class="text-[11px] font-mono px-2 py-0.5 rounded-md bg-stone-100 text-stone-600 ml-2 tabular-nums shrink-0">{{ getCount(cat.uniqueIdentifier) }}</span>
                    </button>
                </nav>
                <p v-else class="px-2.5 text-xs text-stone-500">No categories yet.</p>
            </div>

            <!-- Sources -->
            <div v-if="availableSources.length > 0" class="border-t border-stone-100 pt-4">
                <div class="flex items-center justify-between px-2.5 mb-2">
                    <h3 class="text-[11px] font-bold text-stone-500 uppercase tracking-wider">Sources</h3>
                    <button v-if="selectedSourcePath" @click="$emit('select-source', null)" type="button"
                        class="text-[11px] font-semibold text-slate-700 hover:text-slate-900">
                        Clear
                    </button>
                </div>
                <nav class="space-y-1 max-h-56 overflow-y-auto pr-0.5">
                    <button v-for="src in availableSources" :key="src.path"
                        @click="$emit('select-source', selectedSourcePath === src.path ? null : src.path)"
                        type="button"
                        :title="src.path"
                        :class="selectedSourcePath === src.path ? 'bg-stone-200/80 text-slate-900 font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                        class="w-full flex items-center justify-between px-3 py-1.5 rounded-xl text-xs transition-colors text-left">
                        <span class="truncate">{{ src.label }}</span>
                        <span class="text-[11px] font-mono px-1.5 py-0.5 rounded-md bg-stone-100 text-stone-600 ml-2 tabular-nums shrink-0">{{ src.count }}</span>
                    </button>
                </nav>
            </div>
        </div>
    </aside>
    `,
};
