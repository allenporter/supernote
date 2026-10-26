import { fetchFiles } from '../api/client.js';

export default {
    name: 'MoveModal',
    props: ['itemIds'],
    emits: ['close', 'confirm'],
    template: `
        <div class="fixed inset-0 z-[110] flex items-center justify-center p-4 bg-slate-900/40 dark:bg-black/60 backdrop-blur-sm" @click.self="$emit('close')">
            <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl w-full max-w-md flex flex-col max-h-[80vh] animate-in zoom-in-95">
                <!-- Header -->
                <div class="p-5 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
                    <div>
                        <h3 class="text-lg font-bold text-slate-900 dark:text-white">Move {{ (itemIds || []).length }} {{ (itemIds || []).length === 1 ? 'item' : 'items' }} to...</h3>
                        <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5 truncate" data-testid="move-destination">
                            Destination: <span class="font-semibold text-indigo-600 dark:text-indigo-400">{{ destinationPath }}</span>
                        </p>
                    </div>
                    <button @click="$emit('close')" class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors" aria-label="Close move modal">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                    </button>
                </div>

                <!-- Breadcrumb Navigation Bar -->
                <nav class="px-4 py-2.5 bg-slate-50/80 dark:bg-slate-800/50 border-b border-slate-100 dark:border-slate-800 flex items-center gap-1 overflow-x-auto whitespace-nowrap text-xs font-medium text-slate-500 dark:text-slate-400" aria-label="Move modal breadcrumbs" data-testid="move-breadcrumbs">
                    <div v-for="(crumb, index) in breadcrumbs" :key="crumb.id" class="flex items-center">
                        <button type="button"
                            @click="navigateToBreadcrumb(index)"
                            :data-testid="'move-crumb-' + crumb.id"
                            :class="index === breadcrumbs.length - 1 ? 'text-indigo-600 dark:text-indigo-400 font-bold bg-indigo-50 dark:bg-indigo-950/50' : 'hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800'"
                            class="flex items-center gap-1 px-2 py-1 rounded-md transition-colors">
                            <svg v-if="index === 0" class="w-3.5 h-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                                <path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z"></path>
                            </svg>
                            <span>{{ crumb.name }}</span>
                        </button>
                        <span v-if="index < breadcrumbs.length - 1" class="mx-1 text-slate-300 dark:text-slate-600">/</span>
                    </div>
                </nav>

                <!-- Folder Browser List -->
                <div class="flex-1 overflow-y-auto p-2 space-y-1">
                    <!-- Current Opened Directory Option -->
                    <div @click="selectTarget(currentBrowserDirId)"
                        data-testid="move-current-folder-option"
                        class="flex items-center justify-between gap-3 p-3 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-800/60 cursor-pointer transition-colors border"
                        :class="String(targetDirId) === String(currentBrowserDirId) ? 'bg-indigo-50 dark:bg-indigo-950/40 border-indigo-200 dark:border-indigo-800' : 'border-transparent'">
                        <div class="flex items-center gap-3 min-w-0">
                            <div class="w-10 h-10 bg-indigo-100 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400 rounded-lg flex items-center justify-center shrink-0">
                                <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20"><path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z"></path></svg>
                            </div>
                            <div class="min-w-0">
                                <div class="font-medium text-slate-700 dark:text-slate-200 truncate">
                                    {{ currentBrowserDirId === '0' ? 'Cloud Root' : currentFolderName }}
                                </div>
                                <div class="text-[11px] text-slate-400 dark:text-slate-500">
                                    Move directly into this folder
                                </div>
                            </div>
                        </div>
                        <span v-if="String(targetDirId) === String(currentBrowserDirId)" class="text-xs font-semibold text-indigo-600 dark:text-indigo-400 px-2 py-0.5 bg-indigo-100/80 dark:bg-indigo-900/50 rounded-md shrink-0">
                            Selected
                        </span>
                    </div>

                    <!-- Loading State -->
                    <div v-if="isLoading" class="py-8 flex justify-center">
                        <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-indigo-600 dark:border-indigo-400"></div>
                    </div>

                    <!-- Subfolders List -->
                    <template v-else>
                        <div v-for="folder in availableFolders"
                            :key="folder.id"
                            :data-testid="'move-folder-' + folder.id"
                            @click="selectTarget(folder.id)"
                            @dblclick="enterFolder(folder)"
                            class="flex items-center justify-between gap-3 p-3 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-800/60 cursor-pointer transition-colors border"
                            :class="String(targetDirId) === String(folder.id) ? 'bg-indigo-50 dark:bg-indigo-950/40 border-indigo-200 dark:border-indigo-800' : 'border-transparent'">
                            <div class="flex items-center gap-3 min-w-0 flex-1">
                                <div class="w-10 h-10 bg-amber-100 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 rounded-lg flex items-center justify-center shrink-0">
                                    <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20"><path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z"></path></svg>
                                </div>
                                <span class="font-medium text-slate-700 dark:text-slate-200 truncate">{{ folder.name }}</span>
                            </div>
                            <button type="button"
                                @click.stop="enterFolder(folder)"
                                :data-testid="'move-enter-' + folder.id"
                                title="Open subfolder"
                                class="px-2.5 py-1.5 text-xs font-medium text-slate-500 dark:text-slate-400 hover:text-indigo-600 dark:hover:text-indigo-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg flex items-center gap-1 transition-colors shrink-0">
                                <span>Open</span>
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                                </svg>
                            </button>
                        </div>

                        <div v-if="availableFolders.length === 0" class="py-6 text-center text-xs text-slate-400 dark:text-slate-500">
                            No subfolders available in this directory.
                        </div>
                    </template>
                </div>

                <!-- Footer -->
                <div class="p-5 border-t border-slate-100 dark:border-slate-800 flex justify-end gap-3">
                    <button type="button" @click="$emit('close')" class="px-4 py-2 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 font-medium transition-colors">
                        Cancel
                    </button>
                    <button type="button" @click="confirmMove" :disabled="!targetDirId"
                        data-testid="move-confirm-btn"
                        class="px-6 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-xl font-bold shadow-lg shadow-indigo-200 dark:shadow-none transition-all">
                        Move Here
                    </button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            folders: [],
            currentBrowserDirId: '0',
            breadcrumbs: [{ id: '0', name: 'Cloud Root' }],
            targetDirId: '0',
            isLoading: false
        };
    },
    computed: {
        excludedIdSet() {
            return new Set((this.itemIds || []).map(id => String(id)));
        },
        availableFolders() {
            return this.folders.filter(folder => !this.excludedIdSet.has(String(folder.id)));
        },
        currentFolderName() {
            const last = this.breadcrumbs[this.breadcrumbs.length - 1];
            return last ? last.name : 'Cloud Root';
        },
        destinationPath() {
            if (!this.targetDirId) return 'None selected';
            const basePath = this.breadcrumbs.map(c => c.name).join(' / ');
            if (String(this.targetDirId) === String(this.currentBrowserDirId)) {
                return basePath;
            }
            const selectedSubfolder = this.availableFolders.find(
                f => String(f.id) === String(this.targetDirId)
            );
            if (selectedSubfolder) {
                return `${basePath} / ${selectedSubfolder.name}`;
            }
            if (String(this.targetDirId) === '0') {
                return 'Cloud Root';
            }
            return basePath;
        }
    },
    async mounted() {
        await this.loadFolders('0');
    },
    methods: {
        isExcluded(id) {
            return this.excludedIdSet.has(String(id));
        },
        async loadFolders(dirId = this.currentBrowserDirId) {
            const targetId = String(dirId || '0');
            this.isLoading = true;
            try {
                const files = await fetchFiles(targetId);
                this.folders = files.filter(
                    f => f.isDirectory && !this.isExcluded(f.id)
                );
            } catch (e) {
                console.error(e);
                this.folders = [];
            } finally {
                this.isLoading = false;
            }
        },
        selectTarget(id) {
            if (id === null || id === undefined) return;
            const targetId = String(id);
            if (this.isExcluded(targetId)) return;
            this.targetDirId = targetId;
        },
        async enterFolder(folder) {
            if (!folder || folder.id === null || folder.id === undefined) return;
            const folderId = String(folder.id);
            if (this.isExcluded(folderId)) return;

            this.currentBrowserDirId = folderId;
            this.targetDirId = folderId;

            const existingIndex = this.breadcrumbs.findIndex(c => String(c.id) === folderId);
            if (existingIndex > -1) {
                this.breadcrumbs = this.breadcrumbs.slice(0, existingIndex + 1);
            } else {
                this.breadcrumbs.push({ id: folderId, name: folder.name });
            }

            await this.loadFolders(folderId);
        },
        async navigateToBreadcrumb(index) {
            if (index < 0 || index >= this.breadcrumbs.length) return;
            this.breadcrumbs = this.breadcrumbs.slice(0, index + 1);
            const target = this.breadcrumbs[this.breadcrumbs.length - 1];
            this.currentBrowserDirId = String(target.id);
            this.targetDirId = String(target.id);
            await this.loadFolders(this.currentBrowserDirId);
        },
        confirmMove() {
            if (!this.targetDirId || this.isExcluded(this.targetDirId)) return;
            this.$emit('confirm', String(this.targetDirId));
        }
    }
};
