import { ref } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { fetchFiles } from '../api/client.js';

export function useFileSystem() {
    const files = ref([]);
    const currentDirectoryId = ref("0");
    const isLoading = ref(false);
    const error = ref(null);

    async function loadDirectory(directoryId) {
        isLoading.value = true;
        error.value = null;
        try {
            // If directoryId is not provided, use existing currentDirectoryId
            const targetId = directoryId !== undefined ? directoryId : currentDirectoryId.value;

            const result = await fetchFiles(targetId);
            files.value = result;
            currentDirectoryId.value = targetId;
        } catch (e) {
            console.error(e);
            if (e.message === "Unauthorized") {
                error.value = "Unauthorized";
            } else {
                error.value = "Failed to load directory";
            }
        } finally {
            isLoading.value = false;
        }
    }

    return {
        files,
        currentDirectoryId,
        isLoading,
        error,
        loadDirectory
    };
}
