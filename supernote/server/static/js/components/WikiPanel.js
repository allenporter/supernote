/**
 * LLM Wiki browser, Markdown viewer, inline editor, lint triage, and Obsidian export panel.
 */

import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { ApiError } from '../api/http.js';
import {
    deleteWikiPage,
    downloadWikiVaultZip,
    fetchWikiLintIssues,
    fetchWikiPage,
    fetchWikiPages,
    fetchWikiStatus,
    formatLintTypeLabel,
    formatPageKindLabel,
    formatSourceRef,
    formatWikiActionResult,
    resolveWikiLintIssue,
    saveWikiPage,
    searchWikiPages,
    triggerWikiCompile,
} from '../api/wiki.js';
import { isComponentRunning } from '../composables/useServerFeatures.js';
import { useToast } from '../composables/useToast.js';
import { getErrorMessage } from '../utils/format.js';
import { renderWikiMarkdown } from '../utils/markdown.js';

const KIND_FILTERS = [
    { id: '', label: 'All' },
    { id: 'project', label: 'Projects' },
    { id: 'entity', label: 'Entities' },
    { id: 'topic', label: 'Topics' },
    { id: 'source_digest', label: 'Sources' },
];

export default {
    name: 'WikiPanel',
    props: {
        initialSlug: {
            type: String,
            default: '',
        },
    },
    emits: ['select-slug', 'open-file', 'open-task'],
    /**
     * @param {{ initialSlug: string }} props
     * @param {{
     *   emit: {
     *     (event: 'select-slug', slug: string, replace?: boolean): void,
     *     (event: 'open-file', target: { id: string, pageIndex?: number | null }): void,
     *     (event: 'open-task', task: { id: string, title?: string }): void,
     *   }
     * }} ctx
     */
    setup(props, { emit }) {
        const { showToast } = useToast();

        const isLoading = ref(true);
        const isDisabled = ref(false);
        const isBusy = ref(false);
        /** @type {import('vue').Ref<'incremental' | 'backfill' | 'lint' | ''>} */
        const runningAction = ref('');
        const error = ref('');

        /** @type {import('vue').Ref<import('../api/wiki.js').WikiPage[]>} */
        const pages = ref([]);
        /** @type {import('vue').Ref<import('../api/wiki.js').WikiSearchHit[] | null>} */
        const searchHits = ref(null);
        /** @type {import('vue').Ref<import('../api/wiki.js').WikiPage | null>} */
        const activePage = ref(null);
        /** @type {import('vue').Ref<import('../api/wiki.js').WikiStatus | null>} */
        const status = ref(null);
        /** @type {import('vue').Ref<import('../api/wiki.js').WikiLintIssue[]>} */
        const lintIssues = ref([]);

        const selectedKind = ref('');
        const searchQuery = ref('');
        const showLintPanel = ref(false);
        const showBackfillPanel = ref(false);
        const backfillBannerDismissed = ref(false);
        const stopBackfillRequested = ref(false);
        /** @type {import('vue').Ref<string[]>} */
        const activeBatchFiles = ref([]);
        /**
         * @type {import('vue').Ref<{
         *   filesProcessed: string[],
         *   updatedPages: string[],
         *   batchesRun: number,
         *   completed: boolean,
         *   stopped: boolean,
         * } | null>}
         */
        const lastBackfillSummary = ref(null);
        const isEditing = ref(false);
        const isCreating = ref(false);
        const confirmDeleteSlug = ref('');

        const editSlug = ref('');
        const editTitle = ref('');
        const editKind = ref('topic');
        const editSummary = ref('');
        const editBody = ref('');

        let loadSeq = 0;
        let selectSeq = 0;
        let isUnmounted = false;
        /** @type {ReturnType<typeof setInterval> | null} */
        let backfillPollTimer = null;
        let backfillPollInFlight = false;

        const filteredPages = computed(() => {
            const source = searchHits.value !== null ? searchHits.value : pages.value;
            if (!selectedKind.value) return source;
            return source.filter((p) => p.page_kind === selectedKind.value);
        });

        const renderedBodyHtml = computed(() =>
            activePage.value ? renderWikiMarkdown(activePage.value.body_md) : '',
        );

        const backfillTotal = computed(() => status.value?.backfill_total_files ?? 0);
        const backfillRemaining = computed(() => status.value?.backfill_remaining_files ?? 0);
        const backfillTotalPages = computed(() => status.value?.backfill_total_pages ?? 0);
        const backfillRemainingPages = computed(() => status.value?.backfill_remaining_pages ?? 0);
        const backfillUntranscribed = computed(
            () => status.value?.backfill_untranscribed_files ?? 0,
        );
        const backfillNextFiles = computed(() =>
            Array.isArray(status.value?.backfill_next_files)
                ? status.value.backfill_next_files
                : [],
        );
        const backfillCompleted = computed(() =>
            Math.max(0, backfillTotal.value - backfillRemaining.value),
        );
        const backfillCompletedPages = computed(() =>
            Math.max(0, backfillTotalPages.value - backfillRemainingPages.value),
        );
        const backfillPercent = computed(() => {
            if (backfillTotalPages.value > 0) {
                return Math.min(
                    100,
                    Math.round((backfillCompletedPages.value / backfillTotalPages.value) * 100),
                );
            }
            if (backfillTotal.value <= 0) return 0;
            return Math.min(100, Math.round((backfillCompleted.value / backfillTotal.value) * 100));
        });
        const nextBatchCount = computed(() => Math.min(5, backfillRemaining.value));
        const isBackfillDone = computed(
            () => backfillTotal.value > 0 && backfillRemaining.value === 0,
        );
        const isServerBackfilling = computed(() => status.value?.status === 'backfilling');
        const isBackfillActive = computed(
            () => runningAction.value === 'backfill' || isServerBackfilling.value,
        );
        const isBackfillBannerVisible = computed(() => {
            if (isDisabled.value || error.value) return false;
            if (isBackfillActive.value) return true;
            if (showBackfillPanel.value) return true;
            if (lastBackfillSummary.value && !backfillBannerDismissed.value) return true;
            // Show inline progress banner automatically when backfill is partially done and wiki has pages.
            if (
                pages.value.length > 0 &&
                backfillRemaining.value > 0 &&
                !backfillBannerDismissed.value
            ) {
                return true;
            }
            return false;
        });
        const warnLintCount = computed(
            () => lintIssues.value.filter((issue) => issue.severity !== 'info').length,
        );
        const hasOnlySourceDigests = computed(
            () =>
                pages.value.length > 0 && pages.value.every((p) => p.page_kind === 'source_digest'),
        );
        const pageTitleBySlug = computed(() => {
            /** @type {Record<string, string>} */
            const map = {};
            for (const p of pages.value) {
                map[p.slug] = p.title;
            }
            return map;
        });

        async function loadAll(preferredSlug = '') {
            const seq = ++loadSeq;
            isLoading.value = true;
            error.value = '';
            try {
                const list = await fetchWikiPages();
                if (seq !== loadSeq) return;
                if (list === null) {
                    isDisabled.value = true;
                    pages.value = [];
                    activePage.value = null;
                    return;
                }
                isDisabled.value = false;
                pages.value = list;
                const [st, issues] = await Promise.all([
                    fetchWikiStatus(),
                    fetchWikiLintIssues('open'),
                ]);
                if (seq !== loadSeq) return;
                status.value = st;
                lintIssues.value = issues;
                if (st?.status === 'backfilling') {
                    showBackfillPanel.value = true;
                    backfillBannerDismissed.value = false;
                    startBackfillPoll();
                } else {
                    stopBackfillPoll();
                    stopBackfillRequested.value = false;
                }

                const targetSlug =
                    preferredSlug ||
                    props.initialSlug ||
                    activePage.value?.slug ||
                    list[0]?.slug ||
                    '';
                if (targetSlug) {
                    await selectSlug(targetSlug, { replaceHistory: true });
                } else {
                    activePage.value = null;
                    emit('select-slug', '', true);
                }
            } catch (err) {
                if (seq === loadSeq) {
                    error.value = getErrorMessage(err);
                }
            } finally {
                if (seq === loadSeq) {
                    isLoading.value = false;
                }
            }
        }

        /**
         * @param {string} slug
         * @param {{ replaceHistory?: boolean, syncUrl?: boolean }} [options]
         */
        async function selectSlug(slug, { replaceHistory = false, syncUrl = true } = {}) {
            const seq = ++selectSeq;
            isEditing.value = false;
            isCreating.value = false;
            confirmDeleteSlug.value = '';
            try {
                const loaded = await fetchWikiPage(slug);
                if (seq !== selectSeq) return;
                if (!loaded) {
                    showToast(`Page "${slug}" does not exist yet`, 'info');
                    return;
                }
                activePage.value = loaded;
                if (syncUrl) {
                    emit('select-slug', loaded.slug, replaceHistory);
                }
            } catch (err) {
                if (seq === selectSeq) {
                    showToast(getErrorMessage(err), 'error');
                }
            }
        }

        function clearSearch() {
            searchQuery.value = '';
            searchHits.value = null;
        }

        async function handleSearch() {
            const q = searchQuery.value.trim();
            if (!q) {
                searchHits.value = null;
                return;
            }
            isBusy.value = true;
            try {
                const hits = await searchWikiPages(q);
                searchHits.value = hits;
                if (hits.length > 0) {
                    await selectSlug(hits[0].slug);
                } else {
                    showToast('No matching wiki pages found', 'info');
                }
            } catch (err) {
                showToast(getErrorMessage(err), 'error');
            } finally {
                isBusy.value = false;
            }
        }

        function startCreate() {
            isCreating.value = true;
            isEditing.value = true;
            editSlug.value = 'topics/new-page';
            editTitle.value = '';
            editKind.value = 'topic';
            editSummary.value = '';
            editBody.value = '';
        }

        function startEdit() {
            if (!activePage.value) return;
            isCreating.value = false;
            isEditing.value = true;
            editSlug.value = activePage.value.slug;
            editTitle.value = activePage.value.title;
            editKind.value = activePage.value.page_kind;
            editSummary.value = activePage.value.summary;
            editBody.value = activePage.value.body_md;
        }

        function cancelEdit() {
            isEditing.value = false;
            isCreating.value = false;
        }

        async function submitSave() {
            if (!editSlug.value.trim() || !editTitle.value.trim()) {
                showToast('Slug and title are required', 'error');
                return;
            }
            isBusy.value = true;
            try {
                const saved = await saveWikiPage(editSlug.value.trim(), {
                    title: editTitle.value.trim(),
                    page_kind: editKind.value,
                    summary: editSummary.value.trim(),
                    body_md: editBody.value,
                    claims: isCreating.value ? [] : activePage.value?.claims || [],
                    expected_version: isCreating.value ? 0 : activePage.value?.version,
                    change_summary: isCreating.value ? 'Created in Web UI' : 'Edited in Web UI',
                });
                isEditing.value = false;
                isCreating.value = false;
                showToast(`Saved ${saved.title}`, 'success');
                await loadAll(saved.slug);
            } catch (err) {
                const conflictData =
                    err instanceof ApiError && err.status === 409
                        ? /** @type {{ actual?: number } | null} */ (err.data)
                        : null;
                if (
                    !isCreating.value &&
                    activePage.value &&
                    typeof conflictData?.actual === 'number'
                ) {
                    activePage.value = { ...activePage.value, version: conflictData.actual };
                    showToast(
                        `Page updated elsewhere (now v${conflictData.actual}). Click Save Page again to overwrite.`,
                        'error',
                    );
                } else {
                    showToast(getErrorMessage(err), 'error');
                }
            } finally {
                isBusy.value = false;
            }
        }

        async function handleDeleteConfirmed() {
            if (!confirmDeleteSlug.value) return;
            const deletedSlug = confirmDeleteSlug.value;
            isBusy.value = true;
            try {
                await deleteWikiPage(deletedSlug);
                confirmDeleteSlug.value = '';
                activePage.value = null;
                if (searchHits.value !== null) {
                    searchHits.value = searchHits.value.filter((h) => h.slug !== deletedSlug);
                }
                emit('select-slug', '', true);
                showToast('Wiki page deleted', 'success');
                const nextSlug = pages.value.find((p) => p.slug !== deletedSlug)?.slug || '';
                await loadAll(nextSlug);
            } catch (err) {
                showToast(getErrorMessage(err), 'error');
            } finally {
                isBusy.value = false;
            }
        }

        function stopBackfillPoll() {
            if (backfillPollTimer !== null) {
                clearInterval(backfillPollTimer);
                backfillPollTimer = null;
            }
        }

        function startBackfillPoll() {
            if (backfillPollTimer !== null || isUnmounted) return;
            backfillPollTimer = setInterval(async () => {
                if (isUnmounted || backfillPollInFlight) return;
                backfillPollInFlight = true;
                try {
                    const prevStatus = status.value?.status;
                    const [list, st, issues] = await Promise.all([
                        fetchWikiPages(),
                        fetchWikiStatus(),
                        fetchWikiLintIssues('open'),
                    ]);
                    if (isUnmounted) return;
                    if (list !== null) {
                        pages.value = list;
                        if (!activePage.value && list.length > 0) {
                            await selectSlug(list[0].slug, { replaceHistory: true });
                        }
                    }
                    if (st) status.value = st;
                    lintIssues.value = issues;

                    if (st?.status !== 'backfilling') {
                        stopBackfillPoll();
                        stopBackfillRequested.value = false;
                        if (prevStatus === 'backfilling') {
                            if (
                                (st?.backfill_remaining_files ?? 0) === 0 &&
                                (st?.backfill_total_files ?? 0) > 0
                            ) {
                                showToast(
                                    `Background backfill complete — all ${st?.backfill_total_files} notebooks compiled.`,
                                    'success',
                                );
                            } else if (st?.status === 'error') {
                                showToast(
                                    st.last_error || 'Background backfill stopped with an error.',
                                    'error',
                                );
                            } else {
                                showToast(
                                    `Background backfill stopped (${st?.backfill_remaining_files ?? 0} remaining).`,
                                    'info',
                                );
                            }
                        }
                    }
                } catch {
                    // Transient poll failure; retry on next interval.
                } finally {
                    backfillPollInFlight = false;
                }
            }, 2000);
        }

        function toggleBackfillPanel() {
            if (isBackfillBannerVisible.value && !isBackfillActive.value) {
                showBackfillPanel.value = false;
                backfillBannerDismissed.value = true;
            } else {
                showBackfillPanel.value = true;
                backfillBannerDismissed.value = false;
            }
        }

        function dismissBackfillBanner() {
            if (isBackfillActive.value) return;
            showBackfillPanel.value = false;
            backfillBannerDismissed.value = true;
        }

        async function requestStopBackfill() {
            stopBackfillRequested.value = true;
            try {
                const result = await triggerWikiCompile('backfill_stop');
                const toast = formatWikiActionResult('backfill_stop', result);
                showToast(toast.message, toast.type);
            } catch (err) {
                stopBackfillRequested.value = false;
                showToast(getErrorMessage(err), 'error');
            }
        }

        /**
         * Reset the backfill cursor and optionally kick off the background rebuild immediately.
         *
         * @param {boolean} [startImmediately=true]
         */
        async function handleResetBackfill(startImmediately = true) {
            if (isBusy.value || isDisabled.value || isBackfillActive.value) return;
            isBusy.value = true;
            stopBackfillRequested.value = false;
            try {
                const resetResult = await triggerWikiCompile('backfill_reset');
                lastBackfillSummary.value = null;
                backfillBannerDismissed.value = false;
                showBackfillPanel.value = true;
                if (startImmediately && (resetResult?.remaining_files ?? 0) > 0) {
                    const startResult = await triggerWikiCompile('backfill_start', {
                        maxFiles: 1,
                    });
                    const toast = formatWikiActionResult('backfill_start', startResult);
                    showToast(toast.message, toast.type);
                } else {
                    const toast = formatWikiActionResult('backfill_reset', resetResult);
                    showToast(toast.message, toast.type);
                }
                await loadAll(activePage.value?.slug || '');
            } catch (err) {
                showToast(getErrorMessage(err), 'error');
            } finally {
                isBusy.value = false;
            }
        }

        /**
         * Run either a single synchronous backfill batch (`runAll = false`) or start
         * the server-side continuous background backfill job (`runAll = true`, 1 notebook per turn).
         *
         * @param {boolean} [runAll=false]
         */
        async function handleBackfill(runAll = false) {
            if (
                isBusy.value ||
                isDisabled.value ||
                isBackfillDone.value ||
                isBackfillActive.value
            ) {
                return;
            }
            backfillBannerDismissed.value = false;
            showBackfillPanel.value = true;

            if (runAll) {
                isBusy.value = true;
                stopBackfillRequested.value = false;
                try {
                    const result = await triggerWikiCompile('backfill_start', { maxFiles: 1 });
                    const toast = formatWikiActionResult('backfill_start', result);
                    showToast(toast.message, toast.type);
                    await loadAll(activePage.value?.slug || '');
                } catch (err) {
                    if (!isUnmounted) {
                        showToast(getErrorMessage(err), 'error');
                    }
                } finally {
                    isBusy.value = false;
                }
                return;
            }

            isBusy.value = true;
            runningAction.value = 'backfill';
            activeBatchFiles.value = [...backfillNextFiles.value];
            try {
                const result = await triggerWikiCompile('backfill', { maxFiles: 5 });
                if (isUnmounted) return;
                const toast = formatWikiActionResult('backfill', result);
                showToast(toast.message, toast.type);

                const batchFiles = Array.isArray(result?.files_processed)
                    ? result.files_processed
                    : [];
                const batchPages = Array.isArray(result?.updated_pages) ? result.updated_pages : [];
                if (batchFiles.length > 0 || batchPages.length > 0) {
                    lastBackfillSummary.value = {
                        filesProcessed: batchFiles,
                        updatedPages: batchPages,
                        batchesRun: 1,
                        completed: result?.remaining_files === 0,
                        stopped: false,
                    };
                }
                const preferredSlug = activePage.value?.slug || batchPages[0] || '';
                await loadAll(preferredSlug);
            } catch (err) {
                if (!isUnmounted) {
                    showToast(getErrorMessage(err), 'error');
                    try {
                        const refreshed = await fetchWikiStatus();
                        if (refreshed) status.value = refreshed;
                    } catch {
                        // Best-effort status refresh so persisted compiler errors surface immediately.
                    }
                }
            } finally {
                activeBatchFiles.value = [];
                runningAction.value = '';
                isBusy.value = false;
            }
        }

        /**
         * @param {'incremental' | 'backfill' | 'lint'} mode
         */
        async function handleRunAction(mode) {
            if (mode === 'backfill') {
                await handleBackfill(false);
                return;
            }
            isBusy.value = true;
            runningAction.value = mode;
            try {
                const result = await triggerWikiCompile(mode);
                const toast = formatWikiActionResult(mode, result);
                showToast(toast.message, toast.type);
                await loadAll(activePage.value?.slug || '');
            } catch (err) {
                showToast(getErrorMessage(err), 'error');
                try {
                    const refreshed = await fetchWikiStatus();
                    if (refreshed) status.value = refreshed;
                } catch {
                    // Best-effort status refresh so persisted compiler errors surface immediately.
                }
            } finally {
                runningAction.value = '';
                isBusy.value = false;
            }
        }

        /**
         * @param {number} issueId
         * @param {'resolved' | 'dismissed'} resolution
         */
        async function handleResolveIssue(issueId, resolution) {
            isBusy.value = true;
            try {
                await resolveWikiLintIssue(issueId, resolution);
                await loadAll(activePage.value?.slug || '');
            } catch (err) {
                showToast(getErrorMessage(err), 'error');
            } finally {
                isBusy.value = false;
            }
        }

        async function handleExportZip() {
            try {
                await downloadWikiVaultZip();
                showToast('Exported Obsidian vault (.zip)', 'success');
            } catch (err) {
                showToast(getErrorMessage(err), 'error');
            }
        }

        /**
         * @param {import('../api/wiki.js').WikiSourceRef} ref
         * @returns {boolean}
         */
        function isSourceClickable(ref) {
            const info = formatSourceRef(ref);
            if (!info.clickable) return false;
            if (info.kind === 'task' && !isComponentRunning('schedule')) return false;
            return true;
        }

        /**
         * Open a notebook page or schedule task cited in the active wiki page's Sources footer.
         *
         * @param {import('../api/wiki.js').WikiSourceRef} ref
         */
        function handleOpenSource(ref) {
            if (!isSourceClickable(ref)) return;
            const info = formatSourceRef(ref);
            if (info.kind === 'note' && info.fileId) {
                emit('open-file', { id: info.fileId, pageIndex: info.pageIndex });
            } else if (info.kind === 'task' && info.taskId) {
                emit('open-task', { id: info.taskId, title: info.label });
            }
        }

        /**
         * Intercept clicks on rendered `[[wikilink]]` anchors to navigate in-place.
         *
         * @param {MouseEvent} event
         */
        function handleBodyClick(event) {
            const target = /** @type {HTMLElement | null} */ (event.target);
            const link = target?.closest?.('a[data-wiki-link]');
            if (!link) return;
            const slug = link.getAttribute('data-wiki-link');
            if (slug) {
                event.preventDefault();
                selectSlug(slug);
            }
        }

        watch(
            () => props.initialSlug,
            (nextSlug) => {
                if (nextSlug && nextSlug !== activePage.value?.slug) {
                    selectSlug(nextSlug, { syncUrl: false });
                }
            },
        );

        onMounted(() => {
            loadAll(props.initialSlug);
        });

        onUnmounted(() => {
            isUnmounted = true;
            stopBackfillPoll();
        });

        return {
            KIND_FILTERS,
            formatPageKindLabel,
            formatLintTypeLabel,
            formatSourceRef,
            isSourceClickable,
            isLoading,
            isDisabled,
            isBusy,
            runningAction,
            error,
            pages,
            searchHits,
            filteredPages,
            activePage,
            status,
            lintIssues,
            warnLintCount,
            hasOnlySourceDigests,
            pageTitleBySlug,
            selectedKind,
            searchQuery,
            clearSearch,
            showLintPanel,
            showBackfillPanel,
            isBackfillBannerVisible,
            isServerBackfilling,
            isBackfillActive,
            stopBackfillRequested,
            activeBatchFiles,
            lastBackfillSummary,
            isEditing,
            isCreating,
            confirmDeleteSlug,
            editSlug,
            editTitle,
            editKind,
            editSummary,
            editBody,
            renderedBodyHtml,
            backfillTotal,
            backfillRemaining,
            backfillTotalPages,
            backfillRemainingPages,
            backfillCompletedPages,
            backfillUntranscribed,
            backfillNextFiles,
            backfillCompleted,
            backfillPercent,
            nextBatchCount,
            isBackfillDone,
            selectSlug,
            handleSearch,
            startCreate,
            startEdit,
            cancelEdit,
            submitSave,
            handleDeleteConfirmed,
            toggleBackfillPanel,
            dismissBackfillBanner,
            requestStopBackfill,
            handleResetBackfill,
            handleBackfill,
            handleRunAction,
            handleResolveIssue,
            handleExportZip,
            handleOpenSource,
            handleBodyClick,
        };
    },
    template: `
        <div class="space-y-4">
            <!-- Header Bar -->
            <div class="flex flex-wrap items-center justify-between gap-3 bg-white border border-stone-200/80 rounded-xl p-4 shadow-sm">
                <div class="min-w-0">
                    <h2 class="text-base font-semibold text-slate-900">LLM Wiki</h2>
                    <p class="text-xs text-stone-500 mt-0.5">
                        <template v-if="status">
                            {{ status.page_count }} {{ status.page_count === 1 ? 'page' : 'pages' }}
                            <template v-if="backfillTotal > 0">
                                <template v-if="backfillTotalPages > 0">
                                    · {{ backfillCompletedPages }}/{{ backfillTotalPages }} pages compiled
                                </template>
                                <template v-else>
                                    · {{ backfillCompleted }}/{{ backfillTotal }} notebooks compiled
                                </template>
                            </template>
                            <template v-if="status.status && status.status !== 'idle'">
                                · {{ status.status }}
                            </template>
                        </template>
                        <template v-else>Compiled knowledge base from notebooks &amp; tasks</template>
                    </p>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                    <button type="button" @click="startCreate" :disabled="isDisabled || isBusy"
                        class="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50 transition-colors">
                        New Page
                    </button>
                    <button v-if="backfillTotal > 0 || isBackfillActive"
                        type="button" @click="toggleBackfillPanel" :disabled="isDisabled"
                        :class="isBackfillBannerVisible ? 'bg-slate-100 border-slate-300 text-slate-900' : 'bg-white border-stone-200 text-slate-700 hover:bg-stone-50'"
                        class="px-3 py-1.5 rounded-lg text-xs font-medium border disabled:opacity-50 transition-colors">
                        <template v-if="isBackfillActive">Backfilling…</template>
                        <template v-else-if="backfillRemaining > 0">Backfill ({{ backfillRemainingPages > 0 ? backfillRemainingPages + 'p' : backfillRemaining }} left)</template>
                        <template v-else>Backfill</template>
                    </button>
                    <button type="button" @click="handleRunAction('incremental')" :disabled="isDisabled || isBusy"
                        title="Compile recent notebook and task changes since the last update"
                        class="px-3 py-1.5 rounded-lg text-xs font-medium bg-white border border-stone-200 text-slate-700 hover:bg-stone-50 disabled:opacity-50 transition-colors">
                        {{ runningAction === 'incremental' ? 'Updating…' : 'Update Wiki' }}
                    </button>
                    <button type="button" @click="showLintPanel = !showLintPanel" :disabled="isDisabled"
                        :class="showLintPanel ? 'bg-slate-100 border-slate-300 text-slate-900' : 'bg-white border-stone-200 text-slate-700 hover:bg-stone-50'"
                        class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors">
                        <span>Lint</span>
                        <span v-if="lintIssues.length > 0"
                            :class="warnLintCount > 0 ? 'bg-amber-100 text-amber-800' : 'bg-stone-100 text-stone-600'"
                            class="px-1.5 py-0.5 rounded-full text-[10px] font-semibold leading-none">
                            {{ lintIssues.length }}
                        </span>
                    </button>
                    <button type="button" @click="handleExportZip" :disabled="isDisabled || pages.length === 0"
                        title="Download Obsidian-compatible Markdown vault (.zip)"
                        class="px-3 py-1.5 rounded-lg text-xs font-medium bg-white border border-stone-200 text-slate-700 hover:bg-stone-50 disabled:opacity-50 transition-colors">
                        Export .zip
                    </button>
                </div>
            </div>

            <!-- Compiler Status / Error Banner -->
            <div v-if="!isDisabled && !error && status?.last_error"
                class="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-xs text-amber-900 break-words">
                <span class="font-semibold">Wiki compiler {{ status.status }}:</span>
                {{ status.last_error }}
            </div>

            <!-- Notebook Backfill Progress & Queue Panel -->
            <section v-if="isBackfillBannerVisible" aria-label="Notebook Backfill"
                class="bg-white border border-stone-200/80 rounded-xl p-4 shadow-sm space-y-3">
                <div class="flex items-start justify-between gap-2">
                    <div class="min-w-0 flex-1 space-y-0.5">
                        <div class="flex flex-wrap items-center gap-2">
                            <h3 class="text-xs font-semibold text-slate-900">
                                <template v-if="isBackfillActive">Compiling Notebooks…</template>
                                <template v-else-if="isBackfillDone">Backfill Complete</template>
                                <template v-else>Notebook Backfill</template>
                            </h3>
                            <span v-if="backfillTotal > 0"
                                :class="isBackfillDone ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-stone-100 text-stone-700 border-stone-200'"
                                class="text-[11px] font-medium px-2 py-0.5 rounded-full border">
                                <template v-if="backfillTotalPages > 0">
                                    {{ backfillCompletedPages }} / {{ backfillTotalPages }} pages ({{ backfillPercent }}%)<template v-if="status?.backfill_current_date"> · {{ status.backfill_current_date }}</template>
                                </template>
                                <template v-else>
                                    {{ backfillCompleted }} of {{ backfillTotal }} compiled ({{ backfillPercent }}%)
                                </template>
                            </span>
                            <span v-if="backfillUntranscribed > 0" class="text-[11px] text-stone-500">
                                · {{ backfillUntranscribed }} awaiting OCR
                            </span>
                        </div>
                        <p class="text-xs text-stone-500">
                            <template v-if="isServerBackfilling">
                                Running chronologically on the server in small page windows — safe to switch tabs or reload.
                                <template v-if="backfillNextFiles.length > 0">
                                    Up next: <span class="font-medium text-slate-700">{{ backfillNextFiles.slice(0, 3).join(', ') }}</span>
                                </template>
                            </template>
                            <template v-else-if="runningAction === 'backfill' && activeBatchFiles.length > 0">
                                Compiling {{ activeBatchFiles.length }} {{ activeBatchFiles.length === 1 ? 'notebook' : 'notebooks' }}:
                                <span class="font-medium text-slate-700">{{ activeBatchFiles.join(', ') }}</span>
                            </template>
                            <template v-else-if="runningAction === 'backfill'">
                                Compiling next batch of pages…
                            </template>
                            <template v-else-if="isBackfillDone">
                                All {{ backfillTotal }} OCR’d {{ backfillTotal === 1 ? 'notebook has' : 'notebooks have' }} been compiled into your wiki. New edits update automatically.
                            </template>
                            <template v-else>
                                Compiles OCR’d notebook pages chronologically on the server in small page windows for rich synthesis.
                            </template>
                        </p>
                    </div>
                    <button v-if="!isBackfillActive" type="button" @click="dismissBackfillBanner"
                        aria-label="Hide backfill panel"
                        class="shrink-0 text-stone-400 hover:text-slate-700 px-1.5 py-0.5 rounded text-sm leading-none transition-colors">
                        &times;
                    </button>
                </div>

                <!-- Progress Bar -->
                <div v-if="backfillTotal > 0" class="w-full h-2 rounded-full bg-stone-100 overflow-hidden"
                    role="progressbar" :aria-valuenow="backfillPercent" aria-valuemin="0" aria-valuemax="100">
                    <div :class="isBackfillDone ? 'bg-emerald-600' : 'bg-slate-900'"
                        class="h-full rounded-full transition-all duration-300"
                        :style="{ width: backfillPercent + '%' }"></div>
                </div>

                <!-- Last Batch Summary with clickable page links -->
                <div v-if="lastBackfillSummary && lastBackfillSummary.filesProcessed.length > 0"
                    class="rounded-lg bg-stone-50 border border-stone-200/70 px-3 py-2 text-xs space-y-1.5">
                    <div class="text-stone-600">
                        <span class="font-medium text-slate-800">
                            {{ lastBackfillSummary.batchesRun > 1 ? 'Session total:' : 'Last batch:' }}
                        </span>
                        compiled {{ lastBackfillSummary.filesProcessed.length }}
                        {{ lastBackfillSummary.filesProcessed.length === 1 ? 'notebook' : 'notebooks' }}
                        &rarr;
                        {{ lastBackfillSummary.updatedPages.length }}
                        {{ lastBackfillSummary.updatedPages.length === 1 ? 'page' : 'pages' }} updated.
                    </div>
                    <div v-if="lastBackfillSummary.updatedPages.length > 0" class="flex flex-wrap items-center gap-1.5">
                        <span class="text-[11px] text-stone-500">Updated pages:</span>
                        <button v-for="slug in lastBackfillSummary.updatedPages.slice(0, 8)" :key="slug"
                            type="button" @click="selectSlug(slug)"
                            class="px-2 py-0.5 rounded-md bg-white border border-stone-200 hover:border-slate-300 text-[11px] font-medium text-slate-700 hover:text-slate-900 transition-colors">
                            {{ pageTitleBySlug[slug] || slug }}
                        </button>
                        <span v-if="lastBackfillSummary.updatedPages.length > 8" class="text-[11px] text-stone-400">
                            +{{ lastBackfillSummary.updatedPages.length - 8 }} more
                        </span>
                    </div>
                </div>

                <!-- Next Batch Queue Preview & Controls -->
                <div v-if="backfillRemaining > 0 || isBackfillDone" class="flex flex-col sm:flex-row sm:items-end justify-between gap-3 pt-0.5">
                    <div v-if="backfillRemaining > 0 && backfillNextFiles.length > 0 && !isBackfillActive" class="min-w-0 flex-1 space-y-1">
                        <div class="text-[11px] font-medium text-stone-500">
                            Up next (oldest first):
                        </div>
                        <div class="flex flex-wrap gap-1.5">
                            <span v-for="fname in backfillNextFiles" :key="fname"
                                class="px-2 py-0.5 rounded-md bg-stone-100 text-stone-700 font-mono text-[11px] max-w-full truncate">
                                {{ fname }}
                            </span>
                        </div>
                    </div>
                    <div v-else class="min-w-0 flex-1"></div>
                    <div class="flex flex-wrap items-center gap-2 shrink-0">
                        <template v-if="isBackfillActive">
                            <button v-if="isServerBackfilling" type="button" @click="requestStopBackfill"
                                :disabled="stopBackfillRequested"
                                class="px-3 py-1.5 rounded-lg text-xs font-medium border border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100 disabled:opacity-50 transition-colors">
                                {{ stopBackfillRequested ? 'Stopping after current batch…' : 'Stop After Current Batch' }}
                            </button>
                            <span v-else class="text-xs text-stone-500">Running single batch…</span>
                        </template>
                        <template v-else-if="backfillRemaining > 0">
                            <button type="button" @click="handleBackfill(true)" :disabled="isBusy"
                                class="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50 transition-colors">
                                Backfill All Remaining ({{ backfillRemainingPages > 0 ? backfillRemainingPages + ' pages' : backfillRemaining }})
                            </button>
                            <button v-if="backfillRemaining > nextBatchCount" type="button" @click="handleBackfill(false)" :disabled="isBusy"
                                class="px-3 py-1.5 rounded-lg text-xs font-medium bg-white border border-stone-200 text-slate-700 hover:bg-stone-50 disabled:opacity-50 transition-colors">
                                Next Batch
                            </button>
                            <button v-if="backfillCompleted > 0" type="button" @click="handleResetBackfill(false)" :disabled="isBusy"
                                class="px-3 py-1.5 rounded-lg text-xs font-medium bg-white border border-stone-200 text-stone-600 hover:bg-stone-50 disabled:opacity-50 transition-colors">
                                Reset Cursor
                            </button>
                        </template>
                        <template v-else-if="isBackfillDone">
                            <button type="button" @click="handleResetBackfill(true)" :disabled="isBusy"
                                title="Reset backfill cursor and immediately rebuild all OCR'd notebooks in the background"
                                class="px-3 py-1.5 rounded-lg text-xs font-medium bg-white border border-stone-200 text-slate-700 hover:bg-stone-50 disabled:opacity-50 transition-colors">
                                Reset &amp; Rebuild
                            </button>
                        </template>
                    </div>
                </div>
            </section>

            <!-- Disabled Banner -->
            <div v-if="isDisabled" class="bg-amber-50 border border-amber-200 rounded-xl p-6 text-center">
                <p class="text-sm font-medium text-amber-900">LLM Wiki component is disabled</p>
                <p class="text-xs text-amber-700 mt-1">Enable <code>wiki.enabled: true</code> in your server config to use the knowledge base.</p>
            </div>

            <!-- Error Banner -->
            <div v-else-if="error" class="bg-red-50 border border-red-200 rounded-xl p-4 text-xs text-red-700">
                {{ error }}
            </div>

            <!-- Main Two-Pane Workspace -->
            <div v-else class="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
                <!-- Left Navigation Sidebar -->
                <aside class="lg:col-span-4 bg-white border border-stone-200/80 rounded-xl p-3 shadow-sm space-y-3">
                    <form @submit.prevent="handleSearch" class="flex gap-1.5">
                        <input v-model="searchQuery" type="search" placeholder="Search wiki pages or aliases..."
                            class="flex-1 min-w-0 px-2.5 py-1.5 text-xs bg-stone-50 border border-stone-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-300" />
                        <button type="submit" :disabled="isBusy"
                            class="px-2.5 py-1.5 text-xs font-medium bg-stone-100 hover:bg-stone-200 text-slate-700 rounded-lg transition-colors">
                            Go
                        </button>
                        <button v-if="searchHits !== null" type="button" @click="clearSearch"
                            class="px-2 py-1.5 text-xs text-stone-500 hover:text-slate-800 rounded-lg transition-colors"
                            title="Clear search">
                            &times;
                        </button>
                    </form>

                    <div class="flex flex-wrap gap-1">
                        <button v-for="k in KIND_FILTERS" :key="k.id" type="button"
                            @click="selectedKind = k.id"
                            :class="selectedKind === k.id ? 'bg-slate-900 text-white' : 'bg-stone-100 text-stone-600 hover:bg-stone-200'"
                            class="px-2 py-1 rounded-md text-[11px] font-medium transition-colors">
                            {{ k.label }}
                        </button>
                    </div>

                    <div v-if="isLoading" class="py-8 text-center text-xs text-stone-400">Loading pages...</div>
                    <div v-else-if="filteredPages.length === 0" class="py-8 text-center text-xs text-stone-400">
                        <template v-if="searchHits !== null || selectedKind">No matching wiki pages.</template>
                        <template v-else>No wiki pages yet.</template>
                    </div>
                    <ul v-else class="divide-y divide-stone-100 max-h-[62vh] overflow-y-auto">
                        <li v-for="p in filteredPages" :key="p.slug">
                            <button type="button" @click="selectSlug(p.slug)"
                                :class="activePage?.slug === p.slug ? 'bg-stone-100/90' : 'hover:bg-stone-50'"
                                class="w-full text-left px-2.5 py-2 rounded-lg transition-colors">
                                <div class="flex items-center justify-between gap-2">
                                    <span class="text-xs font-semibold text-slate-900 truncate">{{ p.title }}</span>
                                    <span class="text-[10px] px-1.5 py-0.5 rounded bg-stone-100 text-stone-600 shrink-0">{{ formatPageKindLabel(p.page_kind) }}</span>
                                </div>
                                <div class="text-[11px] text-stone-500 truncate mt-0.5">{{ p.summary || p.slug }}</div>
                            </button>
                        </li>
                    </ul>
                </aside>

                <!-- Right Reader / Editor Pane -->
                <section class="lg:col-span-8 space-y-4">
                    <!-- Lint Triage Drawer -->
                    <div v-if="showLintPanel" class="bg-white border border-stone-200/80 rounded-xl p-4 shadow-sm space-y-2.5">
                        <div class="flex items-center justify-between">
                            <h3 class="text-xs font-semibold text-slate-900">Open Lint Issues ({{ lintIssues.length }})</h3>
                            <button type="button" @click="handleRunAction('lint')" :disabled="isBusy"
                                class="text-[11px] font-medium text-slate-600 hover:text-slate-900 disabled:opacity-50">
                                {{ runningAction === 'lint' ? 'Linting…' : 'Run Lint Now' }}
                            </button>
                        </div>
                        <div v-if="backfillRemaining > 0 && lintIssues.length > 0"
                            class="rounded-lg bg-stone-50 border border-stone-200/80 px-3 py-2 text-[11px] text-stone-600">
                            Backfill is still in progress ({{ backfillRemaining }} {{ backfillRemaining === 1 ? 'notebook' : 'notebooks' }} left). Orphan pages and unresolved links are normal until remaining notebooks are compiled.
                        </div>
                        <div v-if="lintIssues.length === 0" class="text-xs text-stone-500">All clear — zero open lint issues.</div>
                        <div v-for="issue in lintIssues" :key="issue.issue_id"
                            class="flex items-start justify-between gap-3 p-2.5 rounded-lg bg-stone-50 border border-stone-200/60">
                            <div class="min-w-0">
                                <span
                                    :class="issue.severity === 'info' ? 'text-stone-500' : issue.severity === 'error' ? 'text-red-700' : 'text-amber-700'"
                                    class="text-[10px] font-semibold uppercase tracking-wide">
                                    {{ issue.severity }} · {{ formatLintTypeLabel(issue.issue_type) }}
                                </span>
                                <p class="text-xs text-slate-700 mt-0.5 break-words">{{ issue.description }}</p>
                            </div>
                            <div class="flex items-center gap-1.5 shrink-0">
                                <button type="button" @click="handleResolveIssue(issue.issue_id, 'resolved')"
                                    class="px-2 py-1 text-[11px] rounded bg-emerald-50 text-emerald-700 hover:bg-emerald-100">Resolve</button>
                                <button type="button" @click="handleResolveIssue(issue.issue_id, 'dismissed')"
                                    class="px-2 py-1 text-[11px] rounded bg-stone-200/70 text-stone-700 hover:bg-stone-200">Dismiss</button>
                            </div>
                        </div>
                    </div>

                    <!-- Editor Form -->
                    <form v-if="isEditing" @submit.prevent="submitSave"
                        class="bg-white border border-stone-200/80 rounded-xl p-5 shadow-sm space-y-3">
                        <div class="flex items-center justify-between">
                            <h3 class="text-sm font-semibold text-slate-900">{{ isCreating ? 'Create Wiki Page' : 'Edit Wiki Page' }}</h3>
                            <button type="button" @click="cancelEdit" class="text-xs text-stone-500 hover:text-slate-900">Cancel</button>
                        </div>
                        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <label class="block">
                                <span class="text-[11px] font-medium text-stone-600">Slug</span>
                                <input v-model="editSlug" :disabled="!isCreating" required
                                    class="mt-1 w-full px-2.5 py-1.5 text-xs border border-stone-200 rounded-lg bg-stone-50 disabled:opacity-60" />
                            </label>
                            <label class="block">
                                <span class="text-[11px] font-medium text-stone-600">Kind</span>
                                <select v-model="editKind" class="mt-1 w-full px-2.5 py-1.5 text-xs border border-stone-200 rounded-lg bg-white">
                                    <option value="project">project</option>
                                    <option value="entity">entity</option>
                                    <option value="topic">topic</option>
                                    <option value="source_digest">source_digest</option>
                                    <option value="index">index</option>
                                    <option value="log">log</option>
                                </select>
                            </label>
                        </div>
                        <label class="block">
                            <span class="text-[11px] font-medium text-stone-600">Title</span>
                            <input v-model="editTitle" required
                                class="mt-1 w-full px-2.5 py-1.5 text-xs border border-stone-200 rounded-lg" />
                        </label>
                        <label class="block">
                            <span class="text-[11px] font-medium text-stone-600">Summary</span>
                            <input v-model="editSummary"
                                class="mt-1 w-full px-2.5 py-1.5 text-xs border border-stone-200 rounded-lg" />
                        </label>
                        <label class="block">
                            <span class="text-[11px] font-medium text-stone-600">Markdown Body (supports [[slug]] wikilinks)</span>
                            <textarea v-model="editBody" rows="12"
                                class="mt-1 w-full px-3 py-2 text-xs font-mono border border-stone-200 rounded-lg"></textarea>
                        </label>
                        <div class="flex justify-end gap-2">
                            <button type="button" @click="cancelEdit"
                                class="px-3 py-1.5 text-xs rounded-lg border border-stone-200 text-stone-600 hover:bg-stone-50">Cancel</button>
                            <button type="submit" :disabled="isBusy"
                                class="px-3.5 py-1.5 text-xs font-medium rounded-lg bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50">
                                Save Page
                            </button>
                        </div>
                    </form>

                    <!-- Reader Card -->
                    <article v-else-if="activePage"
                        class="bg-white border border-stone-200/80 rounded-xl p-5 shadow-sm space-y-4">
                        <div class="flex flex-wrap items-start justify-between gap-3 border-b border-stone-100 pb-3">
                            <div class="min-w-0">
                                <div class="flex flex-wrap items-center gap-2">
                                    <span class="text-[11px] font-medium px-2 py-0.5 rounded-full bg-stone-100 text-stone-700">{{ formatPageKindLabel(activePage.page_kind) }}</span>
                                    <span class="text-[11px] text-stone-400 font-mono break-all">{{ activePage.slug }}</span>
                                    <span class="text-[11px] text-stone-400">v{{ activePage.version }} · {{ activePage.edit_policy }}</span>
                                </div>
                                <h1 class="text-lg font-semibold text-slate-900 mt-1.5">{{ activePage.title }}</h1>
                                <p v-if="activePage.summary" class="text-xs text-stone-500 mt-0.5">{{ activePage.summary }}</p>
                            </div>
                            <div class="flex items-center gap-2">
                                <button type="button" @click="startEdit"
                                    class="px-2.5 py-1 text-xs font-medium rounded-lg border border-stone-200 text-slate-700 hover:bg-stone-50">
                                    Edit
                                </button>
                                <button v-if="confirmDeleteSlug !== activePage.slug" type="button"
                                    @click="confirmDeleteSlug = activePage.slug"
                                    class="px-2.5 py-1 text-xs font-medium rounded-lg border border-red-200 text-red-600 hover:bg-red-50">
                                    Delete
                                </button>
                                <button v-else type="button" @click="handleDeleteConfirmed" :disabled="isBusy"
                                    class="px-2.5 py-1 text-xs font-medium rounded-lg bg-red-600 text-white hover:bg-red-700">
                                    Confirm Delete
                                </button>
                            </div>
                        </div>

                        <div class="markdown-prose text-sm max-w-none text-slate-800" @click="handleBodyClick" v-html="renderedBodyHtml"></div>

                        <!-- Metadata Footer: Backlinks & Sources -->
                        <div v-if="activePage.backlinks.length || activePage.source_refs.length || activePage.aliases.length"
                            class="border-t border-stone-100 pt-3 grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                            <div v-if="activePage.backlinks.length">
                                <div class="text-[11px] font-semibold text-stone-500 uppercase tracking-wide mb-1">Backlinks</div>
                                <div class="flex flex-wrap gap-1.5">
                                    <button v-for="bl in activePage.backlinks" :key="bl" type="button"
                                        @click="selectSlug(bl)"
                                        class="px-2 py-0.5 rounded bg-stone-100 hover:bg-stone-200 text-slate-700 font-mono text-[11px]">
                                        {{ bl }}
                                    </button>
                                </div>
                            </div>
                            <div v-if="activePage.source_refs.length">
                                <div class="text-[11px] font-semibold text-stone-500 uppercase tracking-wide mb-1">Sources</div>
                                <div class="flex flex-wrap gap-1.5">
                                    <template v-for="ref in activePage.source_refs" :key="ref.source_type + ':' + ref.source_key">
                                        <button v-if="isSourceClickable(ref)" type="button"
                                            @click="handleOpenSource(ref)"
                                            :title="formatSourceRef(ref).tooltip"
                                            class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-stone-100 hover:bg-stone-200 text-slate-700 hover:text-slate-900 text-[11px] font-medium transition-colors max-w-full">
                                            <span class="truncate">{{ formatSourceRef(ref).label }}</span>
                                        </button>
                                        <span v-else
                                            :title="formatSourceRef(ref).tooltip"
                                            :class="ref.is_source_deleted ? 'bg-red-50 text-red-700 line-through' : 'bg-stone-100 text-stone-500'"
                                            class="px-2 py-0.5 rounded text-[11px] max-w-full truncate">
                                            {{ formatSourceRef(ref).label }}
                                        </span>
                                    </template>
                                </div>
                            </div>
                            <div v-if="activePage.aliases.length" class="sm:col-span-2">
                                <div class="text-[11px] font-semibold text-stone-500 uppercase tracking-wide mb-1">Aliases</div>
                                <div class="flex flex-wrap gap-1.5">
                                    <span v-for="alias in activePage.aliases" :key="alias"
                                        class="px-2 py-0.5 rounded bg-stone-100 text-stone-600 text-[11px]">
                                        {{ alias }}
                                    </span>
                                </div>
                            </div>
                        </div>
                    </article>

                    <div v-else-if="isLoading"
                        class="bg-white border border-stone-200/80 rounded-xl p-10 text-center text-xs text-stone-400">
                        Loading wiki...
                    </div>

                    <div v-else-if="pages.length === 0"
                        class="bg-white border border-stone-200/80 rounded-xl p-6 sm:p-8 space-y-4 shadow-sm">
                        <div class="text-center space-y-1.5">
                            <h3 class="text-sm font-semibold text-slate-900">Build your personal wiki</h3>
                            <p class="text-xs text-stone-500 max-w-lg mx-auto leading-relaxed">
                                <template v-if="backfillRemaining > 0">
                                    Compile your {{ backfillRemainingPages > 0 ? backfillRemainingPages + ' OCR’d pages across ' : '' }}{{ backfillRemaining }} {{ backfillRemaining === 1 ? 'notebook' : 'notebooks' }} chronologically in small page windows so projects, topics, and entities build cleanly over time.
                                </template>
                                <template v-else-if="backfillUntranscribed > 0">
                                    {{ backfillUntranscribed }} {{ backfillUntranscribed === 1 ? 'notebook does' : 'notebooks do' }} not have OCR transcripts yet. Process your notebooks with OCR first, then return here to build your wiki—or create a page manually.
                                </template>
                                <template v-else>
                                    No OCR’d notebooks found yet. Upload and transcribe a notebook in Files, or create a wiki page manually.
                                </template>
                            </p>
                        </div>

                        <!-- Queue preview right inside empty state so clicking Backfill is never a surprise -->
                        <div v-if="backfillNextFiles.length > 0"
                            class="max-w-lg mx-auto rounded-lg bg-stone-50 border border-stone-200/80 p-3 space-y-2">
                            <div class="flex items-center justify-between gap-2 text-[11px]">
                                <span class="font-medium text-slate-700">
                                    Up next ({{ backfillNextFiles.length }} earliest {{ backfillNextFiles.length === 1 ? 'notebook' : 'notebooks' }})
                                </span>
                                <span v-if="backfillUntranscribed > 0" class="text-stone-500">
                                    {{ backfillUntranscribed }} awaiting OCR
                                </span>
                            </div>
                            <div class="flex flex-wrap gap-1.5">
                                <span v-for="fname in backfillNextFiles" :key="fname"
                                    class="px-2 py-0.5 rounded-md bg-white border border-stone-200 text-stone-700 font-mono text-[11px] max-w-full truncate">
                                    {{ fname }}
                                </span>
                            </div>
                        </div>

                        <div class="flex flex-wrap items-center justify-center gap-2 pt-1">
                            <template v-if="backfillRemaining > 0">
                                <button type="button" @click="handleBackfill(true)" :disabled="isBusy"
                                    class="px-3.5 py-2 rounded-lg text-xs font-medium bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50 transition-colors">
                                    <template v-if="runningAction === 'backfill'">Backfilling…</template>
                                    <template v-else>Backfill All ({{ backfillRemaining }} {{ backfillRemaining === 1 ? 'notebook' : 'notebooks' }})</template>
                                </button>
                                <button v-if="backfillRemaining > nextBatchCount" type="button" @click="handleBackfill(false)" :disabled="isBusy"
                                    class="px-3.5 py-2 rounded-lg text-xs font-medium bg-white border border-stone-200 text-slate-700 hover:bg-stone-50 disabled:opacity-50 transition-colors">
                                    Backfill Next {{ nextBatchCount }}
                                </button>
                            </template>
                            <button type="button" @click="startCreate" :disabled="isBusy"
                                class="px-3.5 py-2 rounded-lg text-xs font-medium bg-white border border-stone-200 text-slate-700 hover:bg-stone-50 disabled:opacity-50 transition-colors">
                                Create Page Manually
                            </button>
                        </div>
                    </div>

                    <div v-else class="bg-white border border-stone-200/80 rounded-xl p-10 text-center text-xs text-stone-400">
                        Select a wiki page from the left or create a new page to get started.
                    </div>
                </section>
            </div>
        </div>
    `,
};
