import { ref, onMounted } from 'vue';
import { convertNoteToPng } from '../api/client.js';

export default {
    props: ['file', 'isSelected', 'processingStatus'],
    emits: ['open', 'select', 'rename'],
    setup(props) {
        const coverUrl = ref(null);

        const loadCover = async () => {
            if (props.file && props.file.extension === 'note') {
                try {
                    const pages = await convertNoteToPng(props.file.id);
                    if (pages && pages.length > 0) {
                        coverUrl.value = pages[0].url;
                    }
                } catch (e) {
                    // Fallback to vector icon
                }
            }
        };

        onMounted(loadCover);

        return { coverUrl };
    },
    methods: {
        formatSize(bytes) {
            if (!bytes || bytes === '0' || bytes === 0) return '';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
    },
    template: `
    <div class="group file-card bg-white dark:bg-slate-900 rounded-2xl border border-slate-200/80 dark:border-slate-800 shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all cursor-pointer overflow-hidden flex flex-col relative" :class="{'ring-2 ring-indigo-500 bg-indigo-50/30 dark:bg-indigo-950/30': isSelected}">
        <!-- Selection Checkbox -->
        <div class="absolute top-3 left-3 z-20 opacity-0 group-hover:opacity-100 transition-opacity" :class="{'opacity-100': isSelected}">
            <input type="checkbox" :checked="isSelected" @change.stop="$emit('select', file.id)" class="w-4 h-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer">
        </div>

        <!-- Preview / Folder Header Container -->
        <div class="aspect-[4/3] flex items-center justify-center relative overflow-hidden transition-all"
            :class="file.isDirectory ? 'bg-gradient-to-br from-amber-500/10 via-amber-500/5 to-transparent dark:from-amber-500/20' : 'bg-slate-100 dark:bg-slate-800'"
            @click.stop="$emit('open', file)">

            <!-- Cover image thumbnail if loaded -->
            <img v-if="coverUrl" :src="coverUrl" class="w-full h-full object-cover object-top transition-transform group-hover:scale-105" alt="Cover Preview" />

            <!-- Default Vector Icons if no cover image -->
            <template v-else>
                <!-- Folder Presentation -->
                <div v-if="file.isDirectory" class="flex flex-col items-center gap-2 p-4 text-amber-500 dark:text-amber-400 group-hover:scale-110 transition-transform">
                    <svg class="w-12 h-12 drop-shadow-sm" fill="currentColor" viewBox="0 0 20 20">
                        <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z"></path>
                    </svg>
                </div>

                <!-- Notebook File Icon -->
                <div v-else-if="file.extension === 'note'" class="p-3 bg-white/90 dark:bg-slate-800/90 backdrop-blur rounded-xl shadow-sm border border-white/50 dark:border-slate-700">
                    <svg class="w-8 h-8 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path></svg>
                </div>

                <!-- Generic File Icon -->
                <div v-else class="p-3 bg-white/80 dark:bg-slate-800/80 backdrop-blur rounded-xl shadow-sm border border-white/50 dark:border-slate-700">
                    <svg class="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path></svg>
                </div>
            </template>

            <!-- Processing Overlay -->
            <div v-if="processingStatus && processingStatus !== 'COMPLETED' && processingStatus !== 'NONE'"
                class="absolute inset-0 bg-white/80 dark:bg-slate-900/80 backdrop-blur-[2px] flex items-center justify-center z-10">
                <div class="flex flex-col items-center gap-1.5">
                    <svg class="w-6 h-6 text-indigo-600 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <span class="text-[10px] font-semibold text-indigo-700 dark:text-indigo-400 uppercase tracking-widest">{{ processingStatus }}</span>
                </div>
            </div>
        </div>

        <div class="p-3.5 flex justify-between items-start gap-2">
            <div class="min-w-0 flex-1" @click.stop="$emit('open', file)">
                <h3 class="font-semibold text-slate-900 dark:text-slate-100 truncate text-sm" :title="file.name">{{ file.name }}</h3>
                <p class="text-xs text-slate-400 dark:text-slate-500 mt-0.5 font-medium">
                    <template v-if="file.isDirectory">Folder</template>
                    <template v-else>{{ file.extension ? file.extension.toUpperCase() : 'FILE' }}<span v-if="formatSize(file.size)"> · {{ formatSize(file.size) }}</span></template>
                </p>
            </div>
            <button @click.stop="$emit('rename', file)" class="p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors opacity-0 group-hover:opacity-100">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
            </button>
        </div>
    </div>
    `
}
