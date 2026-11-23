/**
 * Recycle Bin state management composable.
 *
 * Manages listing, restoring, permanently deleting, and clearing soft-deleted
 * items with sequence/epoch guards against stale responses and logout races.
 */

import { ref } from 'vue';
import {
    clearRecycleBin,
    deleteRecycleItems,
    fetchRecycleBin,
    revertRecycleItems,
} from '../api/client.js';
import { ApiError } from '../api/http.js';

export function useRecycleBin() {
    /** @type {import('vue').Ref<RecycleItem[]>} */
    const items = ref([]);
    /** @type {import('vue').Ref<string[]>} */
    const selectedIds = ref([]);
    const isLoading = ref(false);
    const isMutating = ref(false);
    /** @type {import('vue').Ref<string | null>} */
    const error = ref(null);
    let activeLoadSeq = 0;
    let resetEpoch = 0;

    function resetRecycleBin() {
        resetEpoch++;
        activeLoadSeq++;
        items.value = [];
        selectedIds.value = [];
        isLoading.value = false;
        isMutating.value = false;
        error.value = null;
    }

    async function loadRecycleBin() {
        const seq = ++activeLoadSeq;
        const epoch = resetEpoch;
        isLoading.value = true;
        error.value = null;
        try {
            const result = await fetchRecycleBin();
            if (seq !== activeLoadSeq || epoch !== resetEpoch) return;
            items.value = result;
            const validIds = new Set(result.map((item) => item.id));
            selectedIds.value = selectedIds.value.filter((id) => validIds.has(id));
        } catch (e) {
            if (seq !== activeLoadSeq || epoch !== resetEpoch) return;
            console.error(e);
            error.value =
                e instanceof ApiError && e.status === 401
                    ? 'Unauthorized'
                    : 'Failed to load Recycle Bin';
        } finally {
            if (seq === activeLoadSeq && epoch === resetEpoch) {
                isLoading.value = false;
            }
        }
    }

    /**
     * @param {(epoch: number) => Promise<void>} action
     */
    async function runMutation(action) {
        if (isMutating.value) return false;
        const epoch = resetEpoch;
        isMutating.value = true;
        try {
            await action(epoch);
            if (epoch !== resetEpoch) return false;
            await loadRecycleBin();
            return epoch === resetEpoch;
        } finally {
            if (epoch === resetEpoch) {
                isMutating.value = false;
            }
        }
    }

    /**
     * @param {string[]} ids
     */
    async function restoreItems(ids) {
        if (!ids.length) return false;
        const snapshot = [...ids];
        return runMutation(async (epoch) => {
            await revertRecycleItems(snapshot);
            if (epoch !== resetEpoch) return;
            const removed = new Set(snapshot);
            items.value = items.value.filter((item) => !removed.has(item.id));
            selectedIds.value = selectedIds.value.filter((id) => !removed.has(id));
        });
    }

    /**
     * @param {string[]} ids
     */
    async function deleteItemsPermanently(ids) {
        if (!ids.length) return false;
        const snapshot = [...ids];
        return runMutation(async (epoch) => {
            await deleteRecycleItems(snapshot);
            if (epoch !== resetEpoch) return;
            const removed = new Set(snapshot);
            items.value = items.value.filter((item) => !removed.has(item.id));
            selectedIds.value = selectedIds.value.filter((id) => !removed.has(id));
        });
    }

    async function emptyRecycleBin() {
        return runMutation(async (epoch) => {
            await clearRecycleBin();
            if (epoch !== resetEpoch) return;
            items.value = [];
            selectedIds.value = [];
        });
    }

    return {
        items,
        selectedIds,
        isLoading,
        isMutating,
        error,
        loadRecycleBin,
        restoreItems,
        deleteItemsPermanently,
        emptyRecycleBin,
        resetRecycleBin,
    };
}
