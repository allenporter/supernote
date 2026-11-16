/**
 * Supernote Cloud Web UI — Host UI Root Application Shell.
 *
 * Coordinates session authentication, OAuth 2.1 consent bridging, top-level
 * tab/route switching, global search (`Cmd/Ctrl+K`), system status drawer,
 * and toast notifications while delegating domain panels to `FileBrowserPanel`,
 * `FileViewer`, and `TaskPanel`.
 */

import { createApp, ref, onMounted, onUnmounted, computed } from 'vue';
import { useFileSystem } from './composables/useFileSystem.js';
import { useProcessingStatus } from './composables/useProcessingStatus.js';
import { useRouter, parseUrlHash, buildUrlHash } from './composables/useRouter.js';
import { useToast } from './composables/useToast.js';
import {
    ApiError,
    getToken,
    login,
    logout,
    onLogout,
    connectSocket,
    submitOAuthBridgeDecision
} from './api/client.js';
import FileBrowserPanel, { compareItems } from './components/FileBrowserPanel.js';
import SearchModal from './components/SearchModal.js';
import TaskPanel from './components/TaskPanel.js';
import LoginCard from './components/LoginCard.js';
import OAuthConsentCard from './components/OAuthConsentCard.js';
import FileViewer from './components/FileViewer.js';
import SystemPanel from './components/SystemPanel.js';

export { parseUrlHash, buildUrlHash, compareItems };

createApp({
    components: {
        'file-browser-panel': FileBrowserPanel,
        SearchModal,
        TaskPanel,
        LoginCard,
        'oauth-consent-card': OAuthConsentCard,
        FileViewer,
        SystemPanel
    },
    setup() {
        const { toasts, showToast, dismissToast } = useToast();

        // Auth & OAuth Consent State
        const isLoggedIn = ref(false);
        const isSubmittingOAuth = ref(false);
        /** @type {import('vue').Ref<'approved' | 'denied' | null>} */
        const oauthCompletedOutcome = ref(null);
        const unsubscribeLogout = onLogout(() => {
            isLoggedIn.value = false;
        });

        // Search & Cross-Tab Focus State
        const showSearchModal = ref(false);
        const searchInitialQuery = ref('');
        const searchShortcutLabel = typeof navigator !== 'undefined' &&
            /Mac|iPod|iPhone|iPad/i.test(navigator.platform || navigator.userAgent || '')
            ? '⌘K'
            : 'Ctrl K';
        /** @type {import('vue').Ref<Record<string, any> | null>} */
        const focusedTaskRequest = ref(null);
        /** @type {import('vue').Ref<Array<string | number>>} */
        const selectedIds = ref([]);

        // Shared VFS State
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
            navigateTo
        } = useRouter({
            isLoggedIn,
            files,
            currentDirectoryId,
            loadedDirectoryId,
            loadDirectory,
            selectedIds,
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

        /**
         * @param {string | number} itemId
         * @param {string} newName
         */
        async function handleRenameItem(itemId, newName) {
            await renameSelectedItem(itemId, newName);
            const crumb = breadcrumbs.value.find(c => String(c.id) === String(itemId));
            if (crumb) {
                crumb.name = newName;
            }
        }

        /**
         * @param {Record<string, any> | null} item
         */
        async function handleSearchSelectFile(item) {
            if (!item) return;
            showSearchModal.value = false;
            await openItem(item);
        }

        /**
         * @param {Record<string, any> | null} task
         */
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

        /**
         * @param {string | number | null} fileId
         */
        async function handleSystemOpenFile(fileId) {
            if (!fileId) return;
            await openItem({ id: String(fileId), isDirectory: false });
        }

        async function resumeSession() {
            const token = getToken();
            if (!token) return false;
            isLoggedIn.value = true;
            connectSocket();
            return true;
        }

        /**
         * @param {{ email: string, password: string }} credentials
         */
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

        /**
         * @param {'approve' | 'deny'} decision
         */
        async function submitOAuthDecision(decision) {
            const req = pendingOAuthRequest.value;
            if (!req || !req.isValid || !req.bridgePathWithQuery || isSubmittingOAuth.value) return;
            if (!getToken()) {
                isLoggedIn.value = false;
                showToast('Please sign in to authorize this application.', 'error');
                return;
            }
            isSubmittingOAuth.value = true;
            let keepLockedForNavigation = false;
            try {
                const data = await submitOAuthBridgeDecision(req.bridgePathWithQuery, decision);
                if (req.redirectTarget?.isCustomScheme) {
                    oauthCompletedOutcome.value = decision === 'approve' ? 'approved' : 'denied';
                } else {
                    keepLockedForNavigation = true;
                }
                window.location.assign(data.redirect_url);
            } catch (e) {
                if (e instanceof ApiError && e.status === 401) {
                    showToast('Your session expired. Please sign in again.', 'error');
                } else if (e instanceof ApiError && e.status === 400) {
                    pendingOAuthRequest.value = { ...req, isValid: false, error: e.message };
                } else {
                    const message = e instanceof Error ? e.message : String(e);
                    showToast('Authorization failed: ' + message, 'error');
                }
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

        /**
         * @param {string} [initialQuery='']
         */
        function openSearchWithQuery(initialQuery = '') {
            searchInitialQuery.value = typeof initialQuery === 'string' ? initialQuery : '';
            showSearchModal.value = true;
        }

        function closeSearchModal() {
            showSearchModal.value = false;
            searchInitialQuery.value = '';
        }

        /**
         * @param {KeyboardEvent} e
         */
        const handleGlobalKeydown = (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
                if (!isLoggedIn.value || pendingOAuthRequest.value) return;
                e.preventDefault();
                if (showSearchModal.value) {
                    closeSearchModal();
                } else {
                    openSearchWithQuery('');
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
            window.addEventListener('keydown', handleGlobalKeydown);
        });

        onUnmounted(() => {
            unsubscribeLogout();
            window.removeEventListener('supernote:file-sync', handleFileSyncEvent);
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
            focusedTaskRequest,
            view,
            files,
            currentDirectoryId,
            isLoading,
            error,
            breadcrumbs,
            selectedIds,
            createNewFolder,
            deleteSelectedItems,
            moveSelectedItems,
            uploadFiles,
            handleRenameItem,
            switchTab,
            openSystemPanel,
            closeSystemPanel,
            closeViewer,
            handleViewerPageChange,
            openItem,
            navigateTo,
            selectedFile,
            selectedPageIndex,
            selectedPageJumpSeq,
            showSystemPanel,
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
