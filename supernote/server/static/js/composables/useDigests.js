import { computed, ref, watch } from 'vue';
import {
    createDigest,
    createDigestCategory,
    deleteDigest,
    deleteDigestCategory,
    fetchDigestCategories,
    fetchDigests,
    updateDigest,
    updateDigestCategory,
} from '../api/digests.js';
import { getErrorMessage } from '../utils/format.js';
import { showToast } from './useToast.js';

/**
 * Extract a concise filename label from a VFS-relative source path.
 * @param {string} sourcePath
 * @returns {string}
 */
export function formatSourceLabel(sourcePath) {
    const parts = sourcePath.split('/').filter(Boolean);
    return parts.length > 0 ? parts[parts.length - 1] : sourcePath;
}

export function useDigests() {
    /** @type {import('vue').Ref<DigestCategory[]>} */
    const categories = ref([]);
    /** @type {import('vue').Ref<DigestItem[]>} */
    const digests = ref([]);
    const isLoading = ref(false);
    /** @type {import('vue').Ref<string | null>} */
    const error = ref(null);

    /** @type {import('vue').Ref<string>} */
    const selectedCategoryFilter = ref('all'); // 'all' | 'uncategorized' | <category.uniqueIdentifier>
    /** @type {import('vue').Ref<string | null>} */
    const selectedSourcePath = ref(null);
    const searchQuery = ref('');

    let activeLoadSeq = 0;

    async function loadDigests() {
        const seq = ++activeLoadSeq;
        isLoading.value = true;
        error.value = null;
        try {
            const [loadedCategories, loadedDigests] = await Promise.all([
                fetchDigestCategories(),
                fetchDigests(),
            ]);
            if (seq === activeLoadSeq) {
                categories.value = loadedCategories;
                digests.value = loadedDigests;
                const activeFilter = selectedCategoryFilter.value;
                if (
                    activeFilter !== 'all' &&
                    activeFilter !== 'uncategorized' &&
                    !loadedCategories.some((c) => c.uniqueIdentifier === activeFilter)
                ) {
                    selectedCategoryFilter.value = 'all';
                }
            }
        } catch (e) {
            if (seq === activeLoadSeq) {
                error.value = getErrorMessage(e);
            }
        } finally {
            if (seq === activeLoadSeq) {
                isLoading.value = false;
            }
        }
    }

    function resetDigests() {
        activeLoadSeq++;
        categories.value = [];
        digests.value = [];
        isLoading.value = false;
        error.value = null;
        selectedCategoryFilter.value = 'all';
        selectedSourcePath.value = null;
        searchQuery.value = '';
    }

    const categoryMap = computed(() => {
        /** @type {Record<string, DigestCategory>} */
        const map = {};
        for (const cat of categories.value) {
            if (cat.uniqueIdentifier) {
                map[cat.uniqueIdentifier] = cat;
            }
        }
        return map;
    });

    const categoryCounts = computed(() => {
        /** @type {Record<string, number>} */
        const counts = { all: digests.value.length, uncategorized: 0 };
        for (const cat of categories.value) {
            if (cat.uniqueIdentifier) {
                counts[cat.uniqueIdentifier] = 0;
            }
        }
        for (const item of digests.value) {
            if (!item.parentUniqueIdentifier || !categoryMap.value[item.parentUniqueIdentifier]) {
                counts.uncategorized += 1;
            } else {
                counts[item.parentUniqueIdentifier] =
                    (counts[item.parentUniqueIdentifier] || 0) + 1;
            }
        }
        return counts;
    });

    const categoryFilteredDigests = computed(() => {
        const filter = selectedCategoryFilter.value;
        if (filter === 'all') {
            return digests.value;
        }
        if (filter === 'uncategorized') {
            return digests.value.filter(
                (item) =>
                    !item.parentUniqueIdentifier || !categoryMap.value[item.parentUniqueIdentifier],
            );
        }
        return digests.value.filter((item) => item.parentUniqueIdentifier === filter);
    });

    const availableSources = computed(() => {
        /** @type {Map<string, number>} */
        const counts = new Map();
        for (const item of categoryFilteredDigests.value) {
            if (item.sourcePath) {
                counts.set(item.sourcePath, (counts.get(item.sourcePath) || 0) + 1);
            }
        }
        /** @type {DigestSourceOption[]} */
        const options = [];
        for (const [path, count] of counts.entries()) {
            options.push({ path, label: formatSourceLabel(path), count });
        }
        return options.sort((a, b) => a.label.localeCompare(b.label));
    });

    watch(availableSources, (sources) => {
        if (selectedSourcePath.value && !sources.some((s) => s.path === selectedSourcePath.value)) {
            selectedSourcePath.value = null;
        }
    });

    const filteredDigests = computed(() => {
        let list = categoryFilteredDigests.value;
        if (selectedSourcePath.value) {
            list = list.filter((item) => item.sourcePath === selectedSourcePath.value);
        }
        const q = searchQuery.value.trim().toLowerCase();
        if (q) {
            list = list.filter((item) => {
                if (item.content.toLowerCase().includes(q)) return true;
                if (item.commentStr?.toLowerCase().includes(q)) return true;
                if (item.handwriting?.transcript?.toLowerCase().includes(q)) return true;
                if (item.author?.toLowerCase().includes(q)) return true;
                if (item.sourcePath?.toLowerCase().includes(q)) return true;
                return item.tags.some((t) => t.toLowerCase().includes(q));
            });
        }
        return [...list].sort(
            (a, b) =>
                (b.lastModifiedTime || b.creationTime) - (a.lastModifiedTime || a.creationTime),
        );
    });

    /**
     * Execute a digest/category mutation, reload state, and surface feedback via toast.
     * @param {() => Promise<unknown>} action
     * @param {string} successMsg
     * @param {string} errorPrefix
     * @param {ToastType} [toastType='success']
     * @returns {Promise<boolean>}
     */
    async function runMutation(action, successMsg, errorPrefix, toastType = 'success') {
        try {
            await action();
            await loadDigests();
            showToast(successMsg, toastType);
            return true;
        } catch (e) {
            showToast(`${errorPrefix}: ${getErrorMessage(e)}`);
            return false;
        }
    }

    /**
     * @param {string} name
     * @param {string | null} [description=null]
     * @returns {Promise<boolean>}
     */
    function addCategory(name, description = null) {
        if (!name.trim()) return Promise.resolve(false);
        return runMutation(
            () => createDigestCategory(name, description),
            'Category created',
            'Failed to create category',
        );
    }

    /**
     * @param {DigestCategory} category
     * @param {string} newName
     * @returns {Promise<boolean>}
     */
    function renameCategory(category, newName) {
        if (!newName.trim()) return Promise.resolve(false);
        return runMutation(
            () => updateDigestCategory(category, { name: newName }),
            'Category renamed',
            'Failed to rename category',
        );
    }

    /**
     * @param {DigestCategory} category
     * @returns {Promise<boolean>}
     */
    function removeCategory(category) {
        return runMutation(
            async () => {
                await deleteDigestCategory(category.id);
                if (selectedCategoryFilter.value === category.uniqueIdentifier) {
                    selectedCategoryFilter.value = 'all';
                }
            },
            'Category deleted',
            'Failed to delete category',
            'info',
        );
    }

    /**
     * @param {DigestInput} input
     * @returns {Promise<boolean>}
     */
    function addDigest(input) {
        if (!input.content.trim()) return Promise.resolve(false);
        return runMutation(() => createDigest(input), 'Digest created', 'Failed to create digest');
    }

    /**
     * @param {string} digestId
     * @param {DigestUpdateInput} updates
     * @returns {Promise<boolean>}
     */
    function editDigest(digestId, updates) {
        return runMutation(
            () => updateDigest(digestId, updates),
            'Digest updated',
            'Failed to update digest',
        );
    }

    /**
     * @param {string} digestId
     * @returns {Promise<boolean>}
     */
    function removeDigest(digestId) {
        return runMutation(
            () => deleteDigest(digestId),
            'Digest deleted',
            'Failed to delete digest',
            'info',
        );
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
        loadDigests,
        resetDigests,
        addCategory,
        renameCategory,
        removeCategory,
        addDigest,
        editDigest,
        removeDigest,
    };
}
