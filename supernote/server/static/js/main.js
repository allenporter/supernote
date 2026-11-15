import { createApp, ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue';
import { useFileSystem } from './composables/useFileSystem.js';
import { useProcessingStatus } from './composables/useProcessingStatus.js';
import { useToast } from './composables/useToast.js';
import { setToken, getToken, login, logout, fetchPathInfo, connectSocket } from './api/client.js';
import { normalizeEpochMs } from './utils/format.js';
import {
    parseOAuthBridgeReturnTo,
    isAllowedOAuthRedirectUri,
    buildOAuthDeniedRedirectUrl
} from './utils/oauth.js';
import SearchModal from './components/SearchModal.js';
import TaskPanel from './components/TaskPanel.js';
import FileCard from './components/FileCard.js';
import LoginCard from './components/LoginCard.js';
import OAuthConsentCard from './components/OAuthConsentCard.js';
import FileViewer from './components/FileViewer.js';
import SystemPanel from './components/SystemPanel.js';
import MoveModal from './components/MoveModal.js';
import RenameModal from './components/RenameModal.js';

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

function parsePageParam(params) {
    if (!params || !params.has('page')) return null;
    const rawPage = Number.parseInt(params.get('page'), 10);
    if (Number.isNaN(rawPage) || rawPage < 1) return 0;
    return rawPage - 1;
}

export function parseUrlHash(hashString) {
    const raw = hashString !== undefined ? hashString : (window.location.hash || window.location.search || '');
    const clean = raw.replace(/^[#?]\/?/, '').trim();

    if (!clean) {
        return { tab: 'files', view: 'grid', dirId: '0', showSystem: false };
    }

    let pathPart = clean;
    let params = null;
    const qIdx = clean.indexOf('?');
    if (qIdx !== -1) {
        pathPart = clean.slice(0, qIdx);
        params = new URLSearchParams(clean.slice(qIdx + 1));
    } else if (clean.includes('=') && !clean.includes('/')) {
        pathPart = '';
        params = new URLSearchParams(clean);
    }

    const pageIndex = parsePageParam(params);

    if (params) {
        if (params.get('tab') === 'system' || params.get('view') === 'system') {
            return { tab: 'system', view: 'grid', dirId: params.get('dir') || '0', showSystem: true };
        }
        if (params.get('tab') === 'tasks' || params.get('view') === 'tasks') {
            return { tab: 'tasks', view: 'grid', dirId: '0', showSystem: false };
        }
        if (params.has('file')) {
            return {
                tab: 'files',
                view: 'viewer',
                fileId: params.get('file'),
                dirId: params.get('dir') || null,
                pageIndex,
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

    const parts = pathPart.split('/').filter(Boolean);

    if (parts[0] === 'system') {
        return { tab: 'system', view: 'grid', dirId: '0', showSystem: true };
    }

    if (parts[0] === 'tasks') {
        return { tab: 'tasks', view: 'grid', dirId: '0', showSystem: false };
    }

    if (parts[0] === 'file' && parts[1]) {
        return { tab: 'files', view: 'viewer', fileId: parts[1], pageIndex, showSystem: false };
    }

    if ((parts[0] === 'files' || parts[0] === 'explorer') && parts[1] === 'file' && parts[2]) {
        return { tab: 'files', view: 'viewer', fileId: parts[2], pageIndex, showSystem: false };
    }

    if ((parts[0] === 'files' || parts[0] === 'explorer') && parts[2] === 'file' && parts[3]) {
        return { tab: 'files', view: 'viewer', dirId: parts[1], fileId: parts[3], pageIndex, showSystem: false };
    }

    if ((parts[0] === 'files' || parts[0] === 'explorer' || parts[0] === 'folder') && parts[1]) {
        return { tab: 'files', view: 'grid', dirId: parts[1], showSystem: false };
    }

    if (parts[0] === 'files' || parts[0] === 'explorer') {
        return { tab: 'files', view: 'grid', dirId: '0', showSystem: false };
    }

    return { tab: 'files', view: 'grid', dirId: '0', showSystem: false };
}

export function buildUrlHash(tab, dirId, viewState, fileObj, showSystem = false, pageIndex = null) {
    if (showSystem || tab === 'system') {
        return '#/system';
    }
    if (tab === 'tasks') {
        return '#/tasks';
    }
    if (viewState === 'viewer' && fileObj && fileObj.id) {
        if (typeof pageIndex === 'number' && pageIndex > 0) {
            return `#/file/${fileObj.id}?page=${pageIndex + 1}`;
        }
        return `#/file/${fileObj.id}`;
    }
    if (dirId && String(dirId) !== '0') {
        return `#/files/${dirId}`;
    }
    return '#/files';
}

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
        const loginError = ref(null);
        const showSystemPanel = ref(false);
        const pendingOAuthRequest = ref(null);
        const isSubmittingOAuth = ref(false);
        const oauthCompletedOutcome = ref(null);

        // Navigation & Display State
        const activeTab = ref('files'); // 'files' | 'tasks'
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

        const view = ref('grid');
        const selectedFile = ref(null);
        const selectedPageIndex = ref(null);
        const selectedPageJumpSeq = ref(0);
        const breadcrumbs = ref([{ id: "0", name: "Cloud" }]);

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

        // URL Routing Synchronization
        const ROUTING_QUERY_KEYS = ['dir', 'folder', 'file', 'tab', 'view', 'page'];
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
            if (urlSyncDepth > 0 || pendingOAuthRequest.value) return;
            const targetHash = buildUrlHash(
                activeTab.value,
                currentDirectoryId.value,
                view.value,
                selectedFile.value,
                showSystemPanel.value,
                selectedPageIndex.value
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
            view.value = 'grid';
            selectedFile.value = null;
            selectedPageIndex.value = null;
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

        async function restoreViewerState(targetFileId, seq, fallbackItem = null, onViewerReady = null) {
            const hasMatchingLoadedDir =
                loadedDirectoryId.value === String(currentDirectoryId.value) &&
                (fallbackItem?.parentId === undefined || String(fallbackItem.parentId) === String(currentDirectoryId.value));
            const existingFile = hasMatchingLoadedDir
                ? files.value.find(f => !f.isDirectory && String(f.id) === targetFileId)
                : null;
            if (existingFile) {
                selectedFile.value = existingFile;
                view.value = 'viewer';
                if (onViewerReady) await onViewerReady();
                const currentLastCrumbId = String(breadcrumbs.value[breadcrumbs.value.length - 1]?.id || '0');
                if (currentLastCrumbId !== String(currentDirectoryId.value)) {
                    await syncBreadcrumbsForDirectory(currentDirectoryId.value, seq);
                }
                return;
            }

            const fallbackName = fallbackItem?.name || `File ${targetFileId}`;
            const fallbackExt = fallbackItem?.extension || (
                fallbackItem?.name && fallbackName.includes('.')
                    ? fallbackName.split('.').pop().toLowerCase()
                    : ''
            );

            try {
                const info = await fetchPathInfo(targetFileId);
                if (seq !== activeSyncSeq) return;
                const allCrumbs = buildCrumbsFromPathInfo(info);
                if (allCrumbs.length <= 1) {
                    selectedFile.value = {
                        ...fallbackItem,
                        id: targetFileId,
                        name: fallbackName,
                        extension: fallbackExt
                    };
                    view.value = 'viewer';
                    if (onViewerReady) await onViewerReady();
                    return;
                }

                const fileCrumb = allCrumbs[allCrumbs.length - 1];
                const folderCrumbs = allCrumbs.slice(0, -1);
                const parentDirId = String(folderCrumbs[folderCrumbs.length - 1].id);
                const ext = fileCrumb.name.includes('.')
                    ? fileCrumb.name.split('.').pop().toLowerCase()
                    : fallbackExt;

                breadcrumbs.value = folderCrumbs;
                currentDirectoryId.value = parentDirId;
                selectedFile.value = {
                    ...fallbackItem,
                    id: targetFileId,
                    name: fileCrumb.name,
                    extension: ext
                };
                view.value = 'viewer';
                if (onViewerReady) await onViewerReady();

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
                    ...fallbackItem,
                    id: targetFileId,
                    name: fallbackName,
                    extension: fallbackExt
                };
                view.value = 'viewer';
                if (onViewerReady) await onViewerReady();
            }
        }

        async function restoreDirectoryState(targetDirId, isInitial, seq) {
            view.value = 'grid';
            selectedFile.value = null;
            selectedPageIndex.value = null;
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
            const rawHash = window.location.hash || '';
            const oauthReq = parseOAuthBridgeReturnTo(rawHash, window.location.origin);
            if (oauthReq) {
                lastSyncedHash = rawHash;
                pendingOAuthRequest.value = oauthReq;
                isSubmittingOAuth.value = false;
                oauthCompletedOutcome.value = null;
                showSystemPanel.value = false;
                showSearchModal.value = false;
                return;
            }
            pendingOAuthRequest.value = null;
            isSubmittingOAuth.value = false;
            oauthCompletedOutcome.value = null;
            if (!isLoggedIn.value) {
                return;
            }

            const currentHash = rawHash || window.location.search || '';
            if (!isInitial && currentHash === lastSyncedHash) {
                return;
            }
            lastSyncedHash = currentHash;
            if (!isInitial && inAppHistoryDepth > 0) {
                inAppHistoryDepth--;
            }

            const isStaleLoginHash = /^#\/?login(?:\?|$)/i.test(rawHash);
            if (isStaleLoginHash) {
                lastSyncedHash = '#/files';
                window.history.replaceState(null, '', '#/files');
            }
            const seq = ++activeSyncSeq;
            const parsed = parseUrlHash(isStaleLoginHash ? '#/files' : currentHash);
            urlSyncDepth++;
            try {
                if (parsed.tab === 'system' || parsed.showSystem) {
                    await restoreSystemView(isInitial, seq);
                    return;
                }
                showSystemPanel.value = false;
                systemOpenedFromHistory = false;

                if (parsed.tab === 'tasks') {
                    activeTab.value = 'tasks';
                    view.value = 'grid';
                    selectedFile.value = null;
                    selectedPageIndex.value = null;
                    viewerOpenedFromHistory = false;
                    return;
                }

                activeTab.value = 'files';
                if (parsed.view === 'viewer' && parsed.fileId) {
                    selectedPageIndex.value = typeof parsed.pageIndex === 'number' ? parsed.pageIndex : null;
                    if (typeof parsed.pageIndex === 'number') {
                        selectedPageJumpSeq.value++;
                    }
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

        watch([activeTab, currentDirectoryId, view, () => selectedFile.value?.id, selectedPageIndex, showSystemPanel], () => {
            updateUrl();
        });

        // Methods
        async function switchTab(tab) {
            isDraggingOver.value = false;
            showSystemPanel.value = false;
            systemOpenedFromHistory = false;
            activeTab.value = tab;
            if (tab === 'files') {
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
            if (activeTab.value === 'files' && view.value === 'grid') {
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
            selectedPageIndex.value = null;
            await nextTick();
            urlSyncDepth--;
            updateUrl(true);
            await restoreDirectoryState(String(currentDirectoryId.value || '0'), false, ++activeSyncSeq);
        }

        async function handleViewerPageChange(pageIdx) {
            if (view.value !== 'viewer' || typeof pageIdx !== 'number' || Number.isNaN(pageIdx) || pageIdx < 0) {
                return;
            }
            if (selectedPageIndex.value === pageIdx) return;
            urlSyncDepth++;
            try {
                selectedPageIndex.value = pageIdx;
                await nextTick();
            } finally {
                urlSyncDepth--;
            }
            updateUrl(true);
        }

        async function openItem(item) {
            isDraggingOver.value = false;
            if (item.isDirectory) {
                activeTab.value = 'files';
                view.value = 'grid';
                selectedFile.value = null;
                selectedPageIndex.value = null;
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
                const targetPage = typeof item.pageIndex === 'number' ? item.pageIndex : null;
                if (
                    view.value === 'viewer' &&
                    String(selectedFile.value?.id) === String(item.id)
                ) {
                    selectedPageIndex.value = targetPage ?? 0;
                    selectedPageJumpSeq.value++;
                    return;
                }
                viewerOpenedFromHistory = true;
                selectedPageIndex.value = targetPage;
                if (targetPage !== null) {
                    selectedPageJumpSeq.value++;
                }
                selectedFile.value = item;
                view.value = 'viewer';
            }
        }

        async function navigateFolder(folder) {
            isDraggingOver.value = false;
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
            isDraggingOver.value = false;
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

        async function handleSearchSelectFile(item) {
            if (!item) return;
            const replaceModalHistory = systemOpenedFromHistory && inAppHistoryDepth > 0;
            const wasSystemUrl = window.location.hash.startsWith('#/system');
            isDraggingOver.value = false;
            showSearchModal.value = false;

            if (item.isDirectory) {
                urlSyncDepth++;
                try {
                    showSystemPanel.value = false;
                    systemOpenedFromHistory = false;
                    activeTab.value = 'files';
                    view.value = 'grid';
                    selectedFile.value = null;
                    selectedPageIndex.value = null;
                    viewerOpenedFromHistory = false;
                    currentDirectoryId.value = String(item.id);
                    selectedIds.value = [];
                    await nextTick();
                } finally {
                    urlSyncDepth--;
                }
                updateUrl(replaceModalHistory);
                const seq = ++activeSyncSeq;
                await Promise.all([
                    loadDirectory(item.id),
                    syncBreadcrumbsForDirectory(item.id, seq)
                ]);
                return;
            }

            const targetFileId = String(item.id);
            const targetPage = typeof item.pageIndex === 'number' ? item.pageIndex : null;

            if (view.value === 'viewer' && String(selectedFile.value?.id) === targetFileId) {
                urlSyncDepth++;
                try {
                    showSystemPanel.value = false;
                    systemOpenedFromHistory = false;
                    activeTab.value = 'files';
                    selectedPageIndex.value = targetPage ?? 0;
                    selectedPageJumpSeq.value++;
                    await nextTick();
                } finally {
                    urlSyncDepth--;
                }
                updateUrl(wasSystemUrl ? replaceModalHistory : true);
                const currentLastCrumbId = String(breadcrumbs.value[breadcrumbs.value.length - 1]?.id || '0');
                if (currentLastCrumbId !== String(currentDirectoryId.value)) {
                    await syncBreadcrumbsForDirectory(currentDirectoryId.value, ++activeSyncSeq);
                }
                return;
            }

            const seq = ++activeSyncSeq;
            let urlReleased = false;
            const releaseAndSyncUrl = async () => {
                if (urlReleased) return;
                urlReleased = true;
                await nextTick();
                urlSyncDepth--;
                if (seq === activeSyncSeq) {
                    updateUrl(replaceModalHistory);
                }
            };

            urlSyncDepth++;
            try {
                showSystemPanel.value = false;
                systemOpenedFromHistory = false;
                activeTab.value = 'files';
                viewerOpenedFromHistory = true;
                selectedPageIndex.value = targetPage;
                if (targetPage !== null) {
                    selectedPageJumpSeq.value++;
                }
                await restoreViewerState(targetFileId, seq, item, releaseAndSyncUrl);
            } finally {
                if (!urlReleased) {
                    await nextTick();
                    urlSyncDepth--;
                }
            }
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
            await handleSearchSelectFile({ id: String(fileId), isDirectory: false });
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
                showToast(`Uploaded ${selectedFiles.length} ${selectedFiles.length === 1 ? 'file' : 'files'}`, 'success');
            } catch (e) {
                showToast("Upload failed: " + e.message);
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
                showToast("Upload failed: " + e.message);
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
                showToast('Moved successfully', 'success');
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
                showToast('Renamed successfully', 'success');
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

        async function handleOAuthApprove() {
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
                        'x-access-token': token,
                        'Accept': 'application/json'
                    }
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
                    showToast(msg, 'error');
                    return;
                }
                if (!isAllowedOAuthRedirectUri(req.clientId, data.redirect_url)) {
                    showToast('Blocked unsafe redirect URI returned by server.', 'error');
                    return;
                }
                if (req.redirectTarget?.isCustomScheme) {
                    oauthCompletedOutcome.value = 'approved';
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

        function handleOAuthDeny() {
            const req = pendingOAuthRequest.value;
            if (!req || !req.isValid || isSubmittingOAuth.value) return;
            const denyUrl = buildOAuthDeniedRedirectUrl(req.redirectUri, req.state);
            if (!denyUrl || !isAllowedOAuthRedirectUri(req.clientId, denyUrl)) {
                showToast('Blocked redirect to unverified callback URI.', 'error');
                return;
            }
            if (req.redirectTarget?.isCustomScheme) {
                oauthCompletedOutcome.value = 'denied';
            } else {
                isSubmittingOAuth.value = true;
            }
            window.location.assign(denyUrl);
        }

        async function dismissOAuthConsent() {
            pendingOAuthRequest.value = null;
            isSubmittingOAuth.value = false;
            oauthCompletedOutcome.value = null;
            lastSyncedHash = '#/files';
            window.history.replaceState(null, '', '#/files');
            if (isLoggedIn.value) {
                await restoreDirectoryState('0', true, ++activeSyncSeq);
            }
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

        const handlePopStateOrHash = () => syncFromUrl();
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

            window.addEventListener('popstate', handlePopStateOrHash);
            window.addEventListener('hashchange', handlePopStateOrHash);
            window.addEventListener('supernote:file-sync', handleFileSyncEvent);
            window.addEventListener('dragend', clearDragState);
            window.addEventListener('drop', clearDragState);
            window.addEventListener('keydown', handleGlobalKeydown);
        });

        onUnmounted(() => {
            window.removeEventListener('popstate', handlePopStateOrHash);
            window.removeEventListener('hashchange', handlePopStateOrHash);
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
