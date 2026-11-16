import { ref } from 'vue';
import {
    createFolder,
    deleteItems,
    fetchFiles,
    moveItems,
    renameItem,
    uploadFile,
} from '../api/client.js';
import { ApiError } from '../api/http.js';

export function useFileSystem() {
    /** @type {import('vue').Ref<FileItem[]>} */
    const files = ref([]);
    /** @type {import('vue').Ref<string>} */
    const currentDirectoryId = ref('0');
    /** @type {import('vue').Ref<string | null>} */
    const loadedDirectoryId = ref(null);
    const isLoading = ref(false);
    /** @type {import('vue').Ref<string | null>} */
    const error = ref(null);
    let activeLoadSeq = 0;
    let activeOps = 0;
    let resetEpoch = 0;

    function beginOp() {
        const epoch = resetEpoch;
        activeOps++;
        isLoading.value = true;
        return () => {
            if (epoch === resetEpoch) {
                activeOps = Math.max(0, activeOps - 1);
                isLoading.value = activeOps > 0;
            }
        };
    }

    function resetFileSystem() {
        resetEpoch++;
        activeLoadSeq++;
        activeOps = 0;
        files.value = [];
        currentDirectoryId.value = '0';
        loadedDirectoryId.value = null;
        isLoading.value = false;
        error.value = null;
    }

    /**
     * @param {string | number} [directoryId]
     */
    async function loadDirectory(directoryId) {
        const seq = ++activeLoadSeq;
        const finishOp = beginOp();
        error.value = null;
        try {
            const targetId =
                directoryId !== undefined ? String(directoryId) : String(currentDirectoryId.value);
            const result = await fetchFiles(targetId);
            if (seq !== activeLoadSeq) return;
            files.value = result;
            currentDirectoryId.value = targetId;
            loadedDirectoryId.value = targetId;
        } catch (e) {
            if (seq !== activeLoadSeq) return;
            console.error(e);
            loadedDirectoryId.value = null;
            error.value =
                e instanceof ApiError && e.status === 401
                    ? 'Unauthorized'
                    : 'Failed to load directory';
        } finally {
            finishOp();
        }
    }

    /**
     * Execute a VFS mutation, refresh the affected directory if still active, and surface failure state.
     * @param {() => Promise<unknown>} action
     * @param {string} failureMessage
     * @param {string[]} [affectedDirIds]
     */
    async function runMutation(action, failureMessage, affectedDirIds) {
        const epoch = resetEpoch;
        const finishOp = beginOp();
        error.value = null;
        try {
            await action();
            if (
                epoch === resetEpoch &&
                (!affectedDirIds || affectedDirIds.includes(String(currentDirectoryId.value)))
            ) {
                await loadDirectory(currentDirectoryId.value);
            }
        } catch (e) {
            if (epoch === resetEpoch) {
                console.error(e);
                error.value = failureMessage;
            }
            throw e;
        } finally {
            finishOp();
        }
    }

    /**
     * @param {string} name
     */
    async function createNewFolder(name) {
        const targetDirId = String(currentDirectoryId.value);
        await runMutation(() => createFolder(targetDirId, name), 'Failed to create folder', [
            targetDirId,
        ]);
    }

    /**
     * @param {string[]} itemIds
     */
    async function deleteSelectedItems(itemIds) {
        const targetDirId = String(currentDirectoryId.value);
        await runMutation(() => deleteItems(targetDirId, itemIds), 'Failed to delete items', [
            targetDirId,
        ]);
    }

    /**
     * @param {string[]} itemIds
     * @param {string} targetDirId
     */
    async function moveSelectedItems(itemIds, targetDirId) {
        const sourceDirId = String(currentDirectoryId.value);
        await runMutation(() => moveItems(itemIds, targetDirId), 'Failed to move items', [
            sourceDirId,
            String(targetDirId),
        ]);
    }

    /**
     * @param {FileList | File[]} fileList
     */
    async function uploadFiles(fileList) {
        const targetDirId = String(currentDirectoryId.value);
        const snapshot = Array.from(fileList);
        await runMutation(
            async () => {
                for (const file of snapshot) {
                    await uploadFile(targetDirId, file);
                }
            },
            'Failed to upload files',
            [targetDirId],
        );
    }

    /**
     * @param {string | number} id
     * @param {string} newName
     */
    async function renameSelectedItem(id, newName) {
        const sourceDirId = String(currentDirectoryId.value);
        await runMutation(() => renameItem(id, newName), 'Failed to rename item', [sourceDirId]);
    }

    return {
        files,
        currentDirectoryId,
        loadedDirectoryId,
        isLoading,
        error,
        loadDirectory,
        createNewFolder,
        deleteSelectedItems,
        moveSelectedItems,
        uploadFiles,
        renameSelectedItem,
        resetFileSystem,
    };
}
