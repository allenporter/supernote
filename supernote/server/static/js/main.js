import { createApp, ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue';
import { useFileSystem } from './composables/useFileSystem.js';
import { useProcessingStatus } from './composables/useProcessingStatus.js';
import { useRouter, parseUrlHash, buildUrlHash } from './composables/useRouter.js';
import { useToast } from './composables/useToast.js';
import { getToken, login, logout, connectSocket } from './api/client.js';
import { normalizeEpochMs } from './utils/format.js';
import SearchModal from './components/SearchModal.js';
import TaskPanel from './components/TaskPanel.js';
import FileCard from './components/FileCard.js';
import LoginCard from './components/LoginCard.js';
import OAuthConsentCard from './components/OAuthConsentCard.js';
import FileViewer from './components/FileViewer.js';
import SystemPanel from './components/SystemPanel.js';
import MoveModal from './components/MoveModal.js';
import RenameModal from './components/RenameModal.js';

export { parseUrlHash, buildUrlHash };

export function compareItems(a, b, sortBy, sortOrder) {
    const aIsFolder = Boolean(a.isDirectory || (a.isFolder && a.isFolder !== 'N'));
    const bIsFolder = Boolean(b.isDirectory || (b.isFolder && b.isFolder !== 'N'));
    if (aIsFolder !== bIsFolder) {
        return aIsFolder ? -1 : 1;
    }
    if (sortBy === 'updatedAt') {
        const tsA = normalizeEpochMs(a.updatedAt);
        const tsB = normalizeEpochMs(b.updatedAt);
        if (tsA === null && tsB !== null) return 1;
        if (tsA !== null && tsB === null) return -1;
        if (tsA !== null && tsB !== null && tsA !== tsB) {
            return sortOrder === 'desc' ? tsB - tsA : tsA - tsB;
        }
    } else if (sortBy === 'size') {
        const sizeCmp = (Number(a.size) || 0) - (Number(b.size) || 0);
        if (sizeCmp !== 0) {
            return sortOrder === 'desc' ? -sizeCmp : sizeCmp;
        }
    }
    const nameCmp = String(a.name || '').localeCompare(String(b.name || ''), undefined, {
        numeric: true,
        sensitivity: 'base'
    });
    return sortOrder === 'desc' ? -nameCmp : nameCmp;
}

createApp({
    components: {
        SearchModal,
        TaskPanel,
        FileCard,
        LoginCard,
        'oauth-consent-card': OAuthConsentCard,
        FileViewer,
        SystemPanel,
        MoveModal,
        RenameModal
    },
    setup() {
        const { toasts, showToast, dismissToast } = useToast();

        // Auth & OAuth Consent State
        const isLoggedIn = ref(false);
        const isSubmittingOAuth = ref(false);
        const oauthCompletedOutcome = ref(null);

        // Search & Display State
        const showSearchModal = ref(false);
        const searchInitialQuery = ref('');
        const searchShortcutLabel = typeof navigator !== 'undefined' &&
            /Mac|iPod|iPhone|iPad/i.test(navigator.platform || navigator.userAgent || '')
            ? '⌘K'
            : 'Ctrl K';
        const displayMode = ref('grid'); // 'grid' | 'list'
        const sortBy = ref('name'); // 'name' | 'updatedAt' | 'size'
        const sortOrder = ref('asc'); // 'asc' | 'desc'
        const isDraggingOver = ref(false);
        const focusedTaskRequest = ref(null);

        // UI Modals State
        const showNewFolderModal = ref(false);
        const newFolderName = ref('');
        const newFolderInput = ref(null);
        const showMoveModal = ref(false);
        const showRenameModal = ref(false);
        const showDeleteModal = ref(false);
        const itemToRename = ref(null);
        const selectedIds = ref([]);

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

        // Host Navigation & URL Routing
        const {
            activeTab,
            view,
            selectedFile,
            selectedPageIndex,
            selectedPageJumpSeq,
            breadcrumbs,
            showSystemPanel,
            pendingOAuthRequest,
            syncFromUrl,
            updateUrl,
            clearOAuthRoute,
            switchTab,
            openSystemPanel,
            closeSystemPanel,
            closeViewer,
            handleViewerPageChange,
            openItem,
            navigateFolder,
            navigateTo,
            navigateToTarget
        } = useRouter({
            isLoggedIn,
            files,
            currentDirectoryId,
            loadedDirectoryId,
            loadDirectory,
            selectedIds,
            onBeforeNavigate: () => {
                isDraggingOver.value = false;
            },
            onOAuthRouteEnter: () => {
                isSubmittingOAuth.value = false;
                oauthCompletedOutcome.value = null;
                showSearchModal.value = false;
            },
            onOAuthRouteClear: () => {
                isSubmittingOAuth.value = false;
                oauthCompletedOutcome.value = null;
            }
        });

        const GRID_PAGE_SIZE = 50;
        const visibleLimit = ref(GRID_PAGE_SIZE);
        watch(currentDirectoryId, () => {
            visibleLimit.value = GRID_PAGE_SIZE;
            isDraggingOver.value = false;
        });

        watch(showNewFolderModal, (isOpen) => {
            if (isOpen) {
                nextTick(() => newFolderInput.value?.focus());
            } else {
                newFolderName.value = '';
            }
        });

        const allFolders = computed(() => {
            const list = files.value.filter(f => f.isDirectory);
            return [...list].sort((a, b) => compareItems(a, b, sortBy.value, sortOrder.value));
        });
        const allRegularFiles = computed(() => {
            const list = files.value.filter(f => !f.isDirectory);
            return [...list].sort((a, b) => compareItems(a, b, sortBy.value, sortOrder.value));
        });
        const folders = computed(() => allFolders.value.slice(0, visibleLimit.value));
        const regularFiles = computed(() => {
            const remaining = Math.max(0, visibleLimit.value - folders.value.length);
            return allRegularFiles.value.slice(0, remaining);
        });
        const totalItemCount = computed(() => files.value.length);
        const visibleItemCount = computed(() => folders.value.length + regularFiles.value.length);
        const hasMoreItems = computed(() => visibleItemCount.value < totalItemCount.value);

        function loadMoreItems() {
            visibleLimit.value += GRID_PAGE_SIZE;
        }

        function handleSortByChange() {
            sortOrder.value = (sortBy.value === 'updatedAt' || sortBy.value === 'size') ? 'desc' : 'asc';
        }

        function toggleSortOrder() {
            sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc';
        }

        watch([sortBy, sortOrder], () => {
            if (hasMoreItems.value && selectedIds.value.length > 0) {
                const visibleSet = new Set([
                    ...folders.value.map(f => f.id),
                    ...regularFiles.value.map(f => f.id)
                ]);
                selectedIds.value = selectedIds.value.filter(id => visibleSet.has(id));
            }
        });

        async function handleSearchSelectFile(item) {
            if (!item) return;
            showSearchModal.value = false;
            await navigateToTarget(item);
        }

        async function handleSearchSelectTask(task) {
            showSearchModal.value = false;
            focusedTaskRequest.value = task
                ? {
                    id: task.id,
                    title: task.title || '',
                    status: task.status || 'needsAction',
                    seq: Date.now()
                }
                : null;
            await switchTab('tasks');
        }

        async function handleSystemOpenFile(fileId) {
            if (!fileId) return;
            await navigateToTarget({ id: String(fileId), isDirectory: false });
        }

        // Selection
        const visibleIdsList = computed(() => [
            ...folders.value.map(f => f.id),
            ...regularFiles.value.map(f => f.id)
        ]);

        const allVisibleSelected = computed(() => {
            const ids = visibleIdsList.value;
            if (ids.length === 0) return false;
            const selectedSet = new Set(selectedIds.value);
            return ids.every(id => selectedSet.has(id));
        });

        function toggleSelection(id) {
            const index = selectedIds.value.indexOf(id);
            if (index > -1) {
                selectedIds.value.splice(index, 1);
            } else {
                selectedIds.value.push(id);
            }
        }

        function toggleSelectAllVisible() {
            if (allVisibleSelected.value) {
                selectedIds.value = [];
            } else {
                selectedIds.value = [...visibleIdsList.value];
            }
        }

        // Actions
        async function handleCreateFolder() {
            const trimmed = newFolderName.value.trim();
            if (!trimmed) return;
            try {
                await createNewFolder(trimmed);
                showNewFolderModal.value = false;
                newFolderName.value = '';
                showToast('Folder created', 'success');
            } catch (e) {
                showToast('Failed to create folder: ' + e.message);
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
                showToast(`Uploaded ${selectedFiles.length} ${selectedFiles.length === 1 ? 'file' : 'files'}`, 'success');
            } catch (e) {
                showToast('Upload failed: ' + e.message);
            } finally {
                event.target.value = '';
            }
        }

        function isFileDragEvent(event) {
            const types = event?.dataTransfer?.types;
            return Boolean(types && Array.from(types).includes('Files'));
        }

        function handleDragOver(event) {
            if (!isFileDragEvent(event)) return;
            event.preventDefault();
            isDraggingOver.value = true;
        }

        function handleDragLeave(event) {
            if (!isDraggingOver.value) return;
            if (!event.currentTarget.contains(event.relatedTarget)) {
                isDraggingOver.value = false;
            }
        }

        async function handleDrop(event) {
            isDraggingOver.value = false;
            if (!isFileDragEvent(event)) return;
            event.preventDefault();
            const droppedFiles = event.dataTransfer?.files;
            if (!droppedFiles || droppedFiles.length === 0) return;
            try {
                await uploadFiles(droppedFiles);
                showToast(`Uploaded ${droppedFiles.length} ${droppedFiles.length === 1 ? 'file' : 'files'}`, 'success');
            } catch (e) {
                showToast('Upload failed: ' + e.message);
            }
        }

        function handleDeleteSelected() {
            if (selectedIds.value.length === 0) return;
            showDeleteModal.value = true;
        }

        async function confirmDeleteSelected() {
            const count = selectedIds.value.length;
            showDeleteModal.value = false;
            if (count === 0) return;
            try {
                await deleteSelectedItems(selectedIds.value);
                selectedIds.value = [];
                showToast(`Deleted ${count} ${count === 1 ? 'item' : 'items'}`, 'success');
            } catch (e) {
                showToast('Delete failed: ' + e.message);
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
                showToast('Moved successfully', 'success');
            } catch (e) {
                showToast('Move failed: ' + e.message);
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
                showToast('Renamed successfully', 'success');
            } catch (e) {
                showToast('Rename failed: ' + e.message);
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
            try {
                await login(email, password);
                const loggedIn = await resumeSession();
                if (loggedIn) {
                    await syncFromUrl(true);
                    updateUrl(true);
                }
            } catch (e) {
                showToast(e.message);
            }
        }

        async function submitOAuthDecision(decision) {
            const req = pendingOAuthRequest.value;
            if (!req || !req.isValid || isSubmittingOAuth.value) return;
            const token = getToken();
            if (!token) {
                isLoggedIn.value = false;
                showToast('Please sign in to authorize this application.', 'error');
                return;
            }
            isSubmittingOAuth.value = true;
            let keepLockedForNavigation = false;
            try {
                const resp = await fetch(req.bridgePathWithQuery, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'x-access-token': token,
                        'Accept': 'application/json'
                    },
                    body: JSON.stringify({ decision })
                });
                if (resp.status === 401) {
                    await logout({ reload: false });
                    isLoggedIn.value = false;
                    showToast('Your session expired. Please sign in again.', 'error');
                    return;
                }
                const data = await resp.json().catch(() => null);
                if (!resp.ok || !data?.redirect_url) {
                    const msg = data?.error_description || data?.error || `Authorization failed (HTTP ${resp.status})`;
                    if (resp.status === 400) {
                        pendingOAuthRequest.value = { ...req, isValid: false, error: msg };
                    } else {
                        showToast(msg, 'error');
                    }
                    return;
                }
                if (req.redirectTarget?.isCustomScheme) {
                    oauthCompletedOutcome.value = decision === 'approve' ? 'approved' : 'denied';
                } else {
                    keepLockedForNavigation = true;
                }
                window.location.assign(data.redirect_url);
            } catch (e) {
                showToast('Authorization failed: ' + e.message, 'error');
            } finally {
                if (!keepLockedForNavigation) {
                    isSubmittingOAuth.value = false;
                }
            }
        }

        const handleOAuthApprove = () => submitOAuthDecision('approve');
        const handleOAuthDeny = () => submitOAuthDecision('deny');

        async function dismissOAuthConsent() {
            isSubmittingOAuth.value = false;
            oauthCompletedOutcome.value = null;
            await clearOAuthRoute();
        }

        function handleLogout() {
            logout();
        }

        const { processingStatuses } = useProcessingStatus({
            files,
            isLoggedIn: computed(() => isLoggedIn.value && !pendingOAuthRequest.value),
            activeTab,
            view
        });

        const clearDragState = () => {
            isDraggingOver.value = false;
        };

        function openSearchWithQuery(initialQuery = '') {
            searchInitialQuery.value = typeof initialQuery === 'string' ? initialQuery : '';
            showSearchModal.value = true;
        }

        function closeSearchModal() {
            showSearchModal.value = false;
            searchInitialQuery.value = '';
        }

        const handleGlobalKeydown = (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
                if (!isLoggedIn.value || pendingOAuthRequest.value) return;
                e.preventDefault();
                if (showSearchModal.value) {
                    closeSearchModal();
                } else {
                    openSearchWithQuery('');
                }
                return;
            }
            if (e.key === 'Escape') {
                isDraggingOver.value = false;
                if (showDeleteModal.value) {
                    showDeleteModal.value = false;
                    e.preventDefault();
                } else if (showNewFolderModal.value) {
                    showNewFolderModal.value = false;
                    e.preventDefault();
                }
            }
        };

        const handleFileSyncEvent = () => {
            if (!isLoggedIn.value || pendingOAuthRequest.value) return;
            loadDirectory(currentDirectoryId.value || '0');
        };

        onMounted(async () => {
            const loggedIn = await resumeSession();
            await syncFromUrl(true);
            if (loggedIn) {
                updateUrl(true);
            }

            window.addEventListener('supernote:file-sync', handleFileSyncEvent);
            window.addEventListener('dragend', clearDragState);
            window.addEventListener('drop', clearDragState);
            window.addEventListener('keydown', handleGlobalKeydown);
        });

        onUnmounted(() => {
            window.removeEventListener('supernote:file-sync', handleFileSyncEvent);
            window.removeEventListener('dragend', clearDragState);
            window.removeEventListener('drop', clearDragState);
            window.removeEventListener('keydown', handleGlobalKeydown);
        });

        return {
            isLoggedIn,
            pendingOAuthRequest,
            isSubmittingOAuth,
            oauthCompletedOutcome,
            handleOAuthApprove,
            handleOAuthDeny,
            dismissOAuthConsent,
            handleLogin,
            handleLogout,
            activeTab,
            showSearchModal,
            searchInitialQuery,
            openSearchWithQuery,
            closeSearchModal,
            searchShortcutLabel,
            displayMode,
            sortBy,
            sortOrder,
            handleSortByChange,
            toggleSortOrder,
            isDraggingOver,
            handleDragOver,
            handleDragLeave,
            handleDrop,
            focusedTaskRequest,
            view,
            files,
            allFolders,
            allRegularFiles,
            folders,
            regularFiles,
            totalItemCount,
            visibleItemCount,
            hasMoreItems,
            loadMoreItems,
            currentDirectoryId,
            isLoading,
            error,
            breadcrumbs,
            switchTab,
            openSystemPanel,
            closeSystemPanel,
            closeViewer,
            handleViewerPageChange,
            openItem,
            navigateFolder,
            navigateTo,
            selectedFile,
            selectedPageIndex,
            selectedPageJumpSeq,
            showSystemPanel,
            showNewFolderModal,
            newFolderName,
            newFolderInput,
            showMoveModal,
            showRenameModal,
            showDeleteModal,
            itemToRename,
            selectedIds,
            allVisibleSelected,
            fileInput,
            toggleSelection,
            toggleSelectAllVisible,
            handleCreateFolder,
            triggerUpload,
            handleFileUpload,
            handleDeleteSelected,
            confirmDeleteSelected,
            handleMoveSelected,
            onConfirmMove,
            triggerRename,
            onConfirmRename,
            processingStatuses,
            toasts,
            showToast,
            dismissToast,
            handleSearchSelectFile,
            handleSearchSelectTask,
            handleSystemOpenFile
        };
    }
}).mount('#app');
