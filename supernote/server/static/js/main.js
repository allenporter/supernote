import { createApp, ref, onMounted, computed, watch, nextTick } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { useFileSystem } from './composables/useFileSystem.js';
import { useToast } from './composables/useToast.js';
import { setToken, getToken, login, logout, fetchProcessingStatus, fetchPathInfo, connectSocket } from './api/client.js';
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
import SettingsView from './components/SettingsView.js';

const SYSTEM_ROOT_UPPER = new Set(['EXPORT', 'INBOX', 'SCREENSHOT']);

function formatCrumbName(name, index) {
    if (index === 0 && SYSTEM_ROOT_UPPER.has(name)) {
        return name.charAt(0) + name.slice(1).toLowerCase();
    }
    return name;
}

function buildCrumbsFromPathInfo(info) {
    const crumbs = [{ id: '0', name: 'Cloud' }];
    if (info && info.path && info.idPath) {
        const names = info.path.split('/').filter(Boolean);
        const ids = info.idPath.split('/').filter(Boolean);
        const len = Math.min(names.length, ids.length);
        for (let i = 0; i < len; i++) {
            crumbs.push({
                id: String(ids[i]),
                name: formatCrumbName(names[i], i)
            });
        }
    }
    return crumbs;
}

export function parseUrlHash(hashString) {
    const raw = hashString !== undefined ? hashString : (window.location.hash || window.location.search || '');
    const clean = raw.replace(/^[#?]\/?/, '').trim();

    if (!clean) {
        return { tab: 'files', view: 'grid', dirId: '0', showSystem: false };
    }

    if (clean.includes('=')) {
        const queryPart = clean.includes('?') ? clean.split('?')[1] : clean;
        const params = new URLSearchParams(queryPart);
        if (params.get('tab') === 'system' || params.get('view') === 'system') {
            return { tab: 'system', view: 'grid', dirId: params.get('dir') || '0', showSystem: true };
        }
        if (params.get('tab') === 'tasks' || params.get('view') === 'tasks') {
            return { tab: 'tasks', view: 'grid', dirId: '0', showSystem: false };
        }
        if (params.get('tab') === 'settings' || params.get('view') === 'settings') {
            return { tab: 'settings', view: 'grid', dirId: '0', showSystem: false };
        }
        if (params.has('file')) {
            return {
                tab: 'files',
                view: 'viewer',
                fileId: params.get('file'),
                dirId: params.get('dir') || null,
                showSystem: false
            };
        }
        if (params.has('dir') || params.has('folder')) {
            return {
                tab: 'files',
                view: 'grid',
                dirId: params.get('dir') || params.get('folder') || '0',
                showSystem: false
            };
        }
    }

    const parts = clean.split('/').filter(Boolean);

    if (parts[0] === 'system') {
        return { tab: 'system', view: 'grid', dirId: '0', showSystem: true };
    }

    if (parts[0] === 'tasks') {
        return { tab: 'tasks', view: 'grid', dirId: '0', showSystem: false };
    }

    if (parts[0] === 'settings') {
        return { tab: 'settings', view: 'grid', dirId: '0', showSystem: false };
    }

    if (parts[0] === 'file' && parts[1]) {
        return { tab: 'files', view: 'viewer', fileId: parts[1], showSystem: false };
    }

    if ((parts[0] === 'files' || parts[0] === 'explorer') && parts[1] === 'file' && parts[2]) {
        return { tab: 'files', view: 'viewer', fileId: parts[2], showSystem: false };
    }

    if ((parts[0] === 'files' || parts[0] === 'explorer') && parts[2] === 'file' && parts[3]) {
        return { tab: 'files', view: 'viewer', dirId: parts[1], fileId: parts[3], showSystem: false };
    }

    if ((parts[0] === 'files' || parts[0] === 'explorer' || parts[0] === 'folder') && parts[1]) {
        return { tab: 'files', view: 'grid', dirId: parts[1], showSystem: false };
    }

    if (parts[0] === 'files' || parts[0] === 'explorer') {
        return { tab: 'files', view: 'grid', dirId: '0', showSystem: false };
    }

    return { tab: 'files', view: 'grid', dirId: '0', showSystem: false };
}

export function buildUrlHash(tab, dirId, viewState, fileObj, showSystem = false) {
    if (showSystem || tab === 'system') {
        return '#/system';
    }
    if (tab === 'tasks') {
        return '#/tasks';
    }
    if (tab === 'settings') {
        return '#/settings';
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
        RenameModal,
        SettingsView
    },
    setup() {
        const { toasts, showToast, dismissToast } = useToast();

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
        const activeTab = ref('files'); // 'files' | 'explorer' | 'tasks' | 'dashboard' | 'settings'
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
            loadedDirectoryId,
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
        const ROUTING_QUERY_KEYS = ['dir', 'folder', 'file', 'tab', 'view'];
        let urlSyncDepth = 0;
        let activeSyncSeq = 0;
        let lastSyncedHash = '';
        let inAppHistoryDepth = 0;
        let viewerOpenedFromHistory = false;
        let systemOpenedFromHistory = false;

        async function syncBreadcrumbsForDirectory(dirId, seq = activeSyncSeq) {
            const targetId = String(dirId || '0');
            if (targetId === '0') {
                breadcrumbs.value = [{ id: '0', name: 'Cloud' }];
                return true;
            }
            try {
                const info = await fetchPathInfo(targetId);
                if (seq !== activeSyncSeq || String(currentDirectoryId.value) !== targetId) {
                    return true;
                }
                const crumbs = buildCrumbsFromPathInfo(info);
                if (crumbs.length <= 1) {
                    return false;
                }
                breadcrumbs.value = crumbs;
                return true;
            } catch (e) {
                console.error("Failed to resolve directory breadcrumbs:", e);
                return true;
            }
        }

        function hasRoutingQueryParams(searchStr) {
            if (!searchStr) return false;
            const params = new URLSearchParams(searchStr);
            return ROUTING_QUERY_KEYS.some(key => params.has(key));
        }

        function updateUrl(replace = false) {
            if (urlSyncDepth > 0) return;
            const targetHash = buildUrlHash(
                activeTab.value,
                currentDirectoryId.value,
                view.value,
                selectedFile.value,
                showSystemPanel.value
            );
            lastSyncedHash = targetHash;
            const stripQuery = hasRoutingQueryParams(window.location.search);
            const targetUrl = stripQuery ? `${window.location.pathname}${targetHash}` : targetHash;
            if (window.location.hash !== targetHash || stripQuery) {
                if (replace) {
                    window.history.replaceState(null, '', targetUrl);
                } else {
                    inAppHistoryDepth++;
                    window.history.pushState(null, '', targetUrl);
                }
            }
        }

        async function restoreSystemView(isInitial, seq) {
            showSystemPanel.value = true;
            if (activeTab.value === 'system') {
                activeTab.value = 'files';
            }
            const targetDirId = String(currentDirectoryId.value || '0');
            if (!isInitial && loadedDirectoryId.value === targetDirId) return;
            await Promise.all([
                loadDirectory(targetDirId),
                syncBreadcrumbsForDirectory(targetDirId, seq)
            ]);
        }

        async function restoreViewerState(targetFileId, seq) {
            const existingFile = files.value.find(f => String(f.id) === targetFileId);
            if (existingFile) {
                selectedFile.value = existingFile;
                view.value = 'viewer';
                const currentLastCrumbId = String(breadcrumbs.value[breadcrumbs.value.length - 1]?.id || '0');
                if (currentLastCrumbId !== String(currentDirectoryId.value)) {
                    await syncBreadcrumbsForDirectory(currentDirectoryId.value, seq);
                }
                return;
            }

            try {
                const info = await fetchPathInfo(targetFileId);
                if (seq !== activeSyncSeq) return;
                const allCrumbs = buildCrumbsFromPathInfo(info);
                if (allCrumbs.length <= 1) {
                    selectedFile.value = {
                        id: targetFileId,
                        name: `Notebook ${targetFileId}`,
                        extension: 'note'
                    };
                    view.value = 'viewer';
                    return;
                }

                const fileCrumb = allCrumbs[allCrumbs.length - 1];
                const folderCrumbs = allCrumbs.slice(0, -1);
                const parentDirId = String(folderCrumbs[folderCrumbs.length - 1].id);
                const ext = fileCrumb.name.includes('.')
                    ? fileCrumb.name.split('.').pop().toLowerCase()
                    : 'note';

                breadcrumbs.value = folderCrumbs;
                currentDirectoryId.value = parentDirId;
                selectedFile.value = {
                    id: targetFileId,
                    name: fileCrumb.name,
                    extension: ext
                };
                view.value = 'viewer';

                await loadDirectory(parentDirId);
                if (seq !== activeSyncSeq) return;
                const loadedFile = files.value.find(f => String(f.id) === targetFileId);
                if (loadedFile) {
                    selectedFile.value = loadedFile;
                }
            } catch (e) {
                if (seq !== activeSyncSeq) return;
                console.error("Failed to resolve file path info:", e);
                selectedFile.value = {
                    id: targetFileId,
                    name: `Notebook ${targetFileId}`,
                    extension: 'note'
                };
                view.value = 'viewer';
            }
        }

        async function restoreDirectoryState(targetDirId, isInitial, seq) {
            view.value = 'grid';
            selectedFile.value = null;
            selectedIds.value = [];

            const dirChanged = String(currentDirectoryId.value) !== targetDirId;
            const lastCrumbId = String(breadcrumbs.value[breadcrumbs.value.length - 1]?.id || '0');
            if (!dirChanged && !isInitial && loadedDirectoryId.value === targetDirId) {
                if (lastCrumbId !== targetDirId) {
                    await syncBreadcrumbsForDirectory(targetDirId, seq);
                }
                return;
            }

            currentDirectoryId.value = targetDirId;
            const [, dirExists] = await Promise.all([
                loadDirectory(targetDirId),
                syncBreadcrumbsForDirectory(targetDirId, seq)
            ]);
            if (seq !== activeSyncSeq) return;
            if (!dirExists && targetDirId !== '0') {
                currentDirectoryId.value = '0';
                breadcrumbs.value = [{ id: '0', name: 'Cloud' }];
                lastSyncedHash = '#/files';
                window.history.replaceState(null, '', '#/files');
                await loadDirectory('0');
            }
        }

        async function syncFromUrl(isInitial = false) {
            const currentHash = window.location.hash || window.location.search || '';
            if (!isInitial && currentHash === lastSyncedHash) {
                return;
            }
            lastSyncedHash = currentHash;
            if (!isInitial && inAppHistoryDepth > 0) {
                inAppHistoryDepth--;
            }

            const seq = ++activeSyncSeq;
            const parsed = parseUrlHash(currentHash);
            urlSyncDepth++;
            try {
                if (parsed.tab === 'system' || parsed.showSystem) {
                    await restoreSystemView(isInitial, seq);
                    return;
                }
                showSystemPanel.value = false;
                systemOpenedFromHistory = false;

                if (parsed.tab === 'tasks' || parsed.tab === 'settings') {
                    activeTab.value = parsed.tab;
                    view.value = 'grid';
                    selectedFile.value = null;
                    viewerOpenedFromHistory = false;
                    return;
                }

                activeTab.value = 'files';
                if (parsed.view === 'viewer' && parsed.fileId) {
                    await restoreViewerState(String(parsed.fileId), seq);
                    return;
                }

                viewerOpenedFromHistory = false;
                await restoreDirectoryState(String(parsed.dirId || '0'), isInitial, seq);
            } finally {
                await nextTick();
                urlSyncDepth--;
            }
        }

        watch([activeTab, currentDirectoryId, view, () => selectedFile.value?.id, showSystemPanel], () => {
            updateUrl();
        });

        // Methods
        async function switchTab(tab) {
            showSystemPanel.value = false;
            systemOpenedFromHistory = false;
            activeTab.value = tab;
            if (tab === 'files' || tab === 'explorer' || tab === 'dashboard') {
                viewerOpenedFromHistory = false;
                await restoreDirectoryState(String(currentDirectoryId.value || '0'), false, ++activeSyncSeq);
            }
        }

        function openSystemPanel() {
            systemOpenedFromHistory = true;
            showSystemPanel.value = true;
        }

        async function closeSystemPanel() {
            if (systemOpenedFromHistory && inAppHistoryDepth > 0) {
                systemOpenedFromHistory = false;
                window.history.back();
                return;
            }
            systemOpenedFromHistory = false;
            urlSyncDepth++;
            showSystemPanel.value = false;
            await nextTick();
            urlSyncDepth--;
            updateUrl(true);
            if ((activeTab.value === 'files' || activeTab.value === 'explorer' || activeTab.value === 'dashboard') && view.value === 'grid') {
                await restoreDirectoryState(String(currentDirectoryId.value || '0'), false, ++activeSyncSeq);
            }
        }

        async function closeViewer() {
            if (viewerOpenedFromHistory && inAppHistoryDepth > 0) {
                viewerOpenedFromHistory = false;
                window.history.back();
                return;
            }
            viewerOpenedFromHistory = false;
            urlSyncDepth++;
            view.value = 'grid';
            selectedFile.value = null;
            await nextTick();
            urlSyncDepth--;
            updateUrl(true);
            await restoreDirectoryState(String(currentDirectoryId.value || '0'), false, ++activeSyncSeq);
        }

        async function openItem(item) {
            if (item.isDirectory) {
                activeTab.value = 'files';
                view.value = 'grid';
                selectedFile.value = null;
                viewerOpenedFromHistory = false;
                currentDirectoryId.value = String(item.id);
                const existingIndex = breadcrumbs.value.findIndex(c => String(c.id) === String(item.id));
                if (existingIndex > -1) {
                    breadcrumbs.value = breadcrumbs.value.slice(0, existingIndex + 1);
                } else {
                    breadcrumbs.value.push({ id: String(item.id), name: item.name });
                }
                selectedIds.value = [];
                await loadDirectory(item.id);
            } else {
                viewerOpenedFromHistory = true;
                selectedFile.value = item;
                view.value = 'viewer';
            }
        }

        async function navigateFolder(folder) {
            activeTab.value = 'files';
            view.value = 'grid';
            selectedFile.value = null;
            viewerOpenedFromHistory = false;
            currentDirectoryId.value = String(folder.id);
            selectedIds.value = [];
            await Promise.all([
                loadDirectory(folder.id),
                syncBreadcrumbsForDirectory(folder.id)
            ]);
        }

        async function navigateTo(index) {
            const crumbs = breadcrumbs.value.slice(0, index + 1);
            breadcrumbs.value = crumbs;
            const target = crumbs[crumbs.length - 1];
            view.value = 'grid';
            selectedFile.value = null;
            viewerOpenedFromHistory = false;
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
                showToast("Failed to create folder: " + e.message);
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
                showToast("Upload failed: " + e.message);
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
                showToast("Delete failed: " + e.message);
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
                showToast("Move failed: " + e.message);
            }
        }

        function triggerRename(item) {
            itemToRename.value = item;
            showRenameModal.value = true;
        }

        async function onConfirmRename(newName) {
            try {
                const renamedId = itemToRename.value.id;
                await renameSelectedItem(renamedId, newName);
                const crumb = breadcrumbs.value.find(c => String(c.id) === String(renamedId));
                if (crumb) {
                    crumb.name = newName;
                }
                showRenameModal.value = false;
                itemToRename.value = null;
            } catch (e) {
                showToast("Rename failed: " + e.message);
            }
        }

        async function resumeSession() {
            const token = getToken();
            if (!token) return false;
            isLoggedIn.value = true;
            connectSocket();
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
                showToast(e.message);
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
            window.addEventListener('supernote:file-sync', () => {
                if (!isLoggedIn.value) return;
                loadDirectory(currentDirectoryId.value || '0');
            });

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
            switchTab,
            openSystemPanel,
            closeSystemPanel,
            closeViewer,
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
            processingStatuses,
            toasts,
            showToast,
            dismissToast
        };
    }
}).mount('#app');
