export default {
    props: ['file'],
    template: `
    <div class="group file-card bg-white rounded-3xl border border-slate-200 shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all cursor-pointer overflow-hidden flex flex-col">
        <div class="aspect-[4/3] bg-slate-100 flex items-center justify-center p-8 relative transition-all bg-[url('https://www.transparenttextures.com/patterns/notebook.png')]">
            <div v-if="file.extension === 'note'" class="p-4 bg-white/80 backdrop-blur rounded-2xl shadow-lg border border-white/50">
                <svg class="w-12 h-12 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path></svg>
            </div>
            <div v-else-if="file.isDirectory" class="p-4 bg-amber-50 text-amber-500 rounded-2xl shadow-md border border-white/50">
                 <svg class="w-10 h-10" fill="currentColor" viewBox="0 0 20 20"><path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z"></path></svg>
            </div>
            <div v-else class="p-4 bg-white/80 backdrop-blur rounded-2xl shadow-lg border border-white/50">
                <svg class="w-12 h-12 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path></svg>
            </div>
        </div>
        <div class="p-5">
            <h3 class="font-bold text-slate-800 truncate">{{ file.name }}</h3>
            <p class="text-xs text-slate-400 mt-1 uppercase tracking-wider font-semibold">
                {{ file.isDirectory ? 'Folder' : file.extension }} · {{ file.size }}
            </p>
        </div>
    </div>
    `
}
