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

    /**
     * @param {string | number} [directoryId]
     */
    async function loadDirectory(directoryId) {
        const seq = ++activeLoadSeq;
        isLoading.value = true;
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
            if (seq === activeLoadSeq) {
                isLoading.value = false;
            }
        }
    }

    /**
     * Execute a VFS mutation, refresh the active directory, and surface failure state.
     * @param {() => Promise<unknown>} action
     * @param {string} failureMessage
     */
    async function runMutation(action, failureMessage) {
        isLoading.value = true;
        try {
            await action();
            await loadDirectory();
        } catch (e) {
            console.error(e);
            error.value = failureMessage;
            throw e;
        } finally {
            isLoading.value = false;
        }
    }

    /**
     * @param {string} name
     */
    async function createNewFolder(name) {
        await runMutation(
            () => createFolder(currentDirectoryId.value, name),
            'Failed to create folder',
        );
    }

    /**
     * @param {string[]} itemIds
     */
    async function deleteSelectedItems(itemIds) {
        await runMutation(
            () => deleteItems(currentDirectoryId.value, itemIds),
            'Failed to delete items',
        );
    }

    /**
     * @param {string[]} itemIds
     * @param {string} targetDirId
     */
    async function moveSelectedItems(itemIds, targetDirId) {
        await runMutation(() => moveItems(itemIds, targetDirId), 'Failed to move items');
    }

    /**
     * @param {FileList | File[]} fileList
     */
    async function uploadFiles(fileList) {
        await runMutation(async () => {
            for (const file of fileList) {
                await uploadFile(currentDirectoryId.value, file);
            }
        }, 'Failed to upload files');
    }

    /**
     * @param {string | number} id
     * @param {string} newName
     */
    async function renameSelectedItem(id, newName) {
        await runMutation(() => renameItem(id, newName), 'Failed to rename item');
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
    };
}
