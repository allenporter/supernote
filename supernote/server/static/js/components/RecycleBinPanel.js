/**
 * Recycle Bin panel for browsing, restoring, permanently deleting, and
 * emptying soft-deleted files and folders.
 */

import { computed, onMounted, ref, watch } from 'vue';
import { useModalEscape } from '../composables/useModalEscape.js';
import { showToast } from '../composables/useToast.js';
import { formatShortDate, formatSize, getErrorMessage } from '../utils/format.js';

/**
 * Compare two Recycle Bin items with folders grouped first and null timestamps last.
 * @param {Partial<RecycleItem>} a
 * @param {Partial<RecycleItem>} b
 * @param {'deletedAt' | 'name' | 'size' | string} sortBy
 * @param {'asc' | 'desc' | string} sortOrder
 * @returns {number}
 */
export function compareRecycleItems(a, b, sortBy, sortOrder) {
    const aIsFolder = Boolean(a.isDirectory);
    const bIsFolder = Boolean(b.isDirectory);
    if (aIsFolder !== bIsFolder) {
        return aIsFolder ? -1 : 1;
    }
    if (sortBy === 'deletedAt') {
        const tsA =
            typeof a.deletedAt === 'number' && Number.isFinite(a.deletedAt) ? a.deletedAt : null;
        const tsB =
            typeof b.deletedAt === 'number' && Number.isFinite(b.deletedAt) ? b.deletedAt : null;
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
        sensitivity: 'base',
    });
    return sortOrder === 'desc' ? -nameCmp : nameCmp;
}

export default {
    name: 'RecycleBinPanel',
    props: {
        items: {
            type: Array,
            default: () => [],
        },
        selectedIds: {
            type: Array,
            default: () => [],
        },
        isLoading: {
            type: Boolean,
            default: false,
        },
        isMutating: {
            type: Boolean,
            default: false,
        },
        error: {
            type: String,
            default: null,
        },
        loadRecycleBin: {
            type: Function,
            required: true,
        },
        restoreItems: {
            type: Function,
            required: true,
        },
        deleteItemsPermanently: {
            type: Function,
            required: true,
        },
        emptyRecycleBin: {
            type: Function,
            required: true,
        },
    },
    emits: ['close', 'update-selected-ids', 'restored'],
    /**
     * @param {{
     *   items: RecycleItem[],
     *   selectedIds: string[],
     *   isLoading: boolean,
     *   isMutating: boolean,
     *   error: string | null,
     *   loadRecycleBin: () => Promise<void>,
     *   restoreItems: (ids: string[]) => Promise<boolean>,
     *   deleteItemsPermanently: (ids: string[]) => Promise<boolean>,
     *   emptyRecycleBin: () => Promise<boolean>
     * }} props
     * @param {{ emit: (event: string, ...args: any[]) => void }} context
     */
    setup(props, { emit }) {
        const sortBy = ref('deletedAt');
        const sortOrder = ref('desc');

        /** @type {import('vue').Ref<string[]>} */
        const pendingDeleteIds = ref([]);
        const showEmptyModal = ref(false);
        /** @type {import('vue').Ref<HTMLButtonElement | null>} */
        const deleteCancelBtn = ref(null);
        /** @type {import('vue').Ref<HTMLButtonElement | null>} */
        const emptyCancelBtn = ref(null);

        const showDeleteModal = computed(() => pendingDeleteIds.value.length > 0);

        const sortedItems = computed(() =>
            [...props.items].sort((a, b) =>
                compareRecycleItems(a, b, sortBy.value, sortOrder.value),
            ),
        );

        const allSelected = computed(() => {
            if (sortedItems.value.length === 0) return false;
            const selectedSet = new Set(props.selectedIds);
            return sortedItems.value.every((item) => selectedSet.has(item.id));
        });

        /**
         * @param {string[]} ids
         */
        function setSelectedIds(ids) {
            emit('update-selected-ids', ids);
        }

        function clearSelection() {
            setSelectedIds([]);
        }

        /**
         * @param {string} id
         */
        function toggleSelection(id) {
            const next = [...props.selectedIds];
            const idx = next.indexOf(id);
            if (idx > -1) {
                next.splice(idx, 1);
            } else {
                next.push(id);
            }
            setSelectedIds(next);
        }

        function toggleSelectAll() {
            if (allSelected.value) {
                clearSelection();
            } else {
                setSelectedIds(sortedItems.value.map((item) => item.id));
            }
        }

        function handleSortByChange() {
            sortOrder.value = sortBy.value === 'name' ? 'asc' : 'desc';
        }

        function toggleSortOrder() {
            sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc';
        }

        /**
         * @param {string[]} ids
         */
        async function handleRestore(ids) {
            if (!ids.length || props.isMutating) return;
            try {
                const ok = await props.restoreItems(ids);
                if (!ok) return;
                emit('restored');
                const label = ids.length === 1 ? '1 item' : `${ids.length} items`;
                showToast(`Restored ${label}`, 'success');
            } catch (e) {
                showToast(getErrorMessage(e, 'Failed to restore items'), 'error');
            }
        }

        /**
         * @param {string[]} ids
         */
        function requestPermanentDelete(ids) {
            if (!ids.length || props.isMutating) return;
            pendingDeleteIds.value = [...ids];
        }

        function closeDeleteModal() {
            if (props.isMutating) return;
            pendingDeleteIds.value = [];
        }

        async function confirmPermanentDelete() {
            const ids = [...pendingDeleteIds.value];
            if (!ids.length || props.isMutating) return;
            try {
                const ok = await props.deleteItemsPermanently(ids);
                if (!ok) return;
                pendingDeleteIds.value = [];
                const label = ids.length === 1 ? '1 item' : `${ids.length} items`;
                showToast(`Permanently deleted ${label}`, 'success');
            } catch (e) {
                showToast(getErrorMessage(e, 'Failed to permanently delete items'), 'error');
            }
        }

        function openEmptyModal() {
            if (props.items.length === 0 || props.isMutating) return;
            showEmptyModal.value = true;
        }

        function closeEmptyModal() {
            if (props.isMutating) return;
            showEmptyModal.value = false;
        }

        async function confirmEmptyRecycleBin() {
            if (props.isMutating) return;
            try {
                const ok = await props.emptyRecycleBin();
                if (!ok) return;
                showEmptyModal.value = false;
                showToast('Recycle Bin emptied', 'success');
            } catch (e) {
                showToast(getErrorMessage(e, 'Failed to empty Recycle Bin'), 'error');
            }
        }

        watch(
            showDeleteModal,
            (isOpen) => {
                if (isOpen) {
                    deleteCancelBtn.value?.focus();
                }
            },
            { flush: 'post' },
        );

        watch(
            showEmptyModal,
            (isOpen) => {
                if (isOpen) {
                    emptyCancelBtn.value?.focus();
                }
            },
            { flush: 'post' },
        );

        useModalEscape(closeDeleteModal, showDeleteModal);
        useModalEscape(closeEmptyModal, showEmptyModal);

        onMounted(() => {
            props.loadRecycleBin();
        });

        return {
            sortBy,
            sortOrder,
            sortedItems,
            allSelected,
            pendingDeleteIds,
            showDeleteModal,
            showEmptyModal,
            deleteCancelBtn,
            emptyCancelBtn,
            formatShortDate,
            formatSize,
            clearSelection,
            toggleSelection,
            toggleSelectAll,
            handleSortByChange,
            toggleSortOrder,
            handleRestore,
            requestPermanentDelete,
            closeDeleteModal,
            confirmPermanentDelete,
            openEmptyModal,
            closeEmptyModal,
            confirmEmptyRecycleBin,
        };
    },
    template: `
    <div>
        <!-- Header Bar -->
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 mb-6 border-b border-stone-200/80">
            <div class="min-w-0">
                <div class="flex items-center gap-2.5 flex-wrap">
                    <button @click="$emit('close')" type="button"
                        class="flex items-center gap-1.5 text-xs font-semibold text-stone-600 hover:text-slate-900 bg-white hover:bg-stone-50 border border-stone-200/90 px-2.5 py-1.5 rounded-lg shadow-sm transition-colors">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path>
                        </svg>
                        <span>Files</span>
                    </button>
                    <h1 class="text-base sm:text-lg font-bold text-slate-900 tracking-tight flex items-center gap-2">
                        <span>Recycle Bin</span>
                        <span class="text-xs font-mono font-medium text-stone-500 bg-stone-200/60 px-2 py-0.5 rounded-md tabular-nums">
                            {{ items.length }}
                        </span>
                    </h1>
                </div>
                <p class="text-xs text-stone-500 mt-1.5">
                    Deleted items can be restored for up to 30 days before automatic permanent removal.
                </p>
            </div>

            <!-- Right Controls -->
            <div class="flex flex-wrap items-center gap-2 shrink-0">
                <div class="flex items-center bg-white border border-stone-200/90 rounded-lg p-0.5 shadow-sm">
                    <select v-model="sortBy" @change="handleSortByChange" aria-label="Sort recycle bin items by"
                        class="bg-transparent text-xs font-medium text-stone-600 hover:text-slate-900 pl-2.5 pr-1 py-1 outline-none cursor-pointer">
                        <option value="deletedAt">Sort: Deleted</option>
                        <option value="name">Sort: Name</option>
                        <option value="size">Sort: Size</option>
                    </select>
                    <button @click="toggleSortOrder" type="button"
                        :aria-label="sortOrder === 'asc' ? 'Sort ascending' : 'Sort descending'"
                        :title="sortOrder === 'asc' ? 'Ascending' : 'Descending'"
                        class="p-1 text-stone-600 hover:text-slate-900 rounded hover:bg-stone-100 transition-colors">
                        <svg v-if="sortOrder === 'asc'" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4h13M3 8h9m-9 4h6m4 0l4-4m0 0l4 4m-4-4v12"></path>
                        </svg>
                        <svg v-else class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4h13M3 8h9m-9 4h9m5-4v12m0 0l-4-4m4 4l4-4"></path>
                        </svg>
                    </button>
                </div>

                <button @click="openEmptyModal" type="button"
                    :disabled="items.length === 0 || isMutating"
                    class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all shadow-sm bg-white border-rose-200 text-rose-700 hover:bg-rose-50 disabled:opacity-40 disabled:cursor-not-allowed">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                    </svg>
                    <span>Empty Recycle Bin</span>
                </button>
            </div>
        </div>

        <!-- Contextual Multi-Select Action Bar -->
        <div v-if="selectedIds.length > 0"
            class="mb-6 px-4 py-2.5 bg-slate-900 text-white rounded-xl shadow-md flex flex-wrap items-center justify-between gap-3 animate-fade-in">
            <div class="flex items-center gap-3">
                <span class="text-xs font-mono font-semibold bg-white/15 px-2 py-0.5 rounded-md tabular-nums">
                    {{ selectedIds.length }} selected
                </span>
                <button @click="toggleSelectAll" type="button"
                    class="text-xs text-stone-300 hover:text-white font-medium transition-colors">
                    {{ allSelected ? 'Deselect all' : 'Select all (' + sortedItems.length + ')' }}
                </button>
            </div>
            <div class="flex items-center gap-2">
                <button @click="handleRestore(selectedIds)" :disabled="isMutating" type="button"
                    class="flex items-center gap-1.5 text-xs bg-white/10 hover:bg-white/20 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg font-medium transition-colors">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6"></path>
                    </svg>
                    <span>Restore</span>
                </button>
                <button @click="requestPermanentDelete(selectedIds)" :disabled="isMutating" type="button"
                    class="flex items-center gap-1.5 text-xs bg-rose-500/90 hover:bg-rose-500 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg font-medium transition-colors">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                    </svg>
                    <span>Delete Permanently</span>
                </button>
                <button @click="clearSelection" type="button"
                    class="text-xs text-stone-300 hover:text-white px-2 py-1">
                    Clear
                </button>
            </div>
        </div>

        <!-- Error State -->
        <div v-if="error" class="bg-rose-50 border border-rose-200 text-rose-700 px-4 py-3 rounded-xl text-xs mb-6 flex items-center justify-between gap-3">
            <span>{{ error }}</span>
            <button @click="loadRecycleBin()" type="button"
                class="px-2.5 py-1 bg-white hover:bg-rose-50 text-rose-700 border border-rose-200 rounded-lg font-semibold shrink-0 transition-colors">
                Retry
            </button>
        </div>

        <!-- Loading State -->
        <div v-if="isLoading && items.length === 0" class="flex flex-col items-center justify-center py-24 gap-3">
            <div class="animate-spin rounded-full h-8 w-8 border-2 border-stone-300 border-t-slate-900"></div>
            <span class="text-xs font-mono text-stone-500">Loading Recycle Bin...</span>
        </div>

        <!-- Empty State -->
        <div v-else-if="!error && sortedItems.length === 0"
            class="bg-white border border-stone-200/90 rounded-2xl p-12 text-center max-w-lg mx-auto my-8 shadow-sm">
            <div class="w-12 h-12 bg-stone-100 text-stone-500 rounded-xl flex items-center justify-center mx-auto mb-4">
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                </svg>
            </div>
            <h2 class="text-sm font-bold text-slate-900 mb-1">Recycle Bin is empty</h2>
            <p class="text-xs text-stone-500 mb-6">
                Files and folders you delete from your Supernote device or the Web UI will appear here for 30 days.
            </p>
            <button @click="$emit('close')" type="button"
                class="px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold transition-colors">
                Back to Files
            </button>
        </div>

        <!-- Recycle Bin Items List -->
        <div v-else class="bg-white rounded-2xl border border-stone-200/90 shadow-sm overflow-hidden">
            <!-- Header Row -->
            <div class="hidden sm:grid sm:grid-cols-12 gap-4 px-4 py-2.5 bg-stone-50/80 border-b border-stone-200/80 text-[11px] font-semibold uppercase tracking-wider text-stone-500 items-center">
                <div class="col-span-5 flex items-center gap-3">
                    <input type="checkbox" :checked="allSelected" @change="toggleSelectAll"
                        aria-label="Select all recycled items"
                        class="w-4 h-4 rounded border-stone-300 text-slate-900 focus:ring-slate-900 cursor-pointer">
                    <span>Name</span>
                </div>
                <div class="col-span-2">Deleted</div>
                <div class="col-span-2 text-right">Size</div>
                <div class="col-span-3 text-right pr-1">Actions</div>
            </div>

            <!-- Mobile Select-All Strip -->
            <div class="flex sm:hidden items-center justify-between px-4 py-2.5 bg-stone-50/80 border-b border-stone-200/80 text-[11px] font-semibold uppercase tracking-wider text-stone-500">
                <label class="flex items-center gap-2.5 cursor-pointer">
                    <input type="checkbox" :checked="allSelected" @change="toggleSelectAll"
                        aria-label="Select all recycled items"
                        class="w-4 h-4 rounded border-stone-300 text-slate-900 focus:ring-slate-900 cursor-pointer">
                    <span>Select all ({{ sortedItems.length }})</span>
                </label>
            </div>

            <!-- Rows -->
            <div class="divide-y divide-stone-100">
                <div v-for="item in sortedItems" :key="item.id"
                    :class="selectedIds.includes(item.id) ? 'bg-stone-50/90' : 'hover:bg-stone-50/60'"
                    class="recycle-row group flex items-center justify-between sm:grid sm:grid-cols-12 gap-3 sm:gap-4 px-4 py-3 transition-colors">
                    <!-- Checkbox + Icon + Name -->
                    <div class="flex items-center gap-3 min-w-0 flex-1 sm:col-span-5">
                        <input type="checkbox"
                            :checked="selectedIds.includes(item.id)"
                            @change="toggleSelection(item.id)"
                            :aria-label="'Select ' + item.name"
                            class="w-4 h-4 rounded border-stone-300 text-slate-900 focus:ring-slate-900 shrink-0 cursor-pointer">
                        <div class="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                            :class="item.isDirectory ? 'bg-amber-50 text-amber-600' : 'bg-stone-100 text-stone-600'">
                            <svg v-if="item.isDirectory" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.75" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"></path>
                            </svg>
                            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.75" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                            </svg>
                        </div>
                        <div class="min-w-0 flex-1">
                            <div class="text-sm font-medium text-slate-900 truncate" :title="item.name">
                                {{ item.name }}
                            </div>
                            <!-- Mobile metadata subtitle -->
                            <div class="flex sm:hidden items-center gap-2 text-[11px] text-stone-500 mt-0.5">
                                <span>{{ formatShortDate(item.deletedAt) || '—' }}</span>
                                <span v-if="!item.isDirectory && item.size > 0">· {{ formatSize(item.size) }}</span>
                            </div>
                        </div>
                    </div>

                    <!-- Desktop Deleted Date -->
                    <div class="hidden sm:block sm:col-span-2 text-xs text-stone-500 truncate">
                        {{ formatShortDate(item.deletedAt) || '—' }}
                    </div>

                    <!-- Desktop Size -->
                    <div class="hidden sm:block sm:col-span-2 text-right text-xs font-mono text-stone-500 tabular-nums">
                        {{ item.isDirectory ? '—' : (formatSize(item.size) || '0 B') }}
                    </div>

                    <!-- Row Actions -->
                    <div class="flex items-center justify-end gap-1.5 sm:col-span-3 shrink-0">
                        <button @click="handleRestore([item.id])" :disabled="isMutating" type="button"
                            :aria-label="'Restore ' + item.name"
                            title="Restore"
                            class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold text-slate-700 bg-stone-100 hover:bg-stone-200/80 disabled:opacity-40 transition-colors">
                            <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6"></path>
                            </svg>
                            <span class="hidden md:inline">Restore</span>
                        </button>
                        <button @click="requestPermanentDelete([item.id])" :disabled="isMutating" type="button"
                            :aria-label="'Delete ' + item.name + ' permanently'"
                            title="Delete Permanently"
                            class="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold text-rose-700 bg-rose-50 hover:bg-rose-100 disabled:opacity-40 transition-colors">
                            <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                            </svg>
                            <span class="hidden lg:inline">Delete</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Permanent Delete Confirmation Modal -->
        <div v-if="showDeleteModal"
            role="dialog" aria-modal="true" aria-label="Confirm Permanent Delete"
            class="fixed inset-0 z-[110] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px]"
            @click.self="closeDeleteModal">
            <div class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-sm p-6 animate-fade-in">
                <div class="w-10 h-10 rounded-xl bg-rose-50 text-rose-600 flex items-center justify-center mb-3">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                    </svg>
                </div>
                <h3 class="text-base font-bold text-slate-900 mb-1">
                    Permanently delete {{ pendingDeleteIds.length }} {{ pendingDeleteIds.length === 1 ? 'item' : 'items' }}?
                </h3>
                <p class="text-xs text-stone-500 mb-5 leading-relaxed">
                    This action cannot be undone. The selected {{ pendingDeleteIds.length === 1 ? 'item' : 'items' }} will be permanently removed from your Supernote Cloud.
                </p>
                <div class="flex justify-end gap-2.5">
                    <button ref="deleteCancelBtn" @click="closeDeleteModal" :disabled="isMutating" type="button"
                        class="px-4 py-2 text-xs text-stone-600 hover:text-slate-900 font-semibold rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 disabled:opacity-40">
                        Cancel
                    </button>
                    <button @click="confirmPermanentDelete" :disabled="isMutating" type="button"
                        class="px-5 py-2 bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white rounded-xl text-xs font-semibold transition-all">
                        {{ isMutating ? 'Deleting...' : 'Delete Permanently' }}
                    </button>
                </div>
            </div>
        </div>

        <!-- Empty Recycle Bin Confirmation Modal -->
        <div v-if="showEmptyModal"
            role="dialog" aria-modal="true" aria-label="Confirm Empty Recycle Bin"
            class="fixed inset-0 z-[110] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px]"
            @click.self="closeEmptyModal">
            <div class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-sm p-6 animate-fade-in">
                <div class="w-10 h-10 rounded-xl bg-rose-50 text-rose-600 flex items-center justify-center mb-3">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
                    </svg>
                </div>
                <h3 class="text-base font-bold text-slate-900 mb-1">
                    Empty Recycle Bin?
                </h3>
                <p class="text-xs text-stone-500 mb-5 leading-relaxed">
                    This action cannot be undone. {{ items.length === 1 ? 'The 1 item' : 'All ' + items.length + ' items' }} in the Recycle Bin will be permanently deleted.
                </p>
                <div class="flex justify-end gap-2.5">
                    <button ref="emptyCancelBtn" @click="closeEmptyModal" :disabled="isMutating" type="button"
                        class="px-4 py-2 text-xs text-stone-600 hover:text-slate-900 font-semibold rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 disabled:opacity-40">
                        Cancel
                    </button>
                    <button @click="confirmEmptyRecycleBin" :disabled="isMutating" type="button"
                        class="px-5 py-2 bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white rounded-xl text-xs font-semibold transition-all">
                        {{ isMutating ? 'Emptying...' : 'Empty Recycle Bin' }}
                    </button>
                </div>
            </div>
        </div>
    </div>
    `,
};
