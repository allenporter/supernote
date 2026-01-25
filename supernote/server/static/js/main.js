import { createApp, ref, onMounted, computed } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { useFileSystem } from './composables/useFileSystem.js';
import { setToken, getToken, login, logout, fetchProcessingStatus } from './api/client.js';
import FileCard from './components/FileCard.js';
import LoginCard from './components/LoginCard.js';
import FileViewer from './components/FileViewer.js';
import SystemPanel from './components/SystemPanel.js';
import MoveModal from './components/MoveModal.js';
import RenameModal from './components/RenameModal.js';

createApp({
    components: {
        FileCard,
        LoginCard,
        FileViewer,
        SystemPanel,
        MoveModal,
        RenameModal
    },
    setup() {
        // Auth State
        const isLoggedIn = ref(false);
        const loginError = ref(null);
        const showSystemPanel = ref(false);

        // UI State
        const showNewFolderModal = ref(false);
        const newFolderName = ref('');
        const showMoveModal = ref(false);
        const showRenameModal = ref(false);
        const itemToRename = ref(null);
        const selectedIds = ref([]);
        const processingStatuses = ref({}); // fileId -> status string

        // File System
        const {
            files,
            currentDirectoryId,
            isLoading,
            error,
            loadDirectory,
            createNewFolder,
            deleteSelectedItems,
            moveSelectedItems,
            uploadFiles,
            renameSelectedItem
        } = useFileSystem();

        const view = ref('grid');
        const selectedFile = ref(null);
        const breadcrumbs = ref([{ id: "0", name: "Cloud" }]);

        const folders = computed(() => files.value.filter(f => f.isDirectory));
        const regularFiles = computed(() => files.value.filter(f => !f.isDirectory));

        // Methods
        async function openItem(item) {
            if (item.isDirectory) {
                currentDirectoryId.value = item.id;
                breadcrumbs.value.push({ id: item.id, name: item.name });
                selectedIds.value = [];
                await loadDirectory(item.id);
            } else {
                selectedFile.value = item;
                view.value = 'viewer';
            }
        }

        async function navigateTo(index) {
            const crumbs = breadcrumbs.value.slice(0, index + 1);
            breadcrumbs.value = crumbs;
            const target = crumbs[crumbs.length - 1];
            view.value = 'grid';
            selectedIds.value = [];
            await loadDirectory(target.id);
        }

        // Selection
        function toggleSelection(id) {
            const index = selectedIds.value.indexOf(id);
            if (index > -1) {
                selectedIds.value.splice(index, 1);
            } else {
                selectedIds.value.push(id);
            }
        }

        // Actions
        async function handleCreateFolder() {
            if (!newFolderName.value) return;
            try {
                await createNewFolder(newFolderName.value);
                showNewFolderModal.value = false;
                newFolderName.value = '';
            } catch (e) {
                alert("Failed to create folder: " + e.message);
            }
        }

        const fileInput = ref(null);
        function triggerUpload() {
            fileInput.value.click();
        }

        async function handleFileUpload(event) {
            const selectedFiles = event.target.files;
            if (selectedFiles.length === 0) return;
            try {
                await uploadFiles(selectedFiles);
            } catch (e) {
                alert("Upload failed: " + e.message);
            } finally {
                event.target.value = ''; // Reset input
            }
        }

        async function handleDeleteSelected() {
            if (!confirm(`Are you sure you want to delete ${selectedIds.value.length} items?`)) return;
            try {
                await deleteSelectedItems(selectedIds.value);
                selectedIds.value = [];
            } catch (e) {
                alert("Delete failed: " + e.message);
            }
        }

        function handleMoveSelected() {
            showMoveModal.value = true;
        }

        async function onConfirmMove(targetDirId) {
            try {
                await moveSelectedItems(selectedIds.value, targetDirId);
                selectedIds.value = [];
                showMoveModal.value = false;
            } catch (e) {
                alert("Move failed: " + e.message);
            }
        }

        function triggerRename(item) {
            itemToRename.value = item;
            showRenameModal.value = true;
        }

        async function onConfirmRename(newName) {
            try {
                await renameSelectedItem(itemToRename.value.id, newName);
                showRenameModal.value = false;
                itemToRename.value = null;
            } catch (e) {
                alert("Rename failed: " + e.message);
            }
        }

        function checkRedirect() {
            const hash = window.location.hash;
            if (hash.includes('?')) {
                const query = hash.substring(hash.indexOf('?'));
                const params = new URLSearchParams(query);
                const returnTo = params.get('return_to');
                if (returnTo) {
                    window.location.href = returnTo;
                    return true;
                }
            }
            return false;
        }

        async function handleLogin({ email, password }) {
            loginError.value = null;
            try {
                await login(email, password);
                if (checkRedirect()) return;
                isLoggedIn.value = true;
                await loadDirectory();
            } catch (e) {
                loginError.value = e.message;
                alert(e.message);
            }
        }

        function handleLogout() {
            logout();
        }

        onMounted(() => {
            if (getToken()) {
                if (checkRedirect()) return;
                isLoggedIn.value = true;
                loadDirectory();
            }

            // Polling for processing status
            setInterval(async () => {
                if (!isLoggedIn.value || isLoading.value || files.value.length === 0) return;

                const noteFileIds = files.value
                    .filter(f => f.extension === 'note')
                    .map(f => parseInt(f.id));

                if (noteFileIds.length === 0) return;

                try {
                    const result = await fetchProcessingStatus(noteFileIds);
                    if (result.success) {
                        processingStatuses.value = {
                            ...processingStatuses.value,
                            ...result.statusMap
                        };
                    }
                } catch (e) {
                    console.error("Failed to poll status:", e);
                }
            }, 3000); // Every 3 seconds
        });

        return {
            isLoggedIn,
            handleLogin,
            handleLogout,
            view,
            files,
            folders,
            regularFiles,
            currentDirectoryId,
            isLoading,
            error,
            breadcrumbs,
            openItem,
            navigateTo,
            selectedFile,
            showSystemPanel,

            // New States
            showNewFolderModal,
            newFolderName,
            showMoveModal,
            showRenameModal,
            itemToRename,
            selectedIds,
            fileInput,

            // New Methods
            toggleSelection,
            handleCreateFolder,
            triggerUpload,
            handleFileUpload,
            handleDeleteSelected,
            handleMoveSelected,
            onConfirmMove,
            triggerRename,
            onConfirmRename,
            processingStatuses
        };
    }
}).mount('#app');
