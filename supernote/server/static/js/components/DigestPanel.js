import { computed, onMounted, onUnmounted, ref } from 'vue';
import { resolveSourceFileId } from '../api/digests.js';
import { formatSourceLabel, useDigests } from '../composables/useDigests.js';
import { showToast } from '../composables/useToast.js';
import { copyTextToClipboard } from '../utils/clipboard.js';
import DigestCard from './digests/DigestCard.js';
import DigestSidebar from './digests/DigestSidebar.js';

export default {
    name: 'DigestPanel',
    components: {
        DigestSidebar,
        DigestCard,
    },
    emits: ['open-file'],
    /**
     * @param {Record<string, any>} _props
     * @param {{ emit: (event: string, ...args: any[]) => void }} ctx
     */
    setup(_props, { emit }) {
        const {
            categories,
            digests,
            isLoading,
            error,
            selectedCategoryFilter,
            selectedSourcePath,
            searchQuery,
            categoryMap,
            categoryCounts,
            availableSources,
            filteredDigests,
            loadDigests,
        } = useDigests();

        /** @type {import('vue').Ref<string | null>} */
        const resolvingDigestId = ref(null);

        function handleDigestSyncEvent() {
            loadDigests().catch(() => {});
        }

        onMounted(async () => {
            window.addEventListener('supernote:digest-sync', handleDigestSyncEvent);
            await loadDigests();
        });

        onUnmounted(() => {
            window.removeEventListener('supernote:digest-sync', handleDigestSyncEvent);
        });

        const activeHeading = computed(() => {
            if (selectedCategoryFilter.value === 'all') return 'All Digests';
            if (selectedCategoryFilter.value === 'uncategorized') return 'Uncategorized';
            return categoryMap.value[selectedCategoryFilter.value]?.name || 'Digests';
        });

        const activeSourceLabel = computed(() =>
            selectedSourcePath.value ? formatSourceLabel(selectedSourcePath.value) : null,
        );

        const hasActiveFilters = computed(() =>
            Boolean(
                selectedCategoryFilter.value !== 'all' ||
                    selectedSourcePath.value ||
                    searchQuery.value.trim(),
            ),
        );

        /**
         * @param {string} categoryFilter
         */
        function handleSelectCategory(categoryFilter) {
            selectedCategoryFilter.value = categoryFilter;
        }

        /**
         * @param {string | null} sourcePath
         */
        function handleSelectSource(sourcePath) {
            selectedSourcePath.value = sourcePath;
        }

        function clearFilters() {
            selectedCategoryFilter.value = 'all';
            selectedSourcePath.value = null;
            searchQuery.value = '';
        }

        /**
         * @param {DigestItem} digest
         */
        async function handleCopyDigest(digest) {
            const copied = await copyTextToClipboard(digest.content || '');
            showToast(
                copied ? 'Copied digest to clipboard' : 'Nothing to copy',
                copied ? 'success' : 'info',
            );
        }

        /**
         * @param {DigestItem} digest
         */
        async function handleOpenSource(digest) {
            if (digest.fileId) {
                emit('open-file', { id: String(digest.fileId), isDirectory: false });
                return;
            }
            if (!digest.sourcePath || resolvingDigestId.value) return;
            resolvingDigestId.value = digest.id;
            try {
                const resolvedId = await resolveSourceFileId(digest.sourcePath);
                if (resolvedId) {
                    emit('open-file', { id: resolvedId, isDirectory: false });
                } else {
                    showToast(`Source file not found in Cloud: ${digest.sourcePath}`, 'info');
                }
            } finally {
                resolvingDigestId.value = null;
            }
        }

        return {
            categories,
            digests,
            isLoading,
            error,
            selectedCategoryFilter,
            selectedSourcePath,
            searchQuery,
            categoryMap,
            categoryCounts,
            availableSources,
            filteredDigests,
            resolvingDigestId,
            activeHeading,
            activeSourceLabel,
            hasActiveFilters,
            loadDigests,
            handleSelectCategory,
            handleSelectSource,
            clearFilters,
            handleCopyDigest,
            handleOpenSource,
        };
    },
    template: `
    <div class="flex flex-col md:flex-row gap-6 items-start">
        <digest-sidebar
            :categories="categories"
            :available-sources="availableSources"
            :selected-category-filter="selectedCategoryFilter"
            :selected-source-path="selectedSourcePath"
            :category-counts="categoryCounts"
            @select-category="handleSelectCategory"
            @select-source="handleSelectSource"></digest-sidebar>

        <section class="flex-1 min-w-0 w-full space-y-4">
            <!-- Header & Search Bar -->
            <div class="bg-white rounded-2xl border border-stone-200/90 shadow-sm p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div class="flex items-center gap-2.5 min-w-0 flex-wrap">
                    <h2 class="text-base font-bold text-slate-900 truncate">{{ activeHeading }}</h2>
                    <span class="text-xs font-mono px-2 py-0.5 rounded-md bg-stone-100 text-stone-600 tabular-nums">
                        {{ filteredDigests.length }}
                    </span>
                    <button v-if="activeSourceLabel"
                        @click="handleSelectSource(null)"
                        type="button"
                        class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-slate-900 text-white text-[11px] font-medium hover:bg-slate-800 transition-colors">
                        <span class="truncate max-w-[180px]">{{ activeSourceLabel }}</span>
                        <span aria-hidden="true">&times;</span>
                    </button>
                </div>

                <div class="flex items-center gap-2 w-full sm:w-auto">
                    <div class="relative flex-1 sm:w-64">
                        <svg class="w-4 h-4 text-stone-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
                        </svg>
                        <input v-model="searchQuery" type="search" placeholder="Filter digests, authors, sources..."
                            aria-label="Filter digests"
                            class="w-full pl-9 pr-3 py-1.5 bg-stone-50 border border-stone-200 rounded-xl text-xs text-slate-900 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-400 transition-all" />
                    </div>
                    <button @click="loadDigests" :disabled="isLoading" type="button"
                        aria-label="Refresh digests"
                        title="Refresh"
                        class="p-2 rounded-xl border border-stone-200 bg-white text-stone-600 hover:text-slate-900 hover:bg-stone-50 disabled:opacity-50 transition-colors shrink-0">
                        <svg class="w-4 h-4" :class="{ 'animate-spin': isLoading }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
                        </svg>
                    </button>
                </div>
            </div>

            <!-- Error Banner -->
            <div v-if="error"
                class="bg-rose-50 border border-rose-200 text-rose-800 rounded-2xl p-4 flex items-center justify-between gap-3 text-xs">
                <span>{{ error }}</span>
                <button @click="loadDigests" type="button"
                    class="px-3 py-1.5 rounded-lg bg-rose-100 hover:bg-rose-200 text-rose-900 font-semibold transition-colors shrink-0">
                    Retry
                </button>
            </div>

            <!-- Loading Skeleton -->
            <div v-if="isLoading && digests.length === 0" class="space-y-3">
                <div v-for="n in 3" :key="n"
                    class="bg-white rounded-2xl border border-stone-200/90 p-5 space-y-3 animate-pulse">
                    <div class="h-4 w-32 bg-stone-200 rounded"></div>
                    <div class="h-4 w-full bg-stone-100 rounded"></div>
                    <div class="h-4 w-2/3 bg-stone-100 rounded"></div>
                </div>
            </div>

            <!-- Empty State -->
            <div v-else-if="filteredDigests.length === 0"
                class="bg-white rounded-2xl border border-stone-200/90 shadow-sm p-10 text-center space-y-3">
                <div class="w-11 h-11 rounded-2xl bg-stone-100 text-stone-500 flex items-center justify-center mx-auto">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.75" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path>
                    </svg>
                </div>
                <div class="space-y-1">
                    <h3 class="text-sm font-semibold text-slate-900">
                        {{ hasActiveFilters ? 'No matching digests' : 'No digests yet' }}
                    </h3>
                    <p class="text-xs text-stone-500 max-w-sm mx-auto">
                        {{ hasActiveFilters
                            ? 'Try adjusting your category, source, or search filter.'
                            : 'Highlights synced from your Supernote device and AI notebook summaries will appear here.' }}
                    </p>
                </div>
                <button v-if="hasActiveFilters" @click="clearFilters" type="button"
                    class="inline-flex items-center px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-medium hover:bg-slate-800 transition-colors">
                    Clear Filters
                </button>
            </div>

            <!-- Digest Stream -->
            <div v-else class="space-y-3.5">
                <digest-card v-for="digest in filteredDigests" :key="digest.id || digest.uniqueIdentifier"
                    :digest="digest"
                    :category-name="digest.parentUniqueIdentifier ? (categoryMap[digest.parentUniqueIdentifier]?.name || null) : null"
                    :is-resolving-source="resolvingDigestId === digest.id"
                    @open-source="handleOpenSource"
                    @copy="handleCopyDigest"></digest-card>
            </div>
        </section>
    </div>
    `,
};
