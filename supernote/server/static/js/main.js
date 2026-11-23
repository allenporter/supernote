/**
 * Supernote Cloud Web UI — Host UI Root Application Shell.
 *
 * Coordinates session authentication, OAuth 2.1 consent bridging, top-level
 * tab/route switching, global search (`Cmd/Ctrl+K`), system status drawer,
 * and toast notifications while delegating domain panels to `FileBrowserPanel`,
 * `FileViewer`, `TaskPanel`, and `SettingsPanel`.
 */

import { computed, createApp, onMounted, onUnmounted, ref } from 'vue';
import { connectSocket, login, submitOAuthBridgeDecision } from './api/client.js';
import { ApiError, getToken, logout, onLogout } from './api/http.js';
import FileBrowserPanel from './components/FileBrowserPanel.js';
import FileViewer from './components/FileViewer.js';
import LoginCard from './components/LoginCard.js';
import OAuthConsentCard from './components/OAuthConsentCard.js';
import RecycleBinPanel from './components/RecycleBinPanel.js';
import SearchModal from './components/SearchModal.js';
import SettingsPanel from './components/SettingsPanel.js';
import SystemPanel from './components/SystemPanel.js';
import TaskPanel from './components/TaskPanel.js';
import { useFileSystem } from './composables/useFileSystem.js';
import { resetEscapeStack } from './composables/useModalEscape.js';
import { useProcessingStatus } from './composables/useProcessingStatus.js';
import { useRecycleBin } from './composables/useRecycleBin.js';
import { useRouter } from './composables/useRouter.js';
import { useToast } from './composables/useToast.js';
import { getErrorMessage } from './utils/format.js';

createApp({
    components: {
        'file-browser-panel': FileBrowserPanel,
        'recycle-bin-panel': RecycleBinPanel,
        SearchModal,
        TaskPanel,
        SettingsPanel,
        LoginCard,
        'oauth-consent-card': OAuthConsentCard,
        FileViewer,
        SystemPanel,
    },
    setup() {
        const { toasts, showToast, dismissToast, clearToasts } = useToast();

        // Auth & OAuth Consent State
        const isLoggedIn = ref(false);
        const isLoggingIn = ref(false);
        const isSubmittingOAuth = ref(false);
        /** @type {import('vue').Ref<'approved' | 'denied' | null>} */
        const oauthCompletedOutcome = ref(null);

        // Search & Cross-Tab Focus State
        const showSearchModal = ref(false);
        const searchInitialQuery = ref('');
        const searchShortcutLabel =
            typeof navigator !== 'undefined' &&
            /Mac|iPod|iPhone|iPad/i.test(navigator.platform || navigator.userAgent || '')
                ? '⌘K'
                : 'Ctrl K';
        /** @type {import('vue').Ref<FocusedTaskRequest | null>} */
        const focusedTaskRequest = ref(null);
        /** @type {import('vue').Ref<string[]>} */
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
            renameSelectedItem,
            resetFileSystem,
        } = useFileSystem();

        // Recycle Bin State
        const {
            items: recycleItems,
            selectedIds: recycleSelectedIds,
            isLoading: isLoadingRecycle,
            isMutating: isMutatingRecycle,
            error: recycleError,
            loadRecycleBin,
            restoreItems: restoreRecycleItems,
            deleteItemsPermanently: deleteRecycleItemsPermanently,
            emptyRecycleBin,
            resetRecycleBin,
        } = useRecycleBin();

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
            openRecycleBin,
            closeRecycleBin,
            openSystemPanel,
            closeSystemPanel,
            closeViewer,
            handleViewerPageChange,
            openItem,
            navigateTo,
            resetSessionRoutes,
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
            },
        });

        /**
         * @param {string | number} itemId
         * @param {string} newName
         */
        async function handleRenameItem(itemId, newName) {
            await renameSelectedItem(itemId, newName);
            const crumb = breadcrumbs.value.find((c) => String(c.id) === String(itemId));
            if (crumb) {
                crumb.name = newName;
            }
        }

        function handleRecycleRestored() {
            loadedDirectoryId.value = null;
        }

        /**
         * @param {Partial<FileItem> | null} item
         */
        async function handleSearchSelectFile(item) {
            if (!item) return;
            showSearchModal.value = false;
            await openItem(item);
        }

        /**
         * @param {Partial<ScheduleTask> | null} task
         */
        async function handleSearchSelectTask(task) {
            showSearchModal.value = false;
            focusedTaskRequest.value = task?.id
                ? {
                      id: String(task.id),
                      title: task.title || '',
                      status: task.status === 'completed' ? 'completed' : 'needsAction',
                      seq: Date.now(),
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
            if (isLoggingIn.value) return;
            isLoggingIn.value = true;
            try {
                await login(email, password);
                const loggedIn = await resumeSession();
                if (loggedIn) {
                    await syncFromUrl(true);
                    updateUrl(true);
                }
            } catch (e) {
                showToast(getErrorMessage(e));
            } finally {
                isLoggingIn.value = false;
            }
        }

        /**
         * @param {'approve' | 'deny'} decision
         */
        async function submitOAuthDecision(decision) {
            const req = pendingOAuthRequest.value;
            if (!req?.isValid || !req.bridgePathWithQuery || isSubmittingOAuth.value) return;
            if (!getToken()) {
                isLoggedIn.value = false;
                showToast('Please sign in to authorize this application.', 'error');
                return;
            }
            isSubmittingOAuth.value = true;
            let keepLockedForNavigation = false;
            try {
                const redirectUrl = await submitOAuthBridgeDecision(
                    req.bridgePathWithQuery,
                    decision,
                );
                if (req.redirectTarget?.isCustomScheme) {
                    oauthCompletedOutcome.value = decision === 'approve' ? 'approved' : 'denied';
                } else {
                    keepLockedForNavigation = true;
                }
                window.location.assign(redirectUrl);
            } catch (e) {
                if (e instanceof ApiError && e.status === 401) {
                    showToast('Your session expired. Please sign in again.', 'error');
                } else if (e instanceof ApiError && e.status === 400) {
                    pendingOAuthRequest.value = { ...req, isValid: false, error: e.message };
                } else {
                    showToast(`Authorization failed: ${getErrorMessage(e)}`, 'error');
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

        const { processingStatuses, resetProcessingStatuses } = useProcessingStatus({
            files,
            isLoggedIn: computed(() => isLoggedIn.value && !pendingOAuthRequest.value),
            activeTab,
            view,
        });

        const unsubscribeLogout = onLogout(() => {
            isLoggedIn.value = false;
            showSearchModal.value = false;
            searchInitialQuery.value = '';
            focusedTaskRequest.value = null;
            selectedIds.value = [];
            resetEscapeStack();
            resetFileSystem();
            resetRecycleBin();
            resetSessionRoutes();
            resetProcessingStatuses();
            clearToasts();
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
            if (view.value === 'recycle') {
                loadRecycleBin();
            } else {
                loadDirectory(currentDirectoryId.value || '0');
            }
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
            isLoggingIn,
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
            openRecycleBin,
            closeRecycleBin,
            recycleItems,
            recycleSelectedIds,
            isLoadingRecycle,
            isMutatingRecycle,
            recycleError,
            loadRecycleBin,
            restoreRecycleItems,
            deleteRecycleItemsPermanently,
            emptyRecycleBin,
            handleRecycleRestored,
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
            handleSystemOpenFile,
        };
    },
}).mount('#app');
