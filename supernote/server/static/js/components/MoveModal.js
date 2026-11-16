import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue';
import { fetchFiles } from '../api/client.js';
import { useModalEscape } from '../composables/useModalEscape.js';

export default {
    name: 'MoveModal',
    props: {
        itemIds: {
            type: Array,
            default: () => [],
        },
        isSubmitting: {
            type: Boolean,
            default: false,
        },
    },
    emits: ['close', 'confirm'],
    template: `
        <div class="fixed inset-0 z-[110] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px] animate-fade-in" @click.self="!isSubmitting && $emit('close')">
            <div ref="dialogRef" tabindex="-1" role="dialog" aria-modal="true" aria-label="Move Items"
                class="bg-white border border-stone-200 rounded-2xl shadow-2xl w-full max-w-md flex flex-col max-h-[80vh] overflow-hidden outline-none">
                <!-- Header -->
                <div class="px-5 py-4 border-b border-stone-200/80 bg-[#F7F6F2]/60 flex items-center justify-between">
                    <div class="min-w-0">
                        <h3 class="text-base font-bold text-slate-900">Move {{ (itemIds || []).length }} {{ (itemIds || []).length === 1 ? 'item' : 'items' }} to...</h3>
                        <p class="text-xs text-stone-500 mt-0.5 truncate" data-testid="move-destination">
                            Destination: <span class="font-semibold text-slate-900">{{ destinationPath }}</span>
                        </p>
                    </div>
                    <button @click="$emit('close')" :disabled="isSubmitting" type="button" class="p-1.5 rounded-lg text-stone-500 hover:text-slate-900 hover:bg-stone-200/60 transition-colors disabled:opacity-40" aria-label="Close move modal">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                    </button>
                </div>

                <!-- Breadcrumb Navigation Bar -->
                <nav class="px-4 py-2 bg-stone-50 border-b border-stone-200/70 flex items-center gap-1 overflow-x-auto whitespace-nowrap text-xs font-medium text-stone-500" aria-label="Move modal breadcrumbs" data-testid="move-breadcrumbs">
                    <div v-for="(crumb, index) in breadcrumbs" :key="crumb.id" class="flex items-center">
                        <button type="button"
                            @click="navigateToBreadcrumb(index)"
                            :data-testid="'move-crumb-' + crumb.id"
                            :class="index === breadcrumbs.length - 1 ? 'text-slate-900 font-bold bg-stone-200/70' : 'hover:text-slate-900 hover:bg-stone-200/40'"
                            class="flex items-center gap-1 px-2 py-1 rounded-md transition-colors">
                            <svg v-if="index === 0" class="w-3.5 h-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                                <path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z"></path>
                            </svg>
                            <span>{{ crumb.name }}</span>
                        </button>
                        <span v-if="index < breadcrumbs.length - 1" class="mx-1 text-stone-400">/</span>
                    </div>
                </nav>

                <!-- Folder Browser List -->
                <div class="flex-1 overflow-y-auto p-2.5 space-y-1">
                    <!-- Current Opened Directory Option -->
                    <button type="button" @click="selectTarget(currentBrowserDirId)"
                        data-testid="move-current-folder-option"
                        class="w-full text-left flex items-center justify-between gap-3 p-3 rounded-xl hover:bg-stone-50 cursor-pointer transition-colors border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900"
                        :class="String(targetDirId) === String(currentBrowserDirId) ? 'bg-stone-100/80 border-slate-900' : 'border-transparent'">
                        <div class="flex items-center gap-3 min-w-0">
                            <div class="w-9 h-9 bg-stone-200/70 text-slate-800 rounded-lg flex items-center justify-center shrink-0">
                                <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z"></path></svg>
                            </div>
                            <div class="min-w-0">
                                <div class="text-xs font-semibold text-slate-900 truncate">
                                    {{ currentBrowserDirId === '0' ? 'Cloud Root' : currentFolderName }}
                                </div>
                                <div class="text-[11px] text-stone-500">
                                    Move directly into this folder
                                </div>
                            </div>
                        </div>
                        <span v-if="String(targetDirId) === String(currentBrowserDirId)" class="text-[10px] font-mono font-semibold text-white px-2 py-0.5 bg-slate-900 rounded-md shrink-0">
                            Selected
                        </span>
                    </button>

                    <!-- Loading State -->
                    <div v-if="isLoading" class="py-8 flex justify-center">
                        <div class="animate-spin rounded-full h-5 w-5 border-2 border-stone-300 border-t-slate-900"></div>
                    </div>

                    <!-- Subfolders List -->
                    <template v-else>
                        <div v-for="folder in availableFolders"
                            :key="folder.id"
                            tabindex="0"
                            :aria-label="'Select destination folder ' + folder.name"
                            :data-testid="'move-folder-' + folder.id"
                            @click="selectTarget(folder.id)"
                            @dblclick="enterFolder(folder)"
                            @keydown.enter.self.prevent="selectTarget(folder.id)"
                            @keydown.space.self.prevent="selectTarget(folder.id)"
                            class="flex items-center justify-between gap-3 p-3 rounded-xl hover:bg-stone-50 cursor-pointer transition-colors border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900"
                            :class="String(targetDirId) === String(folder.id) ? 'bg-stone-100/80 border-slate-900' : 'border-transparent'">
                            <div class="flex items-center gap-3 min-w-0 flex-1">
                                <div class="w-9 h-9 bg-amber-50 border border-amber-200/60 text-amber-600 rounded-lg flex items-center justify-center shrink-0">
                                    <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z"></path></svg>
                                </div>
                                <span class="text-xs font-semibold text-slate-900 truncate">{{ folder.name }}</span>
                            </div>
                            <button type="button"
                                @click.stop="enterFolder(folder)"
                                :data-testid="'move-enter-' + folder.id"
                                title="Open subfolder"
                                class="px-2.5 py-1 text-xs font-semibold text-stone-500 hover:text-slate-900 hover:bg-stone-200/60 rounded-lg flex items-center gap-1 transition-colors shrink-0">
                                <span>Open</span>
                                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                                </svg>
                            </button>
                        </div>

                        <div v-if="availableFolders.length === 0" class="py-6 text-center text-xs text-stone-500">
                            No subfolders available in this directory.
                        </div>
                    </template>
                </div>

                <!-- Footer -->
                <div class="px-5 py-3.5 border-t border-stone-200/80 bg-[#F7F6F2]/60 flex justify-end gap-2.5">
                    <button type="button" @click="$emit('close')" :disabled="isSubmitting" class="px-4 py-2 text-xs text-stone-600 hover:text-slate-900 font-semibold transition-colors disabled:opacity-40">
                        Cancel
                    </button>
                    <button type="button" @click="confirmMove" :disabled="isSubmitting || !targetDirId"
                        data-testid="move-confirm-btn"
                        class="px-5 py-2 bg-slate-900 hover:bg-slate-800 disabled:opacity-40 text-white rounded-xl text-xs font-semibold transition-all">
                        {{ isSubmitting ? 'Moving...' : 'Move Here' }}
                    </button>
                </div>
            </div>
        </div>
    `,
    /**
     * @param {{ itemIds?: Array<string | number>, isSubmitting?: boolean }} props
     * @param {{ emit: (event: string, ...args: any[]) => void }} context
     */
    setup(props, { emit }) {
        /** @type {import('vue').Ref<HTMLElement | null>} */
        const dialogRef = ref(null);
        /** @type {import('vue').Ref<FileItem[]>} */
        const folders = ref([]);
        const currentBrowserDirId = ref('0');
        const breadcrumbs = ref([{ id: '0', name: 'Cloud Root' }]);
        const targetDirId = ref('0');
        const isLoading = ref(false);
        let activeLoadSeq = 0;

        const excludedIdSet = computed(
            () => new Set((props.itemIds || []).map((id) => String(id))),
        );

        const availableFolders = computed(() =>
            folders.value.filter((folder) => !excludedIdSet.value.has(String(folder.id))),
        );

        const currentFolderName = computed(() => {
            const last = breadcrumbs.value[breadcrumbs.value.length - 1];
            return last ? last.name : 'Cloud Root';
        });

        const destinationPath = computed(() => {
            if (!targetDirId.value) return 'None selected';
            const basePath = breadcrumbs.value.map((c) => c.name).join(' / ');
            if (String(targetDirId.value) === String(currentBrowserDirId.value)) {
                return basePath;
            }
            const selectedSubfolder = availableFolders.value.find(
                (f) => String(f.id) === String(targetDirId.value),
            );
            if (selectedSubfolder) {
                return `${basePath} / ${selectedSubfolder.name}`;
            }
            if (String(targetDirId.value) === '0') {
                return 'Cloud Root';
            }
            return basePath;
        });

        /**
         * @param {string | number} id
         */
        const isExcluded = (id) => excludedIdSet.value.has(String(id));

        const loadFolders = async (dirId = currentBrowserDirId.value) => {
            const seq = ++activeLoadSeq;
            const targetId = String(dirId || '0');
            isLoading.value = true;
            try {
                const files = await fetchFiles(targetId);
                if (seq !== activeLoadSeq) return;
                folders.value = files.filter((f) => f.isDirectory && !isExcluded(f.id));
            } catch (e) {
                if (seq !== activeLoadSeq) return;
                console.error(e);
                folders.value = [];
            } finally {
                if (seq === activeLoadSeq) {
                    isLoading.value = false;
                }
            }
        };

        /**
         * @param {string | number | null | undefined} id
         */
        const selectTarget = (id) => {
            if (id === null || id === undefined) return;
            const targetId = String(id);
            if (isExcluded(targetId)) return;
            targetDirId.value = targetId;
        };

        /**
         * @param {FileItem | null | undefined} folder
         */
        const enterFolder = async (folder) => {
            if (!folder || folder.id === null || folder.id === undefined) return;
            const folderId = String(folder.id);
            if (isExcluded(folderId)) return;

            currentBrowserDirId.value = folderId;
            targetDirId.value = folderId;

            const existingIndex = breadcrumbs.value.findIndex((c) => String(c.id) === folderId);
            if (existingIndex > -1) {
                breadcrumbs.value = breadcrumbs.value.slice(0, existingIndex + 1);
            } else {
                breadcrumbs.value.push({ id: folderId, name: folder.name });
            }

            await loadFolders(folderId);
        };

        /**
         * @param {number} index
         */
        const navigateToBreadcrumb = async (index) => {
            if (index < 0 || index >= breadcrumbs.value.length) return;
            breadcrumbs.value = breadcrumbs.value.slice(0, index + 1);
            const target = breadcrumbs.value[breadcrumbs.value.length - 1];
            currentBrowserDirId.value = String(target.id);
            targetDirId.value = String(target.id);
            await loadFolders(currentBrowserDirId.value);
        };

        const confirmMove = () => {
            if (props.isSubmitting || !targetDirId.value || isExcluded(targetDirId.value)) return;
            emit('confirm', String(targetDirId.value));
        };

        useModalEscape(() => {
            if (!props.isSubmitting) emit('close');
        });

        onMounted(() => {
            loadFolders('0');
            nextTick(() => dialogRef.value?.focus());
        });

        onUnmounted(() => {
            activeLoadSeq++;
        });

        return {
            dialogRef,
            folders,
            currentBrowserDirId,
            breadcrumbs,
            targetDirId,
            isLoading,
            availableFolders,
            currentFolderName,
            destinationPath,
            loadFolders,
            selectTarget,
            enterFolder,
            navigateToBreadcrumb,
            confirmMove,
        };
    },
};
