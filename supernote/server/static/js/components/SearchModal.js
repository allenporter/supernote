import { ref, nextTick } from 'vue';
import { searchFiles, searchSemantic } from '../api/client.js';
import { fetchTasks } from '../api/schedule.js';

export default {
    emits: ['close', 'select-file', 'select-task'],
    setup(props, { emit }) {
        const query = ref('');
        const isSearching = ref(false);
        const results = ref([]);
        const semanticResults = ref([]);
        const taskResults = ref([]);
        const searchInput = ref(null);

        let searchTimeout = null;

        const handleSearch = () => {
            if (searchTimeout) clearTimeout(searchTimeout);
            if (!query.value.trim()) {
                results.value = [];
                semanticResults.value = [];
                taskResults.value = [];
                isSearching.value = false;
                return;
            }

            isSearching.value = true;
            searchTimeout = setTimeout(async () => {
                try {
                    const q = query.value.trim().toLowerCase();
                    const [fileMatches, vectorMatches, { tasks: allTasks }] = await Promise.all([
                        searchFiles(q).catch(() => []),
                        searchSemantic(q).catch(() => []),
                        fetchTasks().catch(() => ({ tasks: [] }))
                    ]);

                    results.value = fileMatches.map(f => ({
                        id: f.id,
                        name: f.name || f.fileName,
                        path: f.path_display || f.parent_path || f.name,
                        isDirectory: f.tag === 'folder' || f.isDirectory,
                        size: f.size,
                        extension: f.name?.endsWith('.note') ? 'note' : null
                    }));

                    semanticResults.value = vectorMatches;

                    taskResults.value = allTasks.filter(t =>
                        t.title.toLowerCase().includes(q) || (t.detail && t.detail.toLowerCase().includes(q))
                    );
                } catch (e) {
                    console.error("Search failed:", e);
                } finally {
                    isSearching.value = false;
                }
            }, 300);
        };

        const handleSelect = (item) => {
            emit('select-file', item);
            emit('close');
        };

        const handleSelectTaskItem = (task) => {
            emit('select-task', task);
            emit('close');
        };

        nextTick(() => {
            if (searchInput.value) searchInput.value.focus();
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
            handleSelectTaskItem
        };
    },
    template: `
    <div class="fixed inset-0 z-[100] flex items-start justify-center pt-16 px-4 bg-black/30 backdrop-blur-[2px] animate-fade-in"
        @click.self="$emit('close')">
        <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[80vh]">
            <!-- Unified Search Header -->
            <div class="p-3.5 border-b border-slate-100 dark:border-slate-800 flex items-center gap-3">
                <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                <input ref="searchInput" v-model="query" @input="handleSearch" type="text"
                    placeholder="Global Search (notebooks, transcripts, files, or tasks)..."
                    class="w-full bg-transparent text-slate-900 dark:text-white placeholder-slate-400 outline-none text-sm font-medium">
                <kbd class="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-800 text-slate-400 text-[10px] font-mono rounded border border-slate-200 dark:border-slate-700">ESC</kbd>
            </div>

            <!-- Results Content Area -->
            <div class="p-4 overflow-y-auto space-y-4 flex-1">
                <!-- Searching Indicator -->
                <div v-if="isSearching" class="py-8 text-center text-slate-400 text-xs">
                    <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-slate-700 dark:border-slate-200 mx-auto mb-2"></div>
                    Searching notebooks, files, and tasks...
                </div>

                <!-- Matching Tasks -->
                <div v-if="!isSearching && taskResults.length > 0" class="space-y-1.5">
                    <div class="text-[11px] font-bold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider px-1">
                        ✅ Matching Tasks
                    </div>
                    <div v-for="t in taskResults" :key="t.id" @click="handleSelectTaskItem(t)"
                        class="p-2.5 bg-emerald-50/50 dark:bg-emerald-950/30 hover:bg-emerald-100/60 dark:hover:bg-emerald-900/40 rounded-xl border border-emerald-100 dark:border-emerald-900/50 cursor-pointer transition-all flex items-center justify-between">
                        <div>
                            <p class="font-semibold text-slate-900 dark:text-white text-xs">{{ t.title }}</p>
                            <p v-if="t.detail" class="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5 truncate">{{ t.detail }}</p>
                        </div>
                        <span class="text-[10px] bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 font-bold px-2 py-0.5 rounded-md">Task</span>
                    </div>
                </div>

                <!-- Semantic Content Results -->
                <div v-if="!isSearching && semanticResults.length > 0" class="space-y-1.5">
                    <div class="text-[11px] font-bold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider px-1">
                        📄 Semantic Notebook Content
                    </div>
                    <div v-for="res in semanticResults" :key="res.page_id || res.file_id"
                        @click="handleSelect({ id: res.file_id, name: res.file_name, isDirectory: false, extension: 'note' })"
                        class="p-2.5 bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl border border-slate-200/80 dark:border-slate-800 cursor-pointer transition-all">
                        <div class="flex items-center justify-between">
                            <span class="font-semibold text-slate-900 dark:text-white text-xs">📄 {{ res.file_name }} (Page {{ res.page_index }})</span>
                            <span class="text-[10px] text-slate-400 font-mono">Match: {{ Math.round(res.score * 100) }}%</span>
                        </div>
                        <p class="text-[11px] text-slate-600 dark:text-slate-300 mt-1 line-clamp-2">{{ res.text_preview }}</p>
                    </div>
                </div>

                <!-- Keyword File Matches -->
                <div v-if="!isSearching && results.length > 0" class="space-y-1.5">
                    <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider px-1">
                        📁 Files & Folders
                    </div>
                    <div v-for="item in results" :key="item.id" @click="handleSelect(item)"
                        class="p-2.5 bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl border border-slate-200/80 dark:border-slate-800 cursor-pointer transition-all flex items-center justify-between">
                        <div>
                            <p class="font-semibold text-slate-900 dark:text-white text-xs">
                                {{ item.isDirectory ? '📁' : '📄' }} {{ item.name }}
                            </p>
                            <p class="text-[10px] text-slate-400 font-mono mt-0.5">{{ item.path }}</p>
                        </div>
                        <span class="text-xs text-slate-400">Open</span>
                    </div>
                </div>

                <!-- Empty State -->
                <div v-if="!isSearching && query && results.length === 0 && semanticResults.length === 0 && taskResults.length === 0"
                    class="py-10 text-center text-slate-400 text-xs">
                    No matching files, notebooks, or tasks found for "{{ query }}".
                </div>
            </div>
        </div>
    </div>
    `
}
