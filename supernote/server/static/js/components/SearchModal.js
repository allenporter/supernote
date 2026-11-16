import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { searchFiles, searchSemantic } from '../api/client.js';
import { fetchTasks } from '../api/schedule.js';
import { useModalEscape } from '../composables/useModalEscape.js';

export default {
    props: {
        initialQuery: {
            type: String,
            default: '',
        },
    },
    emits: ['close', 'select-file', 'select-task'],
    /**
     * @param {{ initialQuery?: string }} props
     * @param {{ emit: (event: string, ...args: any[]) => void }} context
     */
    setup(props, { emit }) {
        const query = ref(props.initialQuery || '');
        const isSearching = ref(false);
        /** @type {import('vue').Ref<SearchFileMatch[]>} */
        const results = ref([]);
        /** @type {import('vue').Ref<SemanticSearchMatch[]>} */
        const semanticResults = ref([]);
        /** @type {import('vue').Ref<ScheduleTask[]>} */
        const taskResults = ref([]);
        /** @type {import('vue').Ref<HTMLInputElement | null>} */
        const searchInput = ref(null);

        /** @type {ReturnType<typeof setTimeout> | null} */
        let searchTimeout = null;
        /** @type {Promise<ScheduleTask[]> | null} */
        let cachedTasksPromise = null;
        let activeSearchSeq = 0;

        const invalidateTaskCache = () => {
            cachedTasksPromise = null;
        };

        /**
         * Cache tasks for the duration of the open modal session (invalidated on `supernote:task-sync`)
         * so typing debounced queries does not re-fetch the entire task list on every keystroke.
         * @returns {Promise<ScheduleTask[]>}
         */
        const getModalTasks = () => {
            if (!cachedTasksPromise) {
                cachedTasksPromise = fetchTasks().catch(() => {
                    cachedTasksPromise = null;
                    return [];
                });
            }
            return cachedTasksPromise;
        };

        useModalEscape(() => emit('close'));

        /**
         * @param {string} trimmed
         * @param {number} seq
         */
        const runSearchNow = async (trimmed, seq) => {
            try {
                const qLower = trimmed.toLowerCase();
                const [fileMatches, vectorMatches, allTasks] = await Promise.all([
                    searchFiles(trimmed).catch(() => []),
                    searchSemantic(trimmed).catch(() => []),
                    getModalTasks(),
                ]);
                if (seq !== activeSearchSeq) return;

                results.value = fileMatches;
                semanticResults.value = vectorMatches;
                taskResults.value = allTasks.filter(
                    (t) =>
                        t.title.toLowerCase().includes(qLower) ||
                        t.detail?.toLowerCase().includes(qLower),
                );
            } catch (e) {
                if (seq !== activeSearchSeq) return;
                console.error('Search failed:', e);
            } finally {
                if (seq === activeSearchSeq) {
                    isSearching.value = false;
                }
            }
        };

        /**
         * @param {boolean | Event} [immediate=false]
         */
        const handleSearch = (immediate = false) => {
            if (searchTimeout) clearTimeout(searchTimeout);
            const trimmed = query.value.trim();
            if (!trimmed) {
                activeSearchSeq++;
                results.value = [];
                semanticResults.value = [];
                taskResults.value = [];
                isSearching.value = false;
                return;
            }

            const seq = ++activeSearchSeq;
            isSearching.value = true;
            if (immediate === true) {
                runSearchNow(trimmed, seq);
            } else {
                searchTimeout = setTimeout(() => {
                    runSearchNow(trimmed, seq);
                }, 300);
            }
        };

        watch(
            () => props.initialQuery,
            (newVal) => {
                if (typeof newVal === 'string' && newVal !== query.value) {
                    query.value = newVal;
                    handleSearch(true);
                }
            },
        );

        /**
         * @param {Record<string, any>} item
         */
        const handleSelect = (item) => {
            emit('select-file', item);
            emit('close');
        };

        /**
         * @param {ScheduleTask} task
         */
        const handleSelectTaskItem = (task) => {
            emit('select-task', task);
            emit('close');
        };

        onMounted(() => {
            window.addEventListener('supernote:task-sync', invalidateTaskCache);
            if (query.value.trim()) {
                handleSearch(true);
            }
            nextTick(() => {
                if (searchInput.value) {
                    searchInput.value.focus();
                }
            });
        });

        onUnmounted(() => {
            window.removeEventListener('supernote:task-sync', invalidateTaskCache);
            if (searchTimeout) clearTimeout(searchTimeout);
        });

        return {
            query,
            isSearching,
            results,
            semanticResults,
            taskResults,
            searchInput,
            handleSearch,
            handleSelect,
            handleSelectTaskItem,
        };
    },
    template: `
    <div class="fixed inset-0 z-[150] flex items-start justify-center pt-16 px-4 bg-slate-900/40 backdrop-blur-[2px] animate-fade-in"
        @click.self="$emit('close')">
        <div class="bg-white border border-stone-200 rounded-2xl shadow-2xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[80vh]"
            role="dialog" aria-modal="true" aria-label="Global Search">
            <!-- Unified Search Header -->
            <div class="p-3.5 border-b border-stone-200/80 bg-[#F7F6F2]/60 flex items-center gap-3">
                <svg class="w-4 h-4 text-stone-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                <input ref="searchInput" v-model="query" @input="handleSearch" type="text"
                    aria-label="Global Search"
                    placeholder="Global Search (notebooks, transcripts, files, or tasks)..."
                    class="w-full bg-transparent text-slate-900 placeholder-stone-500 outline-none text-sm font-medium">
                <button type="button" @click="$emit('close')" title="Close search (Escape)" aria-label="Close search"
                    class="px-1.5 py-0.5 bg-white hover:bg-stone-100 text-stone-500 hover:text-slate-900 text-[10px] font-mono rounded border border-stone-200 transition-colors">
                    ESC
                </button>
            </div>

            <!-- Results Content Area -->
            <div class="p-4 overflow-y-auto space-y-4 flex-1">
                <!-- Initial Prompt State -->
                <div v-if="!query.trim() && !isSearching" class="py-8 text-center text-stone-500 text-xs">
                    Type to search across filenames, handwritten notebook transcripts, and tasks.
                </div>

                <!-- Searching Indicator -->
                <div v-if="isSearching" class="py-8 text-center text-stone-500 text-xs">
                    <div class="animate-spin rounded-full h-5 w-5 border-2 border-stone-300 border-t-slate-900 mx-auto mb-2"></div>
                    Searching notebooks, files, and tasks...
                </div>

                <!-- Matching Tasks -->
                <div v-if="!isSearching && taskResults.length > 0" class="space-y-1.5">
                    <div class="text-[11px] font-bold text-stone-500 uppercase tracking-wider px-1">
                        Matching Tasks
                    </div>
                    <button type="button" v-for="t in taskResults" :key="t.id" @click="handleSelectTaskItem(t)"
                        class="w-full text-left p-2.5 bg-stone-50 hover:bg-stone-100 rounded-xl border border-stone-200/80 cursor-pointer transition-all flex items-center justify-between gap-3">
                        <div class="min-w-0">
                            <p class="font-semibold text-slate-900 text-xs truncate">{{ t.title }}</p>
                            <p v-if="t.detail" class="text-[10px] text-stone-500 mt-0.5 truncate">{{ t.detail }}</p>
                        </div>
                        <span class="text-[10px] font-mono bg-emerald-50 border border-emerald-200 text-emerald-700 font-semibold px-2 py-0.5 rounded-md shrink-0">Task</span>
                    </button>
                </div>

                <!-- Semantic Content Results -->
                <div v-if="!isSearching && semanticResults.length > 0" class="space-y-1.5">
                    <div class="text-[11px] font-bold text-stone-500 uppercase tracking-wider px-1">
                        Semantic Notebook Content
                    </div>
                    <button type="button" v-for="res in semanticResults" :key="res.key"
                        @click="handleSelect({ id: res.fileId, name: res.fileName, isDirectory: false, extension: res.extension, pageIndex: res.pageIndex })"
                        class="w-full text-left p-2.5 bg-stone-50 hover:bg-stone-100 rounded-xl border border-stone-200/80 cursor-pointer transition-all">
                        <div class="flex items-center justify-between gap-2">
                            <div class="flex items-center gap-2 min-w-0">
                                <span class="font-semibold text-slate-900 text-xs truncate">{{ res.fileName }}</span>
                                <span class="px-1.5 py-0.5 rounded bg-slate-900 text-white text-[10px] font-mono font-semibold shrink-0 tabular-nums">
                                    Page {{ res.pageNumber }}
                                </span>
                                <span v-if="res.date" class="text-[10px] text-stone-500 font-mono shrink-0 tabular-nums">{{ res.date }}</span>
                            </div>
                            <span class="text-[10px] text-stone-500 font-mono shrink-0 tabular-nums">Match: {{ Math.round(res.score * 100) }}%</span>
                        </div>
                        <p class="text-[11px] text-stone-600 mt-1 line-clamp-2">{{ res.textPreview }}</p>
                    </button>
                </div>

                <!-- Keyword File Matches -->
                <div v-if="!isSearching && results.length > 0" class="space-y-1.5">
                    <div class="text-[11px] font-bold text-stone-500 uppercase tracking-wider px-1">
                        Files &amp; Folders
                    </div>
                    <button type="button" v-for="item in results" :key="item.id" @click="handleSelect(item)"
                        class="w-full text-left p-2.5 bg-stone-50 hover:bg-stone-100 rounded-xl border border-stone-200/80 cursor-pointer transition-all flex items-center justify-between gap-3">
                        <div class="min-w-0 flex items-center gap-2.5">
                            <span class="px-1.5 py-0.5 rounded bg-stone-200/70 text-stone-700 text-[10px] font-mono font-semibold uppercase shrink-0">
                                {{ item.isDirectory ? 'DIR' : (item.extension || 'FILE') }}
                            </span>
                            <div class="min-w-0">
                                <p class="font-semibold text-slate-900 text-xs truncate">{{ item.name }}</p>
                                <p class="text-[10px] text-stone-500 font-mono mt-0.5 truncate">{{ item.path }}</p>
                            </div>
                        </div>
                        <span class="text-xs text-stone-500 shrink-0">Open →</span>
                    </button>
                </div>

                <!-- Empty State -->
                <div v-if="!isSearching && query.trim() && results.length === 0 && semanticResults.length === 0 && taskResults.length === 0"
                    class="py-10 text-center text-stone-500 text-xs">
                    No matching files, notebooks, or tasks found for "{{ query.trim() }}".
                </div>
            </div>
        </div>
    </div>
    `,
};
