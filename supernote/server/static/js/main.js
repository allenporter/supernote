import { createApp, ref, onMounted, computed, watch } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { useFileSystem } from './composables/useFileSystem.js';
import { setToken, getToken, login, logout, fetchProcessingStatus } from './api/client.js';
import Sidebar from './components/Sidebar.js';
import DashboardView from './components/DashboardView.js';
import SearchModal from './components/SearchModal.js';
import TaskPanel from './components/TaskPanel.js';
import FileCard from './components/FileCard.js';
import LoginCard from './components/LoginCard.js';
import FileViewer from './components/FileViewer.js';
import SystemPanel from './components/SystemPanel.js';
import MoveModal from './components/MoveModal.js';
import RenameModal from './components/RenameModal.js';

function parseUrlHash(hashString) {
    const raw = hashString || window.location.hash || '';
    const clean = raw.replace(/^#\/?/, '').trim();

    if (!clean) {
        return { tab: 'files', view: 'grid', dirId: '0' };
    }

    if (clean.includes('=')) {
        const queryPart = clean.includes('?') ? clean.split('?')[1] : clean;
        const params = new URLSearchParams(queryPart);
        if (params.has('file')) {
            return { tab: 'files', view: 'viewer', fileId: params.get('file') };
        }
        if (params.has('dir')) {
            return { tab: 'files', view: 'grid', dirId: params.get('dir') };
        }
        if (params.get('tab') === 'tasks') {
            return { tab: 'tasks', view: 'grid' };
        }
    }

    const parts = clean.split('/');

    if (parts[0] === 'tasks') {
        return { tab: 'tasks', view: 'grid' };
    }

    if (parts[0] === 'file' && parts[1]) {
        return { tab: 'files', view: 'viewer', fileId: parts[1] };
    }

    if ((parts[0] === 'files' || parts[0] === 'explorer') && parts[1] === 'file' && parts[2]) {
        return { tab: 'files', view: 'viewer', fileId: parts[2] };
    }

    if ((parts[0] === 'files' || parts[0] === 'explorer') && parts[1]) {
        return { tab: 'files', view: 'grid', dirId: parts[1] };
    }

    if (parts[0] === 'files' || parts[0] === 'explorer') {
        return { tab: 'files', view: 'grid', dirId: '0' };
    }

    return { tab: 'files', view: 'grid', dirId: '0' };
}

function buildUrlHash(tab, dirId, viewState, fileObj) {
    if (tab === 'tasks') {
        return '#/tasks';
    }
    if (viewState === 'viewer' && fileObj && fileObj.id) {
        return `#/file/${fileObj.id}`;
    }
    if (dirId && String(dirId) !== '0') {
        return `#/files/${dirId}`;
    }
    return '#/files';
}

createApp({
    components: {
        Sidebar,
        DashboardView,
        SearchModal,
        TaskPanel,
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

        // Theme Mode
        const isDarkMode = ref(localStorage.getItem('supernote_theme') === 'dark');

        const toggleTheme = () => {
            isDarkMode.value = !isDarkMode.value;
            localStorage.setItem('supernote_theme', isDarkMode.value ? 'dark' : 'light');
            if (isDarkMode.value) {
                document.documentElement.classList.add('dark');
            } else {
                document.documentElement.classList.remove('dark');
            }
        };

        // Navigation State
        const activeTab = ref('files'); // 'files' | 'explorer' | 'tasks' | 'dashboard'
        const showSearchModal = ref(false);
        const isSidebarOpen = ref(false);

        // UI Modals State
        const showNewFolderModal = ref(false);
        const newFolderName = ref('');
        const showMoveModal = ref(false);
        const showRenameModal = ref(false);
        const itemToRename = ref(null);
        const selectedIds = ref([]);
        const processingStatuses = ref({});

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
        const recentNotes = computed(() => files.value.filter(f => f.extension === 'note'));

        // URL Routing Synchronization
        let isUpdatingFromUrl = false;

        function updateUrl(replace = false) {
            if (isUpdatingFromUrl) return;
            const targetHash = buildUrlHash(activeTab.value, currentDirectoryId.value, view.value, selectedFile.value);
            if (window.location.hash !== targetHash) {
                if (replace) {
                    window.history.replaceState(null, '', targetHash);
                } else {
                    window.history.pushState(null, '', targetHash);
                }
            }
        }

        async function syncFromUrl(isInitial = false) {
            const parsed = parseUrlHash(window.location.hash);
            isUpdatingFromUrl = true;
            try {
                if (parsed.tab === 'tasks') {
                    activeTab.value = 'tasks';
                    view.value = 'grid';
                } else {
                    activeTab.value = 'files';
                    if (parsed.view === 'viewer' && parsed.fileId) {
                        view.value = 'viewer';
                        const existingFile = files.value.find(f => String(f.id) === String(parsed.fileId));
                        if (existingFile) {
                            selectedFile.value = existingFile;
                        } else {
                            selectedFile.value = {
                                id: parsed.fileId,
                                name: `Notebook ${parsed.fileId}`,
                                extension: 'note'
                            };
                        }
                    } else {
                        view.value = 'grid';
                        const targetDirId = parsed.dirId || '0';
                        if (String(currentDirectoryId.value) !== String(targetDirId) || isInitial || files.value.length === 0) {
                            currentDirectoryId.value = targetDirId;
                            await loadDirectory(targetDirId);
                        }
                    }
                }
            } finally {
                isUpdatingFromUrl = false;
            }
        }

        watch([activeTab, currentDirectoryId, view, () => selectedFile.value?.id], () => {
            updateUrl();
        });

        // Methods
        async function openItem(item) {
            if (item.isDirectory) {
                activeTab.value = 'files';
                currentDirectoryId.value = String(item.id);
                const existingCrumb = breadcrumbs.value.find(c => String(c.id) === String(item.id));
                if (!existingCrumb) {
                    breadcrumbs.value.push({ id: String(item.id), name: item.name });
                }
                selectedIds.value = [];
                await loadDirectory(item.id);
            } else {
                selectedFile.value = item;
                view.value = 'viewer';
            }
        }

        async function navigateFolder(folder) {
            activeTab.value = 'files';
            view.value = 'grid';
            currentDirectoryId.value = String(folder.id);
            breadcrumbs.value = [{ id: "0", name: "Cloud" }];
            if (String(folder.id) !== "0") {
                breadcrumbs.value.push({ id: String(folder.id), name: folder.name });
            }
            selectedIds.value = [];
            await loadDirectory(folder.id);
        }

        async function navigateTo(index) {
            const crumbs = breadcrumbs.value.slice(0, index + 1);
            breadcrumbs.value = crumbs;
            const target = crumbs[crumbs.length - 1];
            view.value = 'grid';
            currentDirectoryId.value = String(target.id);
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
                event.target.value = '';
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

        async function resumeSession() {
            const token = getToken();
            if (!token) return false;
            isLoggedIn.value = true;
            return true;
        }

        async function handleLogin({ email, password }) {
            loginError.value = null;
            try {
                await login(email, password);
                const loggedIn = await resumeSession();
                if (loggedIn) {
                    await syncFromUrl(true);
                    updateUrl(true);
                }
            } catch (e) {
                loginError.value = e.message;
                alert(e.message);
            }
        }

        function handleLogout() {
            logout();
        }

        onMounted(async () => {
            if (isDarkMode.value) {
                document.documentElement.classList.add('dark');
            }
            const loggedIn = await resumeSession();
            if (loggedIn) {
                await syncFromUrl(true);
                updateUrl(true);
            }

            window.addEventListener('popstate', () => syncFromUrl());
            window.addEventListener('hashchange', () => syncFromUrl());

            // Keyboard shortcut ⌘K for search
            window.addEventListener('keydown', (e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                    e.preventDefault();
                    showSearchModal.value = !showSearchModal.value;
                }
            });

            // Status Polling
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
                    console.error("Status poll error:", e);
                }
            }, 3000);
        });

        return {
            isLoggedIn,
            handleLogin,
            handleLogout,
            isDarkMode,
            toggleTheme,
            activeTab,
            showSearchModal,
            isSidebarOpen,
            view,
            files,
            folders,
            regularFiles,
            recentNotes,
            currentDirectoryId,
            isLoading,
            error,
            breadcrumbs,
            openItem,
            navigateFolder,
            navigateTo,
            selectedFile,
            showSystemPanel,
            showNewFolderModal,
            newFolderName,
            showMoveModal,
            showRenameModal,
            itemToRename,
            selectedIds,
            fileInput,
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
