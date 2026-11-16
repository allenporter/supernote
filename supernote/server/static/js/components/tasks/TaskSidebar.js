export default {
    name: 'TaskSidebar',
    props: {
        taskGroups: {
            type: Array,
            required: true,
        },
        selectedFilter: {
            type: String,
            required: true,
        },
        selectedGroupId: {
            type: [String, Number],
            default: null,
        },
        openTasksCount: {
            type: Number,
            default: 0,
        },
        todayTasksCount: {
            type: Number,
            default: 0,
        },
        highPriorityCount: {
            type: Number,
            default: 0,
        },
        completedTasksCount: {
            type: Number,
            default: 0,
        },
        groupTaskCounts: {
            type: Object,
            default: () => ({}),
        },
    },
    emits: ['select-filter', 'select-group', 'create-group', 'delete-group', 'open-ics'],
    /**
     * @param {Record<string, any>} props
     */
    setup(props) {
        /**
         * @param {string | number} groupId
         */
        function getTaskCountForGroup(groupId) {
            return props.groupTaskCounts[String(groupId)] || 0;
        }

        /**
         * @param {string | number} groupId
         */
        function isGroupSelected(groupId) {
            return (
                props.selectedGroupId !== null && String(props.selectedGroupId) === String(groupId)
            );
        }

        return {
            getTaskCountForGroup,
            isGroupSelected,
        };
    },
    template: `
    <aside class="w-full md:w-64 flex-shrink-0">
        <div class="bg-white rounded-2xl border border-stone-200/90 shadow-sm p-4 space-y-5">
            <!-- Views / Filters -->
            <div>
                <h3 class="text-[11px] font-bold text-stone-500 uppercase tracking-wider px-2.5 mb-2">Views</h3>
                <nav class="space-y-1">
                    <button @click="$emit('select-filter', 'all')" type="button"
                        :class="selectedFilter === 'all' && selectedGroupId === null ? 'bg-slate-900 text-white font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                        class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors">
                        <span class="flex items-center gap-2.5">
                            <svg class="w-4 h-4 opacity-80" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"></path>
                            </svg>
                            All Tasks
                        </span>
                        <span :class="selectedFilter === 'all' && selectedGroupId === null ? 'bg-white/20 text-white' : 'bg-stone-100 text-stone-600'"
                            class="text-[11px] font-mono px-2 py-0.5 rounded-md tabular-nums">{{ openTasksCount }}</span>
                    </button>

                    <button @click="$emit('select-filter', 'today')" type="button"
                        :class="selectedFilter === 'today' ? 'bg-slate-900 text-white font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                        class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors">
                        <span class="flex items-center gap-2.5">
                            <svg class="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                            </svg>
                            Due Today
                        </span>
                        <span :class="selectedFilter === 'today' ? 'bg-white/20 text-white' : 'bg-stone-100 text-stone-600'"
                            class="text-[11px] font-mono px-2 py-0.5 rounded-md tabular-nums">{{ todayTasksCount }}</span>
                    </button>

                    <button @click="$emit('select-filter', 'high')" type="button"
                        :class="selectedFilter === 'high' ? 'bg-slate-900 text-white font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                        class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors">
                        <span class="flex items-center gap-2.5">
                            <svg class="w-4 h-4 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
                            </svg>
                            High Priority
                        </span>
                        <span :class="selectedFilter === 'high' ? 'bg-white/20 text-white' : 'bg-rose-50 text-rose-700 font-bold'"
                            class="text-[11px] font-mono px-2 py-0.5 rounded-md tabular-nums">{{ highPriorityCount }}</span>
                    </button>

                    <button @click="$emit('select-filter', 'completed')" type="button"
                        :class="selectedFilter === 'completed' ? 'bg-slate-900 text-white font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                        class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors">
                        <span class="flex items-center gap-2.5">
                            <svg class="w-4 h-4 text-stone-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                            </svg>
                            Completed
                        </span>
                        <span :class="selectedFilter === 'completed' ? 'bg-white/20 text-white' : 'bg-stone-100 text-stone-600'"
                            class="text-[11px] font-mono px-2 py-0.5 rounded-md tabular-nums">{{ completedTasksCount }}</span>
                    </button>
                </nav>
            </div>

            <!-- Task Groups -->
            <div class="border-t border-stone-100 pt-4">
                <div class="flex items-center justify-between px-2.5 mb-2">
                    <h3 class="text-[11px] font-bold text-stone-500 uppercase tracking-wider">Task Lists</h3>
                    <button @click="$emit('create-group')" type="button"
                        class="text-slate-900 hover:text-stone-600 text-xs font-semibold flex items-center gap-1">
                        + New
                    </button>
                </div>
                <nav class="space-y-1">
                    <div v-for="group in taskGroups" :key="group.id" class="group flex items-center justify-between">
                        <button @click="$emit('select-group', group.id)" type="button"
                            :class="isGroupSelected(group.id) ? 'bg-stone-200/80 text-slate-900 font-semibold' : 'text-stone-600 hover:bg-stone-100/80 hover:text-slate-900'"
                            class="flex-grow flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-colors text-left truncate">
                            <span class="truncate">{{ group.title }}</span>
                            <span class="text-[11px] font-mono px-2 py-0.5 rounded-md bg-stone-100 text-stone-600 ml-2 tabular-nums">{{ getTaskCountForGroup(group.id) }}</span>
                        </button>
                        <button @click.stop="$emit('delete-group', group)" type="button"
                            :aria-label="'Delete list ' + group.title"
                            class="hover-reveal text-stone-500 hover:text-rose-600 p-1.5 rounded-lg hover:bg-rose-50 transition-colors" title="Delete List">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                            </svg>
                        </button>
                    </div>
                </nav>
            </div>

            <!-- Export ICS Feed Sidebar Link -->
            <div class="border-t border-stone-100 pt-4">
                <button @click="$emit('open-ics')" type="button"
                    class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs text-stone-600 hover:text-slate-900 hover:bg-stone-100/80 transition-colors">
                    <span class="flex items-center gap-2.5 font-medium">
                        <svg class="w-4 h-4 text-stone-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
                        </svg>
                        Export .ics Feed
                    </span>
                    <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-stone-100 text-stone-600 font-semibold border border-stone-200/70">iCal</span>
                </button>
            </div>
        </div>
    </aside>
    `,
};
