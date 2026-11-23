/**
 * Client-side hash router and Host UI view synchronization composable.
 *
 * Canonical routes:
 * - `#/files` and `#/files/<dirId>`
 * - `#/file/<fileId>` and `#/file/<fileId>?page=<1-based>`
 * - `#/recycle`
 * - `#/tasks`
 * - `#/settings`
 * - `#/system`
 * - `#/login?return_to=...` (OAuth 2.1 `/login-bridge` consent handoff)
 *
 * Pure URL helpers (`parseUrlHash`, `buildUrlHash`, `buildCrumbsFromPathInfo`,
 * `formatCrumbName`) are exported at module top level with zero DOM/Vue side
 * effects so they can be imported directly in unit tests.
 */

import { onMounted, onUnmounted, ref } from 'vue';
import { fetchPathInfo } from '../api/client.js';
import { getFileExtension } from '../utils/format.js';
import { parseOAuthBridgeReturnTo } from '../utils/oauth.js';

const SYSTEM_ROOT_UPPER = new Set(['EXPORT', 'INBOX', 'SCREENSHOT']);

/**
 * @param {string} name
 * @param {number} index
 * @returns {string}
 */
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
    if (info?.path && info.idPath) {
        const names = info.path.split('/').filter(Boolean);
        const ids = info.idPath.split('/').filter(Boolean);
        const len = Math.min(names.length, ids.length);
        for (let i = 0; i < len; i++) {
            crumbs.push({
                id: String(ids[i]),
                name: formatCrumbName(names[i], i),
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
    if (!params?.has('page')) return null;
    const rawPage = Number.parseInt(params.get('page') || '', 10);
    if (Number.isNaN(rawPage) || rawPage < 1) return 0;
    return rawPage - 1;
}

/**
 * @param {string} [hashString]
 */
export function parseUrlHash(hashString) {
    const raw =
        hashString !== undefined
            ? hashString
            : typeof window !== 'undefined'
              ? window.location.hash || ''
              : '';
    const clean = raw.replace(/^#\/?/, '').trim();

    if (!clean) {
        return { tab: 'files', view: 'grid', dirId: '0', showSystem: false };
    }

    const qIdx = clean.indexOf('?');
    const pathPart = qIdx !== -1 ? clean.slice(0, qIdx) : clean;
    const params = qIdx !== -1 ? new URLSearchParams(clean.slice(qIdx + 1)) : null;
    const parts = pathPart.split('/').filter(Boolean);

    if (parts[0] === 'system') {
        return { tab: 'system', view: 'grid', dirId: '0', showSystem: true };
    }
    if (parts[0] === 'tasks') {
        return { tab: 'tasks', view: 'grid', dirId: '0', showSystem: false };
    }
    if (parts[0] === 'recycle') {
        return { tab: 'files', view: 'recycle', dirId: '0', showSystem: false };
    }
    if (parts[0] === 'settings') {
        return { tab: 'settings', view: 'grid', dirId: '0', showSystem: false };
    }
    if (parts[0] === 'file' && parts[1]) {
        return {
            tab: 'files',
            view: 'viewer',
            fileId: parts[1],
            pageIndex: parsePageParam(params),
            showSystem: false,
        };
    }
    if (parts[0] === 'files' && parts[1]) {
        return { tab: 'files', view: 'grid', dirId: parts[1], showSystem: false };
    }
    return { tab: 'files', view: 'grid', dirId: '0', showSystem: false };
}

/**
 * @param {string} tab
 * @param {string | number | null} dirId
 * @param {string} viewState
 * @param {{ id?: string | number } | null} fileObj
 * @param {boolean} [showSystem=false]
 * @param {number | null} [pageIndex=null]
 * @returns {string}
 */
export function buildUrlHash(tab, dirId, viewState, fileObj, showSystem = false, pageIndex = null) {
    if (showSystem || tab === 'system') {
        return '#/system';
    }
    if (tab === 'tasks') {
        return '#/tasks';
    }
    if (tab === 'settings') {
        return '#/settings';
    }
    if (viewState === 'recycle') {
        return '#/recycle';
    }
    if (viewState === 'viewer' && fileObj?.id) {
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

/**
 * @param {Object} options
 * @param {import('vue').Ref<boolean>} options.isLoggedIn
 * @param {import('vue').Ref<FileItem[]>} options.files
 * @param {import('vue').Ref<string>} options.currentDirectoryId
 * @param {import('vue').Ref<string | null>} options.loadedDirectoryId
 * @param {(directoryId?: string | number) => Promise<void>} options.loadDirectory
 * @param {import('vue').Ref<string[]>} options.selectedIds
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
    onOAuthRouteEnter = null,
    onOAuthRouteClear = null,
}) {
    const activeTab = ref('files'); // 'files' | 'tasks' | 'settings'
    const view = ref('grid'); // 'grid' | 'viewer'
    /** @type {import('vue').Ref<FileItem | null>} */
    const selectedFile = ref(null);
    /** @type {import('vue').Ref<number | null>} */
    const selectedPageIndex = ref(null);
    const selectedPageJumpSeq = ref(0);
    /** @type {import('vue').Ref<BreadcrumbItem[]>} */
    const breadcrumbs = ref([{ id: '0', name: 'Cloud' }]);
    const showSystemPanel = ref(false);
    /** @type {import('vue').Ref<OAuthBridgeRequest | null>} */
    const pendingOAuthRequest = ref(null);

    let activeSyncSeq = 0;
    let lastSyncedHash = '';
    let inAppHistoryDepth = 0;
    let viewerOpenedFromHistory = false;
    let recycleOpenedFromHistory = false;
    let systemOpenedFromHistory = false;

    function resetViewerSelection() {
        view.value = 'grid';
        selectedFile.value = null;
        selectedPageIndex.value = null;
    }

    function resetSessionRoutes() {
        activeSyncSeq++;
        lastSyncedHash = '';
        inAppHistoryDepth = 0;
        viewerOpenedFromHistory = false;
        recycleOpenedFromHistory = false;
        systemOpenedFromHistory = false;
        activeTab.value = 'files';
        resetViewerSelection();
        breadcrumbs.value = [{ id: '0', name: 'Cloud' }];
        showSystemPanel.value = false;
    }

    /**
     * @param {string | number} dirId
     * @param {number} [seq]
     * @returns {Promise<boolean>}
     */
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
        if (!isLoggedIn.value || pendingOAuthRequest.value) return;
        const targetHash = buildUrlHash(
            activeTab.value,
            currentDirectoryId.value,
            view.value,
            selectedFile.value,
            showSystemPanel.value,
            selectedPageIndex.value,
        );
        lastSyncedHash = targetHash;
        if (window.location.hash !== targetHash) {
            if (replace) {
                window.history.replaceState(null, '', targetHash);
            } else {
                inAppHistoryDepth++;
                window.history.pushState(null, '', targetHash);
            }
        }
    }

    /**
     * @param {boolean} isInitial
     * @param {number} seq
     */
    async function restoreSystemView(isInitial, seq) {
        showSystemPanel.value = true;
        resetViewerSelection();
        if (activeTab.value === 'system') {
            activeTab.value = 'files';
        }
        const targetDirId = String(currentDirectoryId.value || '0');
        if (!isInitial && loadedDirectoryId.value === targetDirId) return;
        await Promise.all([
            loadDirectory(targetDirId),
            syncBreadcrumbsForDirectory(targetDirId, seq),
        ]);
    }

    /**
     * @param {string} targetFileId
     * @param {number} seq
     * @param {Record<string, any> | null} [fallbackItem=null]
     * @param {(() => void) | null} [onViewerReady=null]
     */
    async function restoreViewerState(
        targetFileId,
        seq,
        fallbackItem = null,
        onViewerReady = null,
    ) {
        const hasMatchingLoadedDir =
            loadedDirectoryId.value === String(currentDirectoryId.value) &&
            (fallbackItem?.parentId === undefined ||
                String(fallbackItem.parentId) === String(currentDirectoryId.value));
        const existingFile = hasMatchingLoadedDir
            ? files.value.find((f) => !f.isDirectory && String(f.id) === targetFileId)
            : null;
        if (existingFile) {
            selectedFile.value = existingFile;
            view.value = 'viewer';
            if (onViewerReady) onViewerReady();
            const currentLastCrumbId = String(
                breadcrumbs.value[breadcrumbs.value.length - 1]?.id || '0',
            );
            if (currentLastCrumbId !== String(currentDirectoryId.value)) {
                await syncBreadcrumbsForDirectory(currentDirectoryId.value, seq);
            }
            return;
        }

        const fallbackName = fallbackItem?.name || `File ${targetFileId}`;
        const fallbackExt = fallbackItem?.extension || getFileExtension(fallbackItem?.name);

        try {
            const info = await fetchPathInfo(targetFileId);
            if (seq !== activeSyncSeq) return;
            const allCrumbs = buildCrumbsFromPathInfo(info);
            if (allCrumbs.length <= 1) {
                selectedFile.value = {
                    ...(fallbackItem || {}),
                    id: targetFileId,
                    name: fallbackName,
                    isDirectory: false,
                    extension: fallbackExt,
                };
                view.value = 'viewer';
                if (onViewerReady) onViewerReady();
                return;
            }

            const fileCrumb = allCrumbs[allCrumbs.length - 1];
            const folderCrumbs = allCrumbs.slice(0, -1);
            const parentDirId = String(folderCrumbs[folderCrumbs.length - 1].id);
            const ext = getFileExtension(fileCrumb.name) || fallbackExt;

            breadcrumbs.value = folderCrumbs;
            currentDirectoryId.value = parentDirId;
            selectedFile.value = {
                ...(fallbackItem || {}),
                id: targetFileId,
                name: fileCrumb.name,
                isDirectory: false,
                extension: ext,
            };
            view.value = 'viewer';
            if (onViewerReady) onViewerReady();

            await loadDirectory(parentDirId);
            if (seq !== activeSyncSeq) return;
            const loadedFile = files.value.find((f) => String(f.id) === targetFileId);
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
                isDirectory: false,
                extension: fallbackExt,
            };
            view.value = 'viewer';
            if (onViewerReady) onViewerReady();
        }
    }

    /**
     * @param {string} targetDirId
     * @param {boolean} isInitial
     * @param {number} seq
     */
    async function restoreDirectoryState(targetDirId, isInitial, seq) {
        resetViewerSelection();
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
            syncBreadcrumbsForDirectory(targetDirId, seq),
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

        if (!isInitial && rawHash === lastSyncedHash) {
            return;
        }
        lastSyncedHash = rawHash;
        if (!isInitial && inAppHistoryDepth > 0) {
            inAppHistoryDepth--;
        }

        const isStaleLoginHash = /^#\/?login(?:\?|$)/i.test(rawHash);
        if (isStaleLoginHash) {
            lastSyncedHash = '#/files';
            window.history.replaceState(null, '', '#/files');
        }
        const seq = ++activeSyncSeq;
        const parsed = parseUrlHash(isStaleLoginHash ? '#/files' : rawHash);

        if (parsed.tab === 'system' || parsed.showSystem) {
            await restoreSystemView(isInitial, seq);
            return;
        }
        showSystemPanel.value = false;
        systemOpenedFromHistory = false;

        if (parsed.tab === 'tasks' || parsed.tab === 'settings') {
            activeTab.value = parsed.tab;
            resetViewerSelection();
            viewerOpenedFromHistory = false;
            return;
        }

        activeTab.value = 'files';
        if (parsed.view === 'recycle') {
            selectedFile.value = null;
            selectedPageIndex.value = null;
            view.value = 'recycle';
            viewerOpenedFromHistory = false;
            selectedIds.value = [];
            return;
        }
        if (parsed.view === 'viewer' && parsed.fileId) {
            selectedPageIndex.value =
                typeof parsed.pageIndex === 'number' ? parsed.pageIndex : null;
            if (typeof parsed.pageIndex === 'number') {
                selectedPageJumpSeq.value++;
            }
            await restoreViewerState(String(parsed.fileId), seq);
            return;
        }

        viewerOpenedFromHistory = false;
        await restoreDirectoryState(String(parsed.dirId || '0'), isInitial, seq);
    }

    async function clearOAuthRoute() {
        pendingOAuthRequest.value = null;
        lastSyncedHash = '#/files';
        window.history.replaceState(null, '', '#/files');
        if (isLoggedIn.value) {
            await restoreDirectoryState('0', true, ++activeSyncSeq);
        }
    }

    /**
     * @param {'files' | 'tasks' | 'settings'} tab
     */
    async function switchTab(tab) {
        showSystemPanel.value = false;
        systemOpenedFromHistory = false;
        activeTab.value = tab;
        if (tab === 'files') {
            viewerOpenedFromHistory = false;
            resetViewerSelection();
            updateUrl();
            await restoreDirectoryState(
                String(currentDirectoryId.value || '0'),
                false,
                ++activeSyncSeq,
            );
        } else {
            updateUrl();
        }
    }

    function openRecycleBin() {
        showSystemPanel.value = false;
        systemOpenedFromHistory = false;
        activeTab.value = 'files';
        selectedFile.value = null;
        selectedPageIndex.value = null;
        viewerOpenedFromHistory = false;
        recycleOpenedFromHistory = true;
        selectedIds.value = [];
        view.value = 'recycle';
        updateUrl();
    }

    async function closeRecycleBin() {
        if (recycleOpenedFromHistory && inAppHistoryDepth > 0) {
            recycleOpenedFromHistory = false;
            window.history.back();
            return;
        }
        recycleOpenedFromHistory = false;
        resetViewerSelection();
        viewerOpenedFromHistory = false;
        updateUrl(true);
        await restoreDirectoryState(
            String(currentDirectoryId.value || '0'),
            false,
            ++activeSyncSeq,
        );
    }

    function openSystemPanel() {
        systemOpenedFromHistory = true;
        showSystemPanel.value = true;
        updateUrl();
    }

    async function closeSystemPanel() {
        if (systemOpenedFromHistory && inAppHistoryDepth > 0) {
            systemOpenedFromHistory = false;
            window.history.back();
            return;
        }
        systemOpenedFromHistory = false;
        showSystemPanel.value = false;
        updateUrl(true);
        if (activeTab.value === 'files' && view.value === 'grid') {
            await restoreDirectoryState(
                String(currentDirectoryId.value || '0'),
                false,
                ++activeSyncSeq,
            );
        }
    }

    async function closeViewer() {
        if (viewerOpenedFromHistory && inAppHistoryDepth > 0) {
            viewerOpenedFromHistory = false;
            window.history.back();
            return;
        }
        viewerOpenedFromHistory = false;
        resetViewerSelection();
        updateUrl(true);
        await restoreDirectoryState(
            String(currentDirectoryId.value || '0'),
            false,
            ++activeSyncSeq,
        );
    }

    /**
     * @param {number} pageIdx
     */
    function handleViewerPageChange(pageIdx) {
        if (
            view.value !== 'viewer' ||
            typeof pageIdx !== 'number' ||
            Number.isNaN(pageIdx) ||
            pageIdx < 0
        ) {
            return;
        }
        if (selectedPageIndex.value === pageIdx) return;
        selectedPageIndex.value = pageIdx;
        updateUrl(true);
    }

    /**
     * Navigate to a breadcrumb index in the current path hierarchy.
     * @param {number} index
     */
    async function navigateTo(index) {
        const crumbs = breadcrumbs.value.slice(0, index + 1);
        const target = crumbs[crumbs.length - 1];
        if (!target) return;
        breadcrumbs.value = crumbs;
        showSystemPanel.value = false;
        systemOpenedFromHistory = false;
        activeTab.value = 'files';
        resetViewerSelection();
        viewerOpenedFromHistory = false;
        currentDirectoryId.value = String(target.id);
        selectedIds.value = [];
        updateUrl();
        await loadDirectory(target.id);
    }

    /**
     * Open a directory or file item from the file browser, global search,
     * cross-notebook link, or system status drawer.
     *
     * @param {Record<string, any> | null | undefined} item
     */
    async function openItem(item) {
        if (!item) return;
        const replaceModalHistory = systemOpenedFromHistory && inAppHistoryDepth > 0;
        const wasSystemUrl = window.location.hash.startsWith('#/system');

        if (item.isDirectory) {
            const targetId = String(item.id);
            const prevDirId = String(currentDirectoryId.value || '0');
            const existingIndex = breadcrumbs.value.findIndex((c) => String(c.id) === targetId);
            const isChildOfLoadedDir =
                existingIndex === -1 &&
                loadedDirectoryId.value === prevDirId &&
                Boolean(item.name) &&
                files.value.some((f) => f.isDirectory && String(f.id) === targetId);

            showSystemPanel.value = false;
            systemOpenedFromHistory = false;
            activeTab.value = 'files';
            resetViewerSelection();
            viewerOpenedFromHistory = false;
            currentDirectoryId.value = targetId;
            selectedIds.value = [];
            if (existingIndex > -1) {
                breadcrumbs.value = breadcrumbs.value.slice(0, existingIndex + 1);
            } else if (isChildOfLoadedDir) {
                const depthIndex = Math.max(0, breadcrumbs.value.length - 1);
                breadcrumbs.value = [
                    ...breadcrumbs.value,
                    { id: targetId, name: formatCrumbName(item.name, depthIndex) },
                ];
            }
            updateUrl(replaceModalHistory);

            const seq = ++activeSyncSeq;
            if (existingIndex > -1 || isChildOfLoadedDir) {
                await loadDirectory(targetId);
            } else {
                await Promise.all([
                    loadDirectory(targetId),
                    syncBreadcrumbsForDirectory(targetId, seq),
                ]);
            }
            return;
        }

        const targetFileId = String(item.id);
        const targetPage = typeof item.pageIndex === 'number' ? item.pageIndex : null;

        if (view.value === 'viewer' && String(selectedFile.value?.id) === targetFileId) {
            showSystemPanel.value = false;
            systemOpenedFromHistory = false;
            activeTab.value = 'files';
            selectedPageIndex.value = targetPage ?? 0;
            selectedPageJumpSeq.value++;
            updateUrl(wasSystemUrl ? replaceModalHistory : true);
            const currentLastCrumbId = String(
                breadcrumbs.value[breadcrumbs.value.length - 1]?.id || '0',
            );
            if (currentLastCrumbId !== String(currentDirectoryId.value)) {
                await syncBreadcrumbsForDirectory(currentDirectoryId.value, ++activeSyncSeq);
            }
            return;
        }

        const seq = ++activeSyncSeq;
        showSystemPanel.value = false;
        systemOpenedFromHistory = false;
        activeTab.value = 'files';
        viewerOpenedFromHistory = true;
        selectedPageIndex.value = targetPage;
        if (targetPage !== null) {
            selectedPageJumpSeq.value++;
        }
        await restoreViewerState(targetFileId, seq, item, () => {
            if (seq === activeSyncSeq) {
                updateUrl(replaceModalHistory);
            }
        });
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
        openRecycleBin,
        closeRecycleBin,
        openSystemPanel,
        closeSystemPanel,
        closeViewer,
        handleViewerPageChange,
        openItem,
        navigateTo,
        resetSessionRoutes,
    };
}
