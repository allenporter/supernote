import { onMounted, onUnmounted, ref, watch } from 'vue';
import { fetchProcessingStatus } from '../api/client.js';

const ACTIVE_PROCESSING_STATUSES = new Set(['PENDING', 'PROCESSING']);
const STATUS_POLL_INTERVAL_MS = 3000;

/**
 * @param {Object} options
 * @param {import('vue').Ref<FileItem[]>} options.files
 * @param {import('vue').Ref<boolean> | import('vue').ComputedRef<boolean>} options.isLoggedIn
 * @param {import('vue').Ref<string>} options.activeTab
 * @param {import('vue').Ref<string>} options.view
 */
export function useProcessingStatus({ files, isLoggedIn, activeTab, view }) {
    /** @type {import('vue').Ref<Record<string, string>>} */
    const processingStatuses = ref({});
    /** @type {ReturnType<typeof setTimeout> | null} */
    let statusPollTimer = null;
    let statusPollInFlight = false;

    function stopStatusPoll() {
        if (statusPollTimer !== null) {
            clearTimeout(statusPollTimer);
            statusPollTimer = null;
        }
    }

    function getDirectoryNoteIds() {
        return files.value
            .filter((f) => f.extension === 'note' && f.id !== undefined && f.id !== null)
            .map((f) => String(f.id));
    }

    /**
     * @param {string[]} noteIds
     */
    function shouldKeepPollingStatuses(noteIds) {
        if (!isLoggedIn.value || activeTab.value !== 'files' || view.value !== 'grid') {
            return false;
        }
        if (typeof document !== 'undefined' && document.hidden) {
            return false;
        }
        return noteIds.some((id) => {
            const status = processingStatuses.value[String(id)] ?? processingStatuses.value[id];
            return status === undefined || ACTIVE_PROCESSING_STATUSES.has(status);
        });
    }

    async function refreshProcessingStatuses({ force = false } = {}) {
        stopStatusPoll();
        if (!isLoggedIn.value || activeTab.value !== 'files' || view.value !== 'grid') {
            return;
        }
        if (typeof document !== 'undefined' && document.hidden) {
            return;
        }
        const noteFileIds = getDirectoryNoteIds();
        if (noteFileIds.length === 0) {
            return;
        }
        if (!force && !shouldKeepPollingStatuses(noteFileIds)) {
            return;
        }
        if (statusPollInFlight) {
            return;
        }

        statusPollInFlight = true;
        let pollFailed = false;
        try {
            /** @type {{ success: boolean, statusMap: Record<string, any> }} */
            const result = await fetchProcessingStatus(noteFileIds);
            if (result.success) {
                processingStatuses.value = {
                    ...processingStatuses.value,
                    ...result.statusMap,
                };
            } else {
                pollFailed = true;
            }
        } catch (e) {
            pollFailed = true;
            console.error('Status poll error:', e);
        } finally {
            statusPollInFlight = false;
        }

        if (!pollFailed && shouldKeepPollingStatuses(getDirectoryNoteIds())) {
            statusPollTimer = setTimeout(() => {
                refreshProcessingStatuses();
            }, STATUS_POLL_INTERVAL_MS);
        }
    }

    function handleDigestSync() {
        if (!isLoggedIn.value) return;
        refreshProcessingStatuses({ force: true });
    }

    function handleVisibilityChange() {
        if (document.hidden) {
            stopStatusPoll();
        } else {
            refreshProcessingStatuses();
        }
    }

    watch(files, () => {
        refreshProcessingStatuses({ force: true });
    });

    watch([activeTab, view], ([tab, currentView]) => {
        if (tab === 'files' && currentView === 'grid') {
            refreshProcessingStatuses();
        } else {
            stopStatusPoll();
        }
    });

    onMounted(() => {
        window.addEventListener('supernote:digest-sync', handleDigestSync);
        document.addEventListener('visibilitychange', handleVisibilityChange);
    });

    onUnmounted(() => {
        stopStatusPoll();
        window.removeEventListener('supernote:digest-sync', handleDigestSync);
        document.removeEventListener('visibilitychange', handleVisibilityChange);
    });

    return {
        processingStatuses,
        refreshProcessingStatuses,
        stopStatusPoll,
    };
}
