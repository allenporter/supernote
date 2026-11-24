/**
 * LLM Wiki browser, Markdown viewer, inline editor, lint triage, and Obsidian export panel.
 */

import { computed, onMounted, ref, watch } from 'vue';
import { ApiError } from '../api/http.js';
import {
    deleteWikiPage,
    downloadWikiVaultZip,
    fetchWikiLintIssues,
    fetchWikiPage,
    fetchWikiPages,
    fetchWikiStatus,
    resolveWikiLintIssue,
    saveWikiPage,
    searchWikiPages,
    triggerWikiCompile,
} from '../api/wiki.js';
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
    emits: ['select-slug'],
    /**
     * @param {{ initialSlug: string }} props
     * @param {{ emit: (event: 'select-slug', slug: string, replace?: boolean) => void }} ctx
     */
    setup(props, { emit }) {
        const { showToast } = useToast();

        const isLoading = ref(true);
        const isDisabled = ref(false);
        const isBusy = ref(false);
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

        const filteredPages = computed(() => {
            const source = searchHits.value !== null ? searchHits.value : pages.value;
            if (!selectedKind.value) return source;
            return source.filter((p) => p.page_kind === selectedKind.value);
        });

        const renderedBodyHtml = computed(() =>
            activePage.value ? renderWikiMarkdown(activePage.value.body_md) : '',
        );

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
                if (activePage.value && typeof conflictData?.actual === 'number') {
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
            isBusy.value = true;
            try {
                await deleteWikiPage(confirmDeleteSlug.value);
                confirmDeleteSlug.value = '';
                activePage.value = null;
                showToast('Wiki page deleted', 'success');
                await loadAll();
            } catch (err) {
                showToast(getErrorMessage(err), 'error');
            } finally {
                isBusy.value = false;
            }
        }

        /**
         * @param {'incremental' | 'backfill' | 'lint'} mode
         */
        async function handleRunAction(mode) {
            isBusy.value = true;
            try {
                await triggerWikiCompile(mode);
                showToast(`Wiki ${mode} completed`, 'success');
                await loadAll(activePage.value?.slug || '');
            } catch (err) {
                showToast(getErrorMessage(err), 'error');
            } finally {
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

        return {
            KIND_FILTERS,
            isLoading,
            isDisabled,
            isBusy,
            error,
            pages,
            searchHits,
            filteredPages,
            activePage,
            status,
            lintIssues,
            selectedKind,
            searchQuery,
            clearSearch,
            showLintPanel,
            isEditing,
            isCreating,
            confirmDeleteSlug,
            editSlug,
            editTitle,
            editKind,
            editSummary,
            editBody,
            renderedBodyHtml,
            selectSlug,
            handleSearch,
            startCreate,
            startEdit,
            cancelEdit,
            submitSave,
            handleDeleteConfirmed,
            handleRunAction,
            handleResolveIssue,
            handleExportZip,
            handleBodyClick,
        };
    },
    template: `
        <div class="space-y-4">
            <!-- Header Bar -->
            <div class="flex flex-wrap items-center justify-between gap-3 bg-white border border-stone-200/80 rounded-xl p-4 shadow-sm">
                <div>
                    <h2 class="text-base font-semibold text-slate-900">LLM Wiki</h2>
                    <p class="text-xs text-stone-500 mt-0.5">
                        <template v-if="status">
                            {{ status.page_count }} pages · {{ status.open_lint_count }} lint issues · status: {{ status.status }}
                        </template>
                        <template v-else>Compiled knowledge base from notebooks &amp; tasks</template>
                    </p>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                    <button type="button" @click="startCreate" :disabled="isDisabled || isBusy"
                        class="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50 transition-colors">
                        New Page
                    </button>
                    <button type="button" @click="handleRunAction('incremental')" :disabled="isDisabled || isBusy"
                        class="px-3 py-1.5 rounded-lg text-xs font-medium bg-white border border-stone-200 text-slate-700 hover:bg-stone-50 disabled:opacity-50 transition-colors">
                        Compile Diffs
                    </button>
                    <button type="button" @click="showLintPanel = !showLintPanel" :disabled="isDisabled"
                        class="px-3 py-1.5 rounded-lg text-xs font-medium bg-white border border-stone-200 text-slate-700 hover:bg-stone-50 transition-colors">
                        Lint ({{ lintIssues.length }})
                    </button>
                    <button type="button" @click="handleExportZip" :disabled="isDisabled || pages.length === 0"
                        class="px-3 py-1.5 rounded-lg text-xs font-medium bg-white border border-stone-200 text-slate-700 hover:bg-stone-50 disabled:opacity-50 transition-colors">
                        Export Obsidian .zip
                    </button>
                </div>
            </div>

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
                        No wiki pages yet. Click <strong>New Page</strong> or <strong>Compile Diffs</strong>.
                    </div>
                    <ul v-else class="divide-y divide-stone-100 max-h-[62vh] overflow-y-auto">
                        <li v-for="p in filteredPages" :key="p.slug">
                            <button type="button" @click="selectSlug(p.slug)"
                                :class="activePage?.slug === p.slug ? 'bg-stone-100/90' : 'hover:bg-stone-50'"
                                class="w-full text-left px-2.5 py-2 rounded-lg transition-colors">
                                <div class="flex items-center justify-between gap-2">
                                    <span class="text-xs font-semibold text-slate-900 truncate">{{ p.title }}</span>
                                    <span class="text-[10px] px-1.5 py-0.5 rounded bg-stone-100 text-stone-600 shrink-0">{{ p.page_kind }}</span>
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
                                class="text-[11px] font-medium text-slate-600 hover:text-slate-900">
                                Run Lint Now
                            </button>
                        </div>
                        <div v-if="lintIssues.length === 0" class="text-xs text-stone-500">All clear — zero open lint issues.</div>
                        <div v-for="issue in lintIssues" :key="issue.issue_id"
                            class="flex items-start justify-between gap-3 p-2.5 rounded-lg bg-stone-50 border border-stone-200/60">
                            <div class="min-w-0">
                                <span class="text-[10px] font-semibold uppercase tracking-wide text-amber-700">{{ issue.issue_type }}</span>
                                <p class="text-xs text-slate-700 mt-0.5">{{ issue.description }}</p>
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
                            <div>
                                <div class="flex items-center gap-2">
                                    <span class="text-[11px] font-medium px-2 py-0.5 rounded-full bg-stone-100 text-stone-700">{{ activePage.page_kind }}</span>
                                    <span class="text-[11px] text-stone-400 font-mono">{{ activePage.slug }}</span>
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
                                    <span v-for="ref in activePage.source_refs" :key="ref.source_type + ':' + ref.source_key"
                                        :class="ref.is_source_deleted ? 'bg-red-50 text-red-700 line-through' : 'bg-stone-100 text-stone-700'"
                                        class="px-2 py-0.5 rounded font-mono text-[11px]">
                                        {{ ref.source_type }}:{{ ref.source_key }}
                                    </span>
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

                    <div v-else class="bg-white border border-stone-200/80 rounded-xl p-10 text-center text-xs text-stone-400">
                        Select a wiki page from the left or create a new page to get started.
                    </div>
                </section>
            </div>
        </div>
    `,
};
