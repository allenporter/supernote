import FileCard from './FileCard.js';

export default {
    components: {
        FileCard
    },
    props: {
        recentNotes: { type: Array, default: () => [] },
        processingStatuses: { type: Object, default: () => ({}) }
    },
    emits: ['open-file', 'open-search', 'navigate-tab'],
    template: `
    <div class="space-y-8 animate-fade-in max-w-6xl mx-auto w-full">
        <!-- Clean Minimal Header -->
        <div class="flex flex-wrap items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
            <div>
                <h2 class="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">Notebooks & Library</h2>
                <p class="text-sm text-slate-500 dark:text-slate-400 mt-1">Overview of your synced Supernote notebooks, folders, and active tasks</p>
            </div>
        </div>

        <!-- Quick Nav & Recent Notes Grid -->
        <div class="space-y-4">
            <div class="flex items-center justify-between">
                <h3 class="text-xs font-semibold text-slate-900 dark:text-white uppercase tracking-wider">Recent Notebooks</h3>
                <button @click="$emit('navigate-tab', 'explorer')" class="text-xs text-indigo-600 dark:text-indigo-400 hover:underline font-medium">
                    View all files →
                </button>
            </div>

            <div v-if="recentNotes.length > 0" class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
                <file-card v-for="file in recentNotes" :key="file.id" :file="file"
                    :processing-status="processingStatuses[file.id]"
                    @open="$emit('open-file', $event)"></file-card>
            </div>

            <!-- Clean Empty State -->
            <div v-else class="py-12 px-6 bg-white dark:bg-slate-900 rounded-2xl border border-slate-200/80 dark:border-slate-800 text-center shadow-sm">
                <div class="w-10 h-10 bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 rounded-xl flex items-center justify-center mx-auto mb-3">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
                </div>
                <h4 class="text-sm font-semibold text-slate-900 dark:text-white mb-1">No recent notebooks found</h4>
                <p class="text-xs text-slate-500 dark:text-slate-400 mb-4">Upload a .note notebook file or create a folder to get started.</p>
                <button @click="$emit('navigate-tab', 'explorer')" class="px-3.5 py-1.5 bg-slate-900 dark:bg-white text-white dark:text-slate-900 rounded-xl text-xs font-medium hover:bg-slate-800 transition-colors shadow-sm">
                    Go to Files Explorer
                </button>
            </div>
        </div>
    </div>
    `
}
