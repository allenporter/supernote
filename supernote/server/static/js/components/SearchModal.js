import { ref, nextTick, onMounted, onUnmounted } from 'vue';
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
        let activeSearchSeq = 0;

        const handleKeydown = (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                emit('close');
            }
        };

        const handleSearch = () => {
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
            searchTimeout = setTimeout(async () => {
                try {
                    const qLower = trimmed.toLowerCase();
                    const [fileMatches, vectorMatches, { tasks: allTasks }] = await Promise.all([
                        searchFiles(trimmed).catch(() => []),
                        searchSemantic(trimmed).catch(() => []),
                        fetchTasks().catch(() => ({ tasks: [] }))
                    ]);
                    if (seq !== activeSearchSeq) return;

                    results.value = fileMatches.map(f => {
                        const fileName = f.name || f.fileName || '';
                        const isDir = f.tag === 'folder' || f.isDirectory;
                        const ext = !isDir && fileName.includes('.')
                            ? fileName.split('.').pop().toLowerCase()
                            : null;
                        return {
                            id: f.id,
                            name: fileName,
                            path: f.path_display || f.parent_path || fileName,
                            isDirectory: isDir,
                            size: f.size,
                            extension: ext
                        };
                    });

                    semanticResults.value = vectorMatches.map((r, idx) => {
                        const fileId = r.fileId ?? r.file_id;
                        const fileName = r.fileName ?? r.file_name ?? `Notebook ${fileId}`;
                        const pageIndex = typeof r.pageIndex === 'number'
                            ? r.pageIndex
                            : (typeof r.page_index === 'number' ? r.page_index : 0);
                        const ext = fileName.includes('.')
                            ? fileName.split('.').pop().toLowerCase()
                            : 'note';
                        return {
                            key: r.pageId ?? r.page_id ?? `${fileId}-${pageIndex}-${idx}`,
                            fileId: String(fileId),
                            fileName,
                            extension: ext,
                            pageIndex,
                            pageNumber: pageIndex + 1,
                            score: typeof r.score === 'number' ? r.score : 0,
                            textPreview: r.textPreview ?? r.text_preview ?? '',
                            date: r.date || null
                        };
                    });

                    taskResults.value = allTasks.filter(t =>
                        t.title.toLowerCase().includes(qLower) || (t.detail && t.detail.toLowerCase().includes(qLower))
                    );
                } catch (e) {
                    if (seq !== activeSearchSeq) return;
                    console.error("Search failed:", e);
                } finally {
                    if (seq === activeSearchSeq) {
                        isSearching.value = false;
                    }
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

        onMounted(() => {
            window.addEventListener('keydown', handleKeydown);
            nextTick(() => {
                if (searchInput.value) searchInput.value.focus();
            });
        });

        onUnmounted(() => {
            window.removeEventListener('keydown', handleKeydown);
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
            handleSelectTaskItem
        };
    },
    template: `
    <div class="fixed inset-0 z-[100] flex items-start justify-center pt-16 px-4 bg-black/30 backdrop-blur-[2px] animate-fade-in"
        @click.self="$emit('close')">
        <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[80vh]"
            role="dialog" aria-modal="true" aria-label="Global Search">
            <!-- Unified Search Header -->
            <div class="p-3.5 border-b border-slate-100 dark:border-slate-800 flex items-center gap-3">
                <svg class="w-4 h-4 text-slate-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                <input ref="searchInput" v-model="query" @input="handleSearch" type="text"
                    placeholder="Global Search (notebooks, transcripts, files, or tasks)..."
                    class="w-full bg-transparent text-slate-900 dark:text-white placeholder-slate-400 outline-none text-sm font-medium">
                <button type="button" @click="$emit('close')" title="Close search (Escape)"
                    class="px-1.5 py-0.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-400 hover:text-slate-600 text-[10px] font-mono rounded border border-slate-200 dark:border-slate-700 transition-colors">
                    ESC
                </button>
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
                    <button type="button" v-for="t in taskResults" :key="t.id" @click="handleSelectTaskItem(t)"
                        class="w-full text-left p-2.5 bg-emerald-50/50 dark:bg-emerald-950/30 hover:bg-emerald-100/60 dark:hover:bg-emerald-900/40 rounded-xl border border-emerald-100 dark:border-emerald-900/50 cursor-pointer transition-all flex items-center justify-between gap-3">
                        <div class="min-w-0">
                            <p class="font-semibold text-slate-900 dark:text-white text-xs truncate">{{ t.title }}</p>
                            <p v-if="t.detail" class="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5 truncate">{{ t.detail }}</p>
                        </div>
                        <span class="text-[10px] bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 font-bold px-2 py-0.5 rounded-md shrink-0">Task</span>
                    </button>
                </div>

                <!-- Semantic Content Results -->
                <div v-if="!isSearching && semanticResults.length > 0" class="space-y-1.5">
                    <div class="text-[11px] font-bold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider px-1">
                        📄 Semantic Notebook Content
                    </div>
                    <button type="button" v-for="res in semanticResults" :key="res.key"
                        @click="handleSelect({ id: res.fileId, name: res.fileName, isDirectory: false, extension: res.extension, pageIndex: res.pageIndex })"
                        class="w-full text-left p-2.5 bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl border border-slate-200/80 dark:border-slate-800 cursor-pointer transition-all">
                        <div class="flex items-center justify-between gap-2">
                            <div class="flex items-center gap-2 min-w-0">
                                <span class="font-semibold text-slate-900 dark:text-white text-xs truncate">📄 {{ res.fileName }}</span>
                                <span class="px-1.5 py-0.5 rounded bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 text-[10px] font-mono font-semibold shrink-0">
                                    Page {{ res.pageNumber }}
                                </span>
                                <span v-if="res.date" class="text-[10px] text-slate-400 font-mono shrink-0">{{ res.date }}</span>
                            </div>
                            <span class="text-[10px] text-slate-400 font-mono shrink-0">Match: {{ Math.round(res.score * 100) }}%</span>
                        </div>
                        <p class="text-[11px] text-slate-600 dark:text-slate-300 mt-1 line-clamp-2">{{ res.textPreview }}</p>
                    </button>
                </div>

                <!-- Keyword File Matches -->
                <div v-if="!isSearching && results.length > 0" class="space-y-1.5">
                    <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider px-1">
                        📁 Files & Folders
                    </div>
                    <button type="button" v-for="item in results" :key="item.id" @click="handleSelect(item)"
                        class="w-full text-left p-2.5 bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl border border-slate-200/80 dark:border-slate-800 cursor-pointer transition-all flex items-center justify-between gap-3">
                        <div class="min-w-0">
                            <p class="font-semibold text-slate-900 dark:text-white text-xs truncate">
                                {{ item.isDirectory ? '📁' : '📄' }} {{ item.name }}
                            </p>
                            <p class="text-[10px] text-slate-400 font-mono mt-0.5 truncate">{{ item.path }}</p>
                        </div>
                        <span class="text-xs text-slate-400 shrink-0">Open</span>
                    </button>
                </div>

                <!-- Empty State -->
                <div v-if="!isSearching && query.trim() && results.length === 0 && semanticResults.length === 0 && taskResults.length === 0"
                    class="py-10 text-center text-slate-400 text-xs">
                    No matching files, notebooks, or tasks found for "{{ query.trim() }}".
                </div>
            </div>
        </div>
    </div>
    `
}
