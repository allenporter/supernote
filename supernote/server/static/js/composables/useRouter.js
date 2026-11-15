/**
 * Client-side hash router and Host UI view synchronization composable.
 *
 * Pure URL helpers (`parseUrlHash`, `buildUrlHash`, `buildCrumbsFromPathInfo`,
 * `formatCrumbName`) are exported at module top level with zero DOM/Vue side
 * effects so they can be imported directly in unit tests and plugin helpers.
 */

import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue';
import { fetchPathInfo } from '../api/client.js';
import { parseOAuthBridgeReturnTo } from '../utils/oauth.js';

const SYSTEM_ROOT_UPPER = new Set(['EXPORT', 'INBOX', 'SCREENSHOT']);
const ROUTING_QUERY_KEYS = ['dir', 'folder', 'file', 'tab', 'view', 'page'];

export function formatCrumbName(name, index) {
    if (index === 0 && SYSTEM_ROOT_UPPER.has(name)) {
        return name.charAt(0) + name.slice(1).toLowerCase();
    }
    return name;
}

/**
 * @param {{ path?: string, idPath?: string } | null | undefined} info
 * @returns {BreadcrumbItem[]}
 */
export function buildCrumbsFromPathInfo(info) {
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

/**
 * @param {URLSearchParams | null} params
 * @returns {number | null}
 */
function parsePageParam(params) {
    if (!params || !params.has('page')) return null;
    const rawPage = Number.parseInt(params.get('page') || '', 10);
    if (Number.isNaN(rawPage) || rawPage < 1) return 0;
    return rawPage - 1;
}

export function parseUrlHash(hashString) {
    const raw = hashString !== undefined
        ? hashString
        : (window.location.hash || window.location.search || '');
    const clean = raw.replace(/^[#?]\/?/, '').trim();

    if (!clean) {
        return { tab: 'files', view: 'grid', dirId: '0', showSystem: false };
    }

    let pathPart = clean;
    /** @type {URLSearchParams | null} */
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

function hasRoutingQueryParams(searchStr) {
    if (!searchStr) return false;
    const params = new URLSearchParams(searchStr);
    return ROUTING_QUERY_KEYS.some(key => params.has(key));
}

/**
 * @param {Object} options
 * @param {import('vue').Ref<boolean>} options.isLoggedIn
 * @param {import('vue').Ref<FileItem[]>} options.files
 * @param {import('vue').Ref<string>} options.currentDirectoryId
 * @param {import('vue').Ref<string | null>} options.loadedDirectoryId
 * @param {(directoryId?: string | number) => Promise<void>} options.loadDirectory
 * @param {import('vue').Ref<Array<string | number>>} options.selectedIds
 * @param {(() => void) | null} [options.onBeforeNavigate=null]
 * @param {(() => void) | null} [options.onOAuthRouteEnter=null]
 * @param {(() => void) | null} [options.onOAuthRouteClear=null]
 */
export function useRouter({
    isLoggedIn,
    files,
    currentDirectoryId,
    loadedDirectoryId,
    loadDirectory,
    selectedIds,
    onBeforeNavigate = null,
    onOAuthRouteEnter = null,
    onOAuthRouteClear = null
}) {
    const activeTab = ref('files'); // 'files' | 'tasks'
    const view = ref('grid'); // 'grid' | 'viewer'
    const selectedFile = ref(null);
    const selectedPageIndex = ref(null);
    const selectedPageJumpSeq = ref(0);
    const breadcrumbs = ref([{ id: '0', name: 'Cloud' }]);
    const showSystemPanel = ref(false);
    const pendingOAuthRequest = ref(null);

    let urlSyncDepth = 0;
    let activeSyncSeq = 0;
    let lastSyncedHash = '';
    let inAppHistoryDepth = 0;
    let viewerOpenedFromHistory = false;
    let systemOpenedFromHistory = false;

    function notifyBeforeNavigate() {
        if (onBeforeNavigate) {
            onBeforeNavigate();
        }
    }

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
            console.error('Failed to resolve directory breadcrumbs:', e);
            return true;
        }
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

    /**
     * @param {string} targetFileId
     * @param {number} seq
     * @param {Record<string, any> | null} [fallbackItem=null]
     * @param {(() => void | Promise<void>) | null} [onViewerReady=null]
     */
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
                ? (fallbackName.split('.').pop() || '').toLowerCase()
                : ''
        );

        try {
            const info = await fetchPathInfo(targetFileId);
            if (seq !== activeSyncSeq) return;
            const allCrumbs = buildCrumbsFromPathInfo(info);
            if (allCrumbs.length <= 1) {
                selectedFile.value = {
                    ...(fallbackItem || {}),
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
                ? (fileCrumb.name.split('.').pop() || '').toLowerCase()
                : fallbackExt;

            breadcrumbs.value = folderCrumbs;
            currentDirectoryId.value = parentDirId;
            selectedFile.value = {
                ...(fallbackItem || {}),
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
            console.error('Failed to resolve file path info:', e);
            selectedFile.value = {
                ...(fallbackItem || {}),
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
            showSystemPanel.value = false;
            if (onOAuthRouteEnter) onOAuthRouteEnter();
            return;
        }
        pendingOAuthRequest.value = null;
        if (onOAuthRouteClear) onOAuthRouteClear();
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

    async function clearOAuthRoute() {
        pendingOAuthRequest.value = null;
        lastSyncedHash = '#/files';
        window.history.replaceState(null, '', '#/files');
        if (isLoggedIn.value) {
            await restoreDirectoryState('0', true, ++activeSyncSeq);
        }
    }

    watch(
        [activeTab, currentDirectoryId, view, () => selectedFile.value?.id, selectedPageIndex, showSystemPanel],
        () => {
            if (!isLoggedIn.value || pendingOAuthRequest.value) return;
            updateUrl();
        }
    );

    async function switchTab(tab) {
        notifyBeforeNavigate();
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
        notifyBeforeNavigate();
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
        notifyBeforeNavigate();
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
        notifyBeforeNavigate();
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

    async function navigateToTarget(item) {
        if (!item) return;
        const replaceModalHistory = systemOpenedFromHistory && inAppHistoryDepth > 0;
        const wasSystemUrl = window.location.hash.startsWith('#/system');
        notifyBeforeNavigate();

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

    const handlePopStateOrHash = () => syncFromUrl();

    onMounted(() => {
        window.addEventListener('popstate', handlePopStateOrHash);
        window.addEventListener('hashchange', handlePopStateOrHash);
    });

    onUnmounted(() => {
        window.removeEventListener('popstate', handlePopStateOrHash);
        window.removeEventListener('hashchange', handlePopStateOrHash);
    });

    return {
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
    };
}
