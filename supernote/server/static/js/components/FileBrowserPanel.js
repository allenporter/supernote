/**
 * Files & Notebooks directory browser panel.
 *
 * Owns directory view presentation (Grid / List toggle, sorting, pagination),
 * multi-select batch toolbar, drag-and-drop upload overlay, and folder/file
 * action modals (Create Folder, Delete confirmation, Move, and Rename), while
 * delegating Host UI routing and VFS API persistence to parent props/events.
 */

import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { onLogout } from '../api/http.js';
import { useModalEscape } from '../composables/useModalEscape.js';
import { showToast } from '../composables/useToast.js';
import { getErrorMessage, normalizeEpochMs } from '../utils/format.js';
import FileCard from './FileCard.js';
import MoveModal from './MoveModal.js';
import RenameModal from './RenameModal.js';

const GRID_PAGE_SIZE = 50;

// Persist user's chosen layout and sort mode across viewer / tab switches within the session
const sharedDisplayMode = ref('grid'); // 'grid' | 'list'
const sharedSortBy = ref('name'); // 'name' | 'updatedAt' | 'size'
const sharedSortOrder = ref('asc'); // 'asc' | 'desc'

onLogout(() => {
    sharedDisplayMode.value = 'grid';
    sharedSortBy.value = 'name';
    sharedSortOrder.value = 'asc';
});

/**
 * Compare two VFS items, keeping folders grouped before regular files.
 * @param {Partial<FileItem>} a
 * @param {Partial<FileItem>} b
 * @param {'name' | 'updatedAt' | 'size' | string} sortBy
 * @param {'asc' | 'desc' | string} sortOrder
 * @returns {number}
 */
export function compareItems(a, b, sortBy, sortOrder) {
    const aIsFolder = Boolean(a.isDirectory);
    const bIsFolder = Boolean(b.isDirectory);
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
        sensitivity: 'base',
    });
    return sortOrder === 'desc' ? -nameCmp : nameCmp;
}

export default {
    name: 'FileBrowserPanel',
    components: {
        FileCard,
        MoveModal,
        RenameModal,
    },
    props: {
        files: {
            type: Array,
            default: () => [],
        },
        currentDirectoryId: {
            type: String,
            default: '0',
        },
        breadcrumbs: {
            type: Array,
            default: () => [{ id: '0', name: 'Cloud' }],
        },
        isLoading: {
            type: Boolean,
            default: false,
        },
        error: {
            type: String,
            default: null,
        },
        processingStatuses: {
            type: Object,
            default: () => ({}),
        },
        selectedIds: {
            type: Array,
            default: () => [],
        },
        createFolder: {
            type: Function,
            required: true,
        },
        uploadFiles: {
            type: Function,
            required: true,
        },
        deleteItems: {
            type: Function,
            required: true,
        },
        moveItems: {
            type: Function,
            required: true,
        },
        renameItem: {
            type: Function,
            required: true,
        },
    },
    emits: ['open-item', 'navigate-to', 'update-selected-ids', 'open-recycle-bin'],
    /**
     * @param {{
     *   files: FileItem[],
     *   currentDirectoryId: string,
     *   breadcrumbs: BreadcrumbItem[],
     *   isLoading: boolean,
     *   error: string | null,
     *   processingStatuses: Record<string, string>,
     *   selectedIds: string[],
     *   createFolder: (name: string) => Promise<any>,
     *   uploadFiles: (files: FileList | File[]) => Promise<any>,
     *   deleteItems: (ids: string[]) => Promise<any>,
     *   moveItems: (ids: string[], targetDirId: string) => Promise<any>,
     *   renameItem: (id: string | number, newName: string) => Promise<any>
     * }} props
     * @param {{ emit: (event: string, ...args: any[]) => void }} context
     */
    setup(props, { emit }) {
        const displayMode = sharedDisplayMode;
        const sortBy = sharedSortBy;
        const sortOrder = sharedSortOrder;

        const isDraggingOver = ref(false);
        const visibleLimit = ref(GRID_PAGE_SIZE);

        const showNewFolderModal = ref(false);
        const newFolderName = ref('');
        const isCreatingFolder = ref(false);
        /** @type {import('vue').Ref<HTMLInputElement | null>} */
        const newFolderInput = ref(null);
        const showMoveModal = ref(false);
        const isMovingItems = ref(false);
        const showRenameModal = ref(false);
        const isRenamingItem = ref(false);
        const showDeleteModal = ref(false);
        const isDeletingItems = ref(false);
        /** @type {import('vue').Ref<HTMLButtonElement | null>} */
        const deleteCancelBtn = ref(null);
        /** @type {import('vue').Ref<FileItem | null>} */
        const itemToRename = ref(null);
        /** @type {import('vue').Ref<HTMLInputElement | null>} */
        const fileInput = ref(null);

        /**
         * @param {string[]} ids
         */
        function setSelectedIds(ids) {
            emit('update-selected-ids', ids);
        }

        function clearSelection() {
            setSelectedIds([]);
        }

        watch(
            () => props.currentDirectoryId,
            () => {
                visibleLimit.value = GRID_PAGE_SIZE;
                isDraggingOver.value = false;
            },
        );

        watch(showNewFolderModal, (isOpen) => {
            if (isOpen) {
                nextTick(() => newFolderInput.value?.focus());
            } else {
                newFolderName.value = '';
            }
        });

        watch(showDeleteModal, (isOpen) => {
            if (isOpen) {
                nextTick(() => deleteCancelBtn.value?.focus());
            }
        });

        const allFolders = computed(() => {
            const list = props.files.filter((f) => f.isDirectory);
            return [...list].sort((a, b) => compareItems(a, b, sortBy.value, sortOrder.value));
        });

        const allRegularFiles = computed(() => {
            const list = props.files.filter((f) => !f.isDirectory);
            return [...list].sort((a, b) => compareItems(a, b, sortBy.value, sortOrder.value));
        });

        const folders = computed(() => allFolders.value.slice(0, visibleLimit.value));
        const regularFiles = computed(() => {
            const remaining = Math.max(0, visibleLimit.value - folders.value.length);
            return allRegularFiles.value.slice(0, remaining);
        });

        const totalItemCount = computed(() => props.files.length);
        const visibleItemCount = computed(() => folders.value.length + regularFiles.value.length);
        const hasMoreItems = computed(() => visibleItemCount.value < totalItemCount.value);

        function loadMoreItems() {
            visibleLimit.value += GRID_PAGE_SIZE;
        }

        function handleSortByChange() {
            sortOrder.value =
                sortBy.value === 'updatedAt' || sortBy.value === 'size' ? 'desc' : 'asc';
        }

        function toggleSortOrder() {
            sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc';
        }

        watch([sortBy, sortOrder], () => {
            if (hasMoreItems.value && props.selectedIds.length > 0) {
                const visibleSet = new Set([
                    ...folders.value.map((f) => f.id),
                    ...regularFiles.value.map((f) => f.id),
                ]);
                setSelectedIds(props.selectedIds.filter((id) => visibleSet.has(id)));
            }
        });

        const visibleIdsList = computed(() => [
            ...folders.value.map((f) => f.id),
            ...regularFiles.value.map((f) => f.id),
        ]);

        const allVisibleSelected = computed(() => {
            const ids = visibleIdsList.value;
            if (ids.length === 0) return false;
            const selectedSet = new Set(props.selectedIds);
            return ids.every((id) => selectedSet.has(id));
        });

        /**
         * @param {string} id
         */
        function toggleSelection(id) {
            const next = [...props.selectedIds];
            const index = next.indexOf(id);
            if (index > -1) {
                next.splice(index, 1);
            } else {
                next.push(id);
            }
            setSelectedIds(next);
        }

        function toggleSelectAllVisible() {
            if (allVisibleSelected.value) {
                clearSelection();
            } else {
                setSelectedIds([...visibleIdsList.value]);
            }
        }

        async function handleCreateFolder() {
            const trimmed = newFolderName.value.trim();
            if (!trimmed || isCreatingFolder.value) return;
            isCreatingFolder.value = true;
            try {
                await props.createFolder(trimmed);
                showNewFolderModal.value = false;
                newFolderName.value = '';
                showToast('Folder created', 'success');
            } catch (e) {
                showToast(`Failed to create folder: ${getErrorMessage(e)}`);
            } finally {
                isCreatingFolder.value = false;
            }
        }

        function triggerUpload() {
            fileInput.value?.click();
        }

        /**
         * @param {Event & { target: HTMLInputElement }} event
         */
        async function handleFileUpload(event) {
            const selectedFiles = event.target.files;
            if (!selectedFiles || selectedFiles.length === 0) return;
            try {
                await props.uploadFiles(selectedFiles);
                showToast(
                    `Uploaded ${selectedFiles.length} ${selectedFiles.length === 1 ? 'file' : 'files'}`,
                    'success',
                );
            } catch (e) {
                showToast(`Upload failed: ${getErrorMessage(e)}`);
            } finally {
                event.target.value = '';
            }
        }

        /**
         * @param {DragEvent} event
         */
        function isFileDragEvent(event) {
            const types = event?.dataTransfer?.types;
            return Boolean(types && Array.from(types).includes('Files'));
        }

        /**
         * @param {DragEvent} event
         */
        function handleDragOver(event) {
            if (!isFileDragEvent(event)) return;
            event.preventDefault();
            isDraggingOver.value = true;
        }

        /**
         * @param {DragEvent & { currentTarget: HTMLElement, relatedTarget: Node | null }} event
         */
        function handleDragLeave(event) {
            if (!isDraggingOver.value) return;
            if (!event.currentTarget.contains(event.relatedTarget)) {
                isDraggingOver.value = false;
            }
        }

        /**
         * @param {DragEvent} event
         */
        async function handleDrop(event) {
            isDraggingOver.value = false;
            if (!isFileDragEvent(event)) return;
            event.preventDefault();
            const droppedFiles = event.dataTransfer?.files;
            if (!droppedFiles || droppedFiles.length === 0) return;
            try {
                await props.uploadFiles(droppedFiles);
                showToast(
                    `Uploaded ${droppedFiles.length} ${droppedFiles.length === 1 ? 'file' : 'files'}`,
                    'success',
                );
            } catch (e) {
                showToast(`Upload failed: ${getErrorMessage(e)}`);
            }
        }

        function handleDeleteSelected() {
            if (props.selectedIds.length === 0) return;
            showDeleteModal.value = true;
        }

        async function confirmDeleteSelected() {
            if (isDeletingItems.value) return;
            const idsToDelete = [...props.selectedIds];
            const count = idsToDelete.length;
            if (count === 0) {
                showDeleteModal.value = false;
                return;
            }
            isDeletingItems.value = true;
            try {
                await props.deleteItems(idsToDelete);
                clearSelection();
                showDeleteModal.value = false;
                showToast(`Deleted ${count} ${count === 1 ? 'item' : 'items'}`, 'success');
            } catch (e) {
                showToast(`Delete failed: ${getErrorMessage(e)}`);
            } finally {
                isDeletingItems.value = false;
            }
        }

        function handleMoveSelected() {
            showMoveModal.value = true;
        }

        /**
         * @param {string} targetDirId
         */
        async function onConfirmMove(targetDirId) {
            if (isMovingItems.value) return;
            isMovingItems.value = true;
            try {
                await props.moveItems(props.selectedIds, targetDirId);
                clearSelection();
                showMoveModal.value = false;
                showToast('Moved successfully', 'success');
            } catch (e) {
                showToast(`Move failed: ${getErrorMessage(e)}`);
            } finally {
                isMovingItems.value = false;
            }
        }

        /**
         * @param {FileItem} item
         */
        function triggerRename(item) {
            itemToRename.value = item;
            showRenameModal.value = true;
        }

        /**
         * @param {string} newName
         */
        async function onConfirmRename(newName) {
            if (!itemToRename.value || isRenamingItem.value) return;
            isRenamingItem.value = true;
            try {
                await props.renameItem(itemToRename.value.id, newName);
                showRenameModal.value = false;
                itemToRename.value = null;
                showToast('Renamed successfully', 'success');
            } catch (e) {
                showToast(`Rename failed: ${getErrorMessage(e)}`);
            } finally {
                isRenamingItem.value = false;
            }
        }

        const clearDragState = () => {
            isDraggingOver.value = false;
        };

        useModalEscape(clearDragState, isDraggingOver);

        useModalEscape(() => {
            if (!isCreatingFolder.value) showNewFolderModal.value = false;
        }, showNewFolderModal);

        useModalEscape(() => {
            if (!isDeletingItems.value) showDeleteModal.value = false;
        }, showDeleteModal);

        onMounted(() => {
            window.addEventListener('dragend', clearDragState);
            window.addEventListener('drop', clearDragState);
        });

        onUnmounted(() => {
            window.removeEventListener('dragend', clearDragState);
            window.removeEventListener('drop', clearDragState);
        });

        return {
            displayMode,
            sortBy,
            sortOrder,
            handleSortByChange,
            toggleSortOrder,
            isDraggingOver,
            handleDragOver,
            handleDragLeave,
            handleDrop,
            allFolders,
            allRegularFiles,
            folders,
            regularFiles,
            totalItemCount,
            visibleItemCount,
            hasMoreItems,
            loadMoreItems,
            allVisibleSelected,
            toggleSelection,
            toggleSelectAllVisible,
            clearSelection,
            showNewFolderModal,
            newFolderName,
            isCreatingFolder,
            newFolderInput,
            showMoveModal,
            isMovingItems,
            showRenameModal,
            isRenamingItem,
            showDeleteModal,
            isDeletingItems,
            deleteCancelBtn,
            itemToRename,
            fileInput,
            handleCreateFolder,
            triggerUpload,
            handleFileUpload,
            handleDeleteSelected,
            confirmDeleteSelected,
            handleMoveSelected,
            onConfirmMove,
            triggerRename,
            onConfirmRename,
        };
    },
    template: `
    <div @dragover="handleDragOver" @dragleave="handleDragLeave" @drop="handleDrop" class="relative">
        <!-- Drag-and-Drop Upload Overlay -->
        <div v-if="isDraggingOver"
            class="fixed inset-4 z-40 rounded-2xl bg-slate-900/10 backdrop-blur-[2px] border-2 border-dashed border-slate-900 flex items-center justify-center pointer-events-none">
            <div class="bg-white px-6 py-4 rounded-2xl shadow-xl border border-stone-200 flex items-center gap-3">
                <svg class="w-6 h-6 text-slate-900" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path>
                </svg>
                <span class="text-sm font-semibold text-slate-900">Drop files to upload to {{ breadcrumbs[breadcrumbs.length - 1]?.name || 'Cloud' }}</span>
            </div>
        </div>

        <!-- Unified Directory Header Bar: Breadcrumbs + Controls -->
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 mb-6 border-b border-stone-200/80">
            <!-- Breadcrumb Path -->
            <nav class="flex items-center text-sm overflow-x-auto whitespace-nowrap min-w-0" aria-label="Breadcrumb">
                <div v-for="(crumb, index) in breadcrumbs" :key="crumb.id" class="flex items-center">
                    <button @click="$emit('navigate-to', index)" type="button"
                        :class="index === breadcrumbs.length - 1
                            ? 'text-slate-900 font-bold bg-stone-200/60 px-2.5 py-1 rounded-lg'
                            : 'text-stone-600 hover:text-slate-900 hover:bg-stone-200/40 px-2 py-1 rounded-lg font-medium transition-colors'"
                        class="flex items-center gap-1.5 text-sm">
                        <svg v-if="index === 0" class="w-4 h-4 text-stone-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6">
                            </path>
                        </svg>
                        <span>{{ crumb.name }}</span>
                    </button>
                    <svg v-if="index < breadcrumbs.length - 1" class="w-4 h-4 mx-1 text-stone-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                    </svg>
                </div>
            </nav>

            <!-- Right Controls: Sort, View Mode, New Folder, Upload -->
            <div class="flex flex-wrap items-center gap-2 shrink-0">
                <!-- Sort Control -->
                <div class="flex items-center bg-white border border-stone-200/90 rounded-lg p-0.5 shadow-sm">
                    <select v-model="sortBy" @change="handleSortByChange" aria-label="Sort files by"
                        class="bg-transparent text-xs font-medium text-stone-600 hover:text-slate-900 pl-2.5 pr-1 py-1 outline-none cursor-pointer">
                        <option value="name">Sort: Name</option>
                        <option value="updatedAt">Sort: Modified</option>
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

                <!-- Grid / List View Switcher -->
                <div class="flex items-center bg-white border border-stone-200/90 rounded-lg p-0.5 shadow-sm">
                    <button @click="displayMode = 'grid'" type="button"
                        aria-label="Grid view"
                        :class="displayMode === 'grid' ? 'bg-stone-200/80 text-slate-900' : 'text-stone-500 hover:text-slate-800'"
                        class="p-1.5 rounded-md transition-colors" title="Grid view">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"></path>
                        </svg>
                    </button>
                    <button @click="displayMode = 'list'" type="button"
                        aria-label="List view"
                        :class="displayMode === 'list' ? 'bg-stone-200/80 text-slate-900' : 'text-stone-500 hover:text-slate-800'"
                        class="p-1.5 rounded-md transition-colors" title="List view">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path>
                        </svg>
                    </button>
                </div>

                <!-- Recycle Bin Button -->
                <button @click="$emit('open-recycle-bin')" type="button"
                    aria-label="Recycle Bin"
                    title="Recycle Bin"
                    class="flex items-center gap-1.5 bg-white hover:bg-stone-50 text-stone-600 hover:text-slate-900 border border-stone-200/90 px-2.5 py-1.5 rounded-lg text-xs font-semibold shadow-sm transition-all">
                    <svg class="w-3.5 h-3.5 text-stone-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                    </svg>
                    <span class="hidden lg:inline">Recycle Bin</span>
                </button>

                <!-- New Folder Button -->
                <button @click="showNewFolderModal = true" type="button"
                    class="flex items-center gap-1.5 bg-white hover:bg-stone-50 text-slate-700 border border-stone-200/90 px-3 py-1.5 rounded-lg text-xs font-semibold shadow-sm transition-all">
                    <svg class="w-3.5 h-3.5 text-stone-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
                    </svg>
                    New Folder
                </button>

                <!-- Primary Upload CTA -->
                <button @click="triggerUpload" type="button"
                    class="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-white px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all shadow-sm">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path>
                    </svg>
                    Upload
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
                <button @click="toggleSelectAllVisible" type="button"
                    class="text-xs text-stone-300 hover:text-white font-medium transition-colors">
                    {{ allVisibleSelected ? 'Deselect all' : 'Select all (' + visibleItemCount + ')' }}
                </button>
            </div>
            <div class="flex items-center gap-2">
                <button @click="handleMoveSelected" type="button"
                    class="flex items-center gap-1.5 text-xs bg-white/10 hover:bg-white/20 text-white px-3 py-1.5 rounded-lg font-medium transition-colors">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"></path>
                    </svg>
                    Move
                </button>
                <button @click="handleDeleteSelected" type="button"
                    class="flex items-center gap-1.5 text-xs bg-rose-500/90 hover:bg-rose-500 text-white px-3 py-1.5 rounded-lg font-medium transition-colors">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                    </svg>
                    Delete
                </button>
                <button @click="clearSelection" type="button"
                    class="text-xs text-stone-300 hover:text-white px-2 py-1">
                    Clear
                </button>
            </div>
        </div>

        <!-- Error State -->
        <div v-if="error" class="bg-rose-50 border border-rose-200 text-rose-700 px-4 py-3 rounded-xl text-sm mb-6 flex items-center justify-between">
            <span>{{ error }}</span>
        </div>

        <!-- Loading State -->
        <div v-if="isLoading" class="flex flex-col items-center justify-center py-24 gap-3">
            <div class="animate-spin rounded-full h-8 w-8 border-2 border-stone-300 border-t-slate-900"></div>
            <span class="text-xs font-mono text-stone-500">Loading directory...</span>
        </div>

        <!-- Empty Directory State -->
        <div v-else-if="folders.length === 0 && regularFiles.length === 0"
            class="bg-white border border-stone-200/90 rounded-2xl p-12 text-center max-w-lg mx-auto my-8 shadow-sm">
            <div class="w-12 h-12 bg-stone-100 text-stone-500 rounded-xl flex items-center justify-center mx-auto mb-4">
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"></path>
                </svg>
            </div>
            <h3 class="text-sm font-bold text-slate-900 mb-1">This folder is empty</h3>
            <p class="text-xs text-stone-500 mb-6">Drag and drop <code class="font-mono text-[11px] bg-stone-100 px-1 py-0.5 rounded text-slate-700">.note</code>, PDF, EPUB, or image files here, or use the actions below.</p>
            <div class="flex items-center justify-center gap-2.5">
                <button @click="showNewFolderModal = true" type="button"
                    class="px-3.5 py-2 bg-white hover:bg-stone-50 text-slate-700 border border-stone-200 rounded-lg text-xs font-semibold transition-colors">
                    + New Folder
                </button>
                <button @click="triggerUpload" type="button"
                    class="px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold transition-colors">
                    Upload Files
                </button>
            </div>
        </div>

        <!-- Populated Directory Content -->
        <template v-else>
            <!-- List View Mode -->
            <div v-if="displayMode === 'list'" class="bg-white rounded-2xl border border-stone-200/90 shadow-sm overflow-hidden">
                <div class="grid grid-cols-12 gap-4 px-4 py-2.5 bg-stone-50/80 border-b border-stone-200/80 text-[11px] font-semibold uppercase tracking-wider text-stone-500">
                    <div class="col-span-7 sm:col-span-5 pl-7">Name</div>
                    <div class="hidden sm:block sm:col-span-3">Modified</div>
                    <div class="col-span-3 sm:col-span-2 text-right">Size</div>
                    <div class="col-span-2 text-right pr-2">Actions</div>
                </div>
                <div class="divide-y divide-stone-100">
                    <FileCard v-for="folder in folders" :key="folder.id" :file="folder" layout="list"
                        :is-selected="selectedIds.includes(folder.id)"
                        :selection-mode="selectedIds.length > 0"
                        :processing-status="processingStatuses[folder.id]" @open="$emit('open-item', $event)" @select="toggleSelection"
                        @rename="triggerRename" />
                    <FileCard v-for="file in regularFiles" :key="file.id" :file="file" layout="list"
                        :is-selected="selectedIds.includes(file.id)"
                        :selection-mode="selectedIds.length > 0"
                        :processing-status="processingStatuses[file.id]" @open="$emit('open-item', $event)" @select="toggleSelection"
                        @rename="triggerRename" />
                </div>
            </div>

            <!-- Grid View Mode (Separated Compact Folders + Portrait Notebook Cards) -->
            <div v-else class="space-y-8">
                <!-- Folders Section -->
                <section v-if="folders.length > 0">
                    <div class="flex items-center justify-between mb-3">
                        <h2 class="text-[11px] font-bold uppercase tracking-wider text-stone-500">
                            Folders <span class="font-mono font-normal text-stone-500">({{ allFolders.length }})</span>
                        </h2>
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                        <FileCard v-for="folder in folders" :key="folder.id" :file="folder" layout="folder"
                            :is-selected="selectedIds.includes(folder.id)"
                            :selection-mode="selectedIds.length > 0"
                            :processing-status="processingStatuses[folder.id]" @open="$emit('open-item', $event)" @select="toggleSelection"
                            @rename="triggerRename" />
                    </div>
                </section>

                <!-- Files & Notebooks Section -->
                <section v-if="regularFiles.length > 0">
                    <div class="flex items-center justify-between mb-3">
                        <h2 class="text-[11px] font-bold uppercase tracking-wider text-stone-500">
                            Notebooks &amp; Files <span class="font-mono font-normal text-stone-500">({{ allRegularFiles.length }})</span>
                        </h2>
                    </div>
                    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 sm:gap-5">
                        <FileCard v-for="file in regularFiles" :key="file.id" :file="file" layout="grid"
                            :is-selected="selectedIds.includes(file.id)"
                            :selection-mode="selectedIds.length > 0"
                            :processing-status="processingStatuses[file.id]" @open="$emit('open-item', $event)" @select="toggleSelection"
                            @rename="triggerRename" />
                    </div>
                </section>
            </div>

            <!-- Directory Pagination Footer -->
            <div v-if="totalItemCount > 50"
                class="mt-8 flex flex-col items-center gap-3">
                <p class="text-xs font-mono text-stone-500 tabular-nums">
                    Showing {{ visibleItemCount }} of {{ totalItemCount }} items
                </p>
                <button v-if="hasMoreItems" @click="loadMoreItems" type="button"
                    class="px-5 py-2 bg-white hover:bg-stone-50 text-slate-700 border border-stone-200 rounded-xl text-xs font-semibold shadow-sm transition-all">
                    Load More
                </button>
            </div>
        </template>

        <!-- Hidden Upload Input -->
        <input type="file" ref="fileInput" class="hidden" multiple @change="handleFileUpload">

        <!-- Create New Folder Modal -->
        <div v-if="showNewFolderModal"
            role="dialog" aria-modal="true" aria-label="Create New Folder"
            class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px]"
            @click.self="!isCreatingFolder && (showNewFolderModal = false)">
            <form @submit.prevent="handleCreateFolder" class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-md p-6 animate-fade-in">
                <h3 class="text-base font-bold text-slate-900 mb-1">Create New Folder</h3>
                <p class="text-xs text-stone-500 mb-4">Create a subfolder inside {{ breadcrumbs[breadcrumbs.length - 1]?.name || 'Cloud' }}.</p>
                <input id="new-folder-name" ref="newFolderInput" v-model="newFolderName" type="text" placeholder="Folder name" aria-label="Folder name"
                    :disabled="isCreatingFolder"
                    class="w-full px-3.5 py-2.5 bg-stone-50 border border-stone-200 rounded-xl text-sm focus:ring-2 focus:ring-slate-900 focus:border-slate-900 outline-none transition-all mb-5 disabled:opacity-60">
                <div class="flex justify-end gap-2.5">
                    <button @click="showNewFolderModal = false" :disabled="isCreatingFolder" type="button"
                        class="px-4 py-2 text-xs text-stone-600 hover:text-slate-900 font-semibold disabled:opacity-40">Cancel</button>
                    <button type="submit" :disabled="isCreatingFolder || !newFolderName.trim()"
                        class="px-5 py-2 bg-slate-900 hover:bg-slate-800 disabled:opacity-40 text-white rounded-xl text-xs font-semibold transition-all">
                        {{ isCreatingFolder ? 'Creating...' : 'Create Folder' }}
                    </button>
                </div>
            </form>
        </div>

        <!-- In-App Delete Confirmation Modal -->
        <div v-if="showDeleteModal"
            role="dialog" aria-modal="true" aria-label="Confirm Delete"
            class="fixed inset-0 z-[110] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px]"
            @click.self="!isDeletingItems && (showDeleteModal = false)">
            <div class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-sm p-6 animate-fade-in">
                <div class="w-10 h-10 rounded-xl bg-rose-50 text-rose-600 flex items-center justify-center mb-3">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                    </svg>
                </div>
                <h3 class="text-base font-bold text-slate-900 mb-1">
                    Delete {{ selectedIds.length }} {{ selectedIds.length === 1 ? 'item' : 'items' }}?
                </h3>
                <p class="text-xs text-stone-500 mb-5 leading-relaxed">
                    The selected {{ selectedIds.length === 1 ? 'item' : 'items' }} will be moved to the Recycle Bin and can be restored for up to 30 days.
                </p>
                <div class="flex justify-end gap-2.5">
                    <button ref="deleteCancelBtn" @click="showDeleteModal = false" :disabled="isDeletingItems" type="button"
                        class="px-4 py-2 text-xs text-stone-600 hover:text-slate-900 font-semibold rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 disabled:opacity-40">Cancel</button>
                    <button @click="confirmDeleteSelected" :disabled="isDeletingItems" type="button"
                        class="px-5 py-2 bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white rounded-xl text-xs font-semibold transition-all">
                        {{ isDeletingItems ? 'Deleting...' : 'Delete' }}
                    </button>
                </div>
            </div>
        </div>

        <!-- Move & Rename Modals -->
        <MoveModal v-if="showMoveModal" :item-ids="selectedIds" :is-submitting="isMovingItems" @close="!isMovingItems && (showMoveModal = false)"
            @confirm="onConfirmMove" />

        <RenameModal v-if="showRenameModal" :item="itemToRename" :is-submitting="isRenamingItem" @close="!isRenamingItem && (showRenameModal = false)"
            @confirm="onConfirmRename" />
    </div>
    `,
};
