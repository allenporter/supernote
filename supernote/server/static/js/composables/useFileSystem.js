import { ref } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { fetchFiles, createFolder, deleteItems, moveItems, renameItem, uploadFile } from '../api/client.js';

export function useFileSystem() {
    const files = ref([]);
    const currentDirectoryId = ref("0");
    const loadedDirectoryId = ref(null);
    const isLoading = ref(false);
    const error = ref(null);
    let activeLoadSeq = 0;

    async function loadDirectory(directoryId) {
        const seq = ++activeLoadSeq;
        isLoading.value = true;
        error.value = null;
        try {
            const targetId = directoryId !== undefined ? String(directoryId) : String(currentDirectoryId.value);
            const result = await fetchFiles(targetId);
            if (seq !== activeLoadSeq) return;
            files.value = result;
            currentDirectoryId.value = targetId;
            loadedDirectoryId.value = targetId;
        } catch (e) {
            if (seq !== activeLoadSeq) return;
            console.error(e);
            loadedDirectoryId.value = null;
            if (e.message === "Unauthorized") {
                error.value = "Unauthorized";
            } else {
                error.value = "Failed to load directory";
            }
        } finally {
            if (seq === activeLoadSeq) {
                isLoading.value = false;
            }
        }
    }

    async function createNewFolder(name) {
        isLoading.value = true;
        try {
            await createFolder(currentDirectoryId.value, name);
            await loadDirectory();
        } catch (e) {
            console.error(e);
            error.value = "Failed to create folder";
            throw e;
        } finally {
            isLoading.value = false;
        }
    }

    async function deleteSelectedItems(itemIds) {
        isLoading.value = true;
        try {
            await deleteItems(currentDirectoryId.value, itemIds);
            await loadDirectory();
        } catch (e) {
            console.error(e);
            error.value = "Failed to delete items";
            throw e;
        } finally {
            isLoading.value = false;
        }
    }

    async function moveSelectedItems(itemIds, targetDirId) {
        isLoading.value = true;
        try {
            await moveItems(itemIds, targetDirId);
            await loadDirectory();
        } catch (e) {
            console.error(e);
            error.value = "Failed to move items";
            throw e;
        } finally {
            isLoading.value = false;
        }
    }

    async function uploadFiles(fileList) {
        isLoading.value = true;
        try {
            for (const file of fileList) {
                await uploadFile(currentDirectoryId.value, file);
            }
            await loadDirectory();
        } catch (e) {
            console.error(e);
            error.value = "Failed to upload files";
            throw e;
        } finally {
            isLoading.value = false;
        }
    }

    async function renameSelectedItem(id, newName) {
        isLoading.value = true;
        try {
            await renameItem(id, newName);
            await loadDirectory();
        } catch (e) {
            console.error(e);
            error.value = "Failed to rename item";
            throw e;
        } finally {
            isLoading.value = false;
        }
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
        renameSelectedItem
    };
}
