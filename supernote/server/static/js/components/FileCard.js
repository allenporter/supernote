export default {
    props: ['file', 'isSelected', 'processingStatus'],
    methods: {
        formatSize(bytes) {
            if (!bytes || bytes === '0' || bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
    },
    template: `
    <div class="group file-card bg-white rounded-3xl border border-slate-200 shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all cursor-pointer overflow-hidden flex flex-col relative" :class="{'ring-2 ring-indigo-500 bg-indigo-50/30': isSelected}">
        <!-- Selection Checkbox -->
        <div class="absolute top-4 left-4 z-10 opacity-0 group-hover:opacity-100 transition-opacity" :class="{'opacity-100': isSelected}">
            <input type="checkbox" :checked="isSelected" @change.stop="$emit('select', file.id)" class="w-5 h-5 rounded-md border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer">
        </div>

        <div class="aspect-[4/3] bg-slate-100 flex items-center justify-center p-8 relative transition-all bg-[url('https://www.transparenttextures.com/patterns/notebook.png')]" @click.stop="$emit('open', file)">
            <div v-if="file.extension === 'note'" class="p-4 bg-white/80 backdrop-blur rounded-2xl shadow-lg border border-white/50">
                <svg class="w-12 h-12 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path></svg>
            </div>
            <div v-else-if="file.isDirectory" class="p-4 bg-amber-50 text-amber-500 rounded-2xl shadow-md border border-white/50">
                 <svg class="w-10 h-10" fill="currentColor" viewBox="0 0 20 20"><path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z"></path></svg>
            </div>
            <div v-else class="p-4 bg-white/80 backdrop-blur rounded-2xl shadow-lg border border-white/50">
                <svg class="w-12 h-12 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path></svg>
            </div>

            <!-- Processing Overlay -->
            <div v-if="processingStatus && processingStatus !== 'COMPLETED' && processingStatus !== 'NONE'"
                class="absolute inset-0 bg-white/60 backdrop-blur-[2px] flex items-center justify-center z-10">
                <div class="flex flex-col items-center gap-2">
                    <svg class="w-8 h-8 text-indigo-600 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <span class="text-[10px] font-bold text-indigo-700 uppercase tracking-widest">{{ processingStatus }}</span>
                </div>
            </div>
        </div>
        <div class="p-5 flex justify-between items-start gap-2">
            <div class="min-w-0" @click.stop="$emit('open', file)">
                <h3 class="font-bold text-slate-800 truncate" :title="file.name">{{ file.name }}</h3>
                <p class="text-xs text-slate-400 mt-1 uppercase tracking-wider font-semibold">
                    {{ file.isDirectory ? 'Folder' : file.extension }} · {{ formatSize(file.size) }}
                </p>
            </div>
            <button @click.stop="$emit('rename', file)" class="p-2 text-slate-400 hover:text-indigo-600 transition-colors opacity-0 group-hover:opacity-100">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
            </button>
        </div>
    </div>
    `
}
