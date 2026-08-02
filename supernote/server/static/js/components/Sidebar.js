export default {
    props: {
        activeTab: { type: String, default: 'dashboard' },
        breadcrumbs: { type: Array, default: () => [{ id: '0', name: 'Root' }] },
        subfolders: { type: Array, default: () => [] },
        currentDirectoryId: { type: String, default: '0' },
        isDarkMode: { type: Boolean, default: false },
        isOpen: { type: Boolean, default: false }
    },
    emits: ['navigate-tab', 'navigate-folder', 'toggle-theme', 'toggle-system', 'close'],
    setup(props, { emit }) {
        const handleNavTab = (tab) => {
            emit('navigate-tab', tab);
            emit('close');
        };
        const handleNavFolder = (folder) => {
            emit('navigate-folder', folder);
            emit('close');
        };
        return { handleNavTab, handleNavFolder };
    },
    template: `
    <aside :class="isOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'"
        class="fixed md:static inset-y-0 left-0 z-40 w-60 border-r border-slate-200 dark:border-slate-800 flex flex-col h-full bg-white dark:bg-slate-900 transition-transform duration-200 ease-in-out shadow-xl md:shadow-none">

        <!-- Clean Brand Header -->
        <div class="p-4 flex items-center justify-between border-b border-slate-100 dark:border-slate-800">
            <div class="flex items-center gap-2.5 cursor-pointer" @click="handleNavTab('dashboard')">
                <div class="w-7 h-7 bg-slate-900 dark:bg-white text-white dark:text-slate-900 rounded-lg flex items-center justify-center font-bold text-xs">
                    S
                </div>
                <h1 class="text-sm font-semibold text-slate-900 dark:text-white tracking-tight">
                    Supernote Knowledge Hub
                </h1>
            </div>
            <!-- Close Button for Mobile Drawer -->
            <button @click="$emit('close')" class="md:hidden p-1 text-slate-400 hover:text-slate-700">
                ✕
            </button>
        </div>

        <!-- Navigation Links -->
        <nav class="p-2 space-y-0.5">
            <button @click="handleNavTab('dashboard')"
                :class="activeTab === 'dashboard' ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-white font-semibold' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50'"
                class="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-all text-left">
                <svg class="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>
                <span>Dashboard</span>
            </button>

            <button @click="handleNavTab('explorer')"
                :class="activeTab === 'explorer' ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-white font-semibold' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50'"
                class="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-all text-left">
                <svg class="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"></path></svg>
                <span>Files</span>
            </button>

            <button @click="handleNavTab('tasks')"
                :class="activeTab === 'tasks' ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-white font-semibold' : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50'"
                class="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-all text-left">
                <svg class="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"></path></svg>
                <span>Tasks & Schedule</span>
            </button>
        </nav>

        <!-- Folder Path Navigation (Clean Tree Hierarchy) -->
        <div class="px-3 pt-3 pb-2 border-t border-slate-100 dark:border-slate-800 flex-1 overflow-y-auto">
            <div class="mb-1 px-1 flex items-center justify-between">
                <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Folder Path</span>
            </div>

            <div class="space-y-0.5 text-xs">
                <!-- Breadcrumbs Path Trail -->
                <div v-for="(crumb, idx) in breadcrumbs" :key="crumb.id">
                    <button @click="handleNavFolder({ id: crumb.id, name: crumb.name })"
                        :style="{ paddingLeft: (idx * 12 + 8) + 'px' }"
                        :class="currentDirectoryId === crumb.id ? 'text-indigo-600 dark:text-indigo-400 font-bold bg-slate-100 dark:bg-slate-800/80' : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'"
                        class="w-full flex items-center gap-1.5 py-1.5 rounded-md transition-colors text-left">
                        <svg v-if="idx === 0" class="w-3.5 h-3.5 text-slate-400 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z"></path></svg>
                        <svg v-else class="w-3.5 h-3.5 text-amber-500/80 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z"></path></svg>
                        <span class="truncate">{{ idx === 0 ? 'Root' : crumb.name }}</span>
                    </button>
                </div>

                <!-- Subfolders under Current Folder -->
                <div v-for="folder in subfolders" :key="folder.id">
                    <button @click="handleNavFolder(folder)"
                        :style="{ paddingLeft: (breadcrumbs.length * 12 + 8) + 'px' }"
                        class="w-full flex items-center gap-1.5 py-1.5 rounded-md text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-colors text-left">
                        <svg class="w-3.5 h-3.5 text-slate-400 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z"></path></svg>
                        <span class="truncate">{{ folder.name }}</span>
                    </button>
                </div>
            </div>
        </div>

        <!-- Clean Footer -->
        <div class="p-2 border-t border-slate-100 dark:border-slate-800 space-y-0.5">
            <button @click="$emit('toggle-system')"
                class="w-full flex items-center justify-between px-2.5 py-1.5 text-xs font-medium text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 rounded-md transition-colors">
                <span class="flex items-center gap-2">
                    <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                    System Status
                </span>
            </button>

            <button @click="$emit('toggle-theme')"
                class="w-full flex items-center justify-between px-2.5 py-1.5 text-xs font-medium text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 rounded-md transition-colors">
                <span>{{ isDarkMode ? '🌙 Dark' : '☀️ Light' }}</span>
            </button>
        </div>
    </aside>
    `
}
