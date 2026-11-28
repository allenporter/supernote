/**
 * Cross-notebook page timeline view (`TimelinePanel`).
 *
 * Displays a day-grouped visual grid of notebook pages across all folders,
 * combining device-authored creation dates with synced page edits, plus a
 * collapsible mini-calendar to jump straight to any specific day.
 */

import { computed, onMounted, ref } from 'vue';
import {
    formatTimelineDayHeading,
    getMonthCalendarMeta,
    shiftMonthKey,
    useTimeline,
} from '../composables/useTimeline.js';

const WEEKDAY_LABELS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];

export default {
    name: 'TimelinePanel',
    emits: ['close', 'open-page'],
    /**
     * @param {Record<string, never>} _props
     * @param {{ emit: (event: string, ...args: any[]) => void }} context
     */
    setup(_props, { emit }) {
        const {
            items,
            groupedDays,
            daysByDate,
            isLoading,
            isLoadingMore,
            error,
            hasMore,
            selectedDate,
            calendarMonth,
            includeBlank,
            starredOnly,
            loadMore,
            loadMonthDays,
            selectDate,
            refreshAll,
        } = useTimeline();

        const showCalendar = ref(false);

        const calendarMeta = computed(() => getMonthCalendarMeta(calendarMonth.value));

        const calendarMonthLabel = computed(() => {
            const { year, monthIndex } = calendarMeta.value;
            return new Date(year, monthIndex, 1).toLocaleDateString(undefined, {
                month: 'long',
                year: 'numeric',
            });
        });

        const calendarCells = computed(() => {
            const { year, monthIndex, daysInMonth, firstWeekday } = calendarMeta.value;
            const mm = String(monthIndex + 1).padStart(2, '0');
            /** @type {Array<{ key: string, day: number | null, iso: string | null, count: number }>} */
            const cells = [];
            for (let i = 0; i < firstWeekday; i++) {
                cells.push({ key: `pad-${i}`, day: null, iso: null, count: 0 });
            }
            for (let d = 1; d <= daysInMonth; d++) {
                const iso = `${year}-${mm}-${String(d).padStart(2, '0')}`;
                const info = daysByDate.value[iso];
                cells.push({ key: iso, day: d, iso, count: info ? info.count : 0 });
            }
            return cells;
        });

        const selectedDateLabel = computed(() =>
            selectedDate.value ? formatTimelineDayHeading(selectedDate.value) : null,
        );

        /**
         * @param {number} delta
         */
        async function stepMonth(delta) {
            await loadMonthDays(shiftMonthKey(calendarMonth.value, delta), {
                userInitiated: true,
            });
        }

        async function toggleStarredOnly() {
            starredOnly.value = !starredOnly.value;
            await refreshAll();
        }

        async function toggleIncludeBlank() {
            includeBlank.value = !includeBlank.value;
            await refreshAll();
        }

        /**
         * @param {TimelinePage} item
         */
        function handleOpenPage(item) {
            emit('open-page', {
                id: item.fileId,
                name: item.fileName,
                isDirectory: false,
                pageIndex: item.pageIndex,
            });
        }

        /**
         * @param {TimelinePage} item
         * @returns {string | null}
         */
        function activityBadgeLabel(item) {
            const hasCreated = item.sources.includes('created');
            const hasEdited = item.sources.includes('edited');
            const hasDated = item.sources.includes('dated');
            if (hasEdited && !hasCreated) return 'Edited';
            if (hasEdited && hasCreated) return 'Created · Edited';
            if (hasDated && !hasCreated && !hasEdited) return 'Dated in notes';
            return null;
        }

        onMounted(() => {
            refreshAll();
        });

        return {
            WEEKDAY_LABELS,
            items,
            groupedDays,
            isLoading,
            isLoadingMore,
            error,
            hasMore,
            selectedDate,
            selectedDateLabel,
            includeBlank,
            starredOnly,
            showCalendar,
            calendarMonthLabel,
            calendarCells,
            loadMore,
            selectDate,
            stepMonth,
            toggleStarredOnly,
            toggleIncludeBlank,
            handleOpenPage,
            activityBadgeLabel,
            refreshAll,
        };
    },
    template: `
    <div>
        <!-- Header Bar: Folders/Timeline Switcher + Filters -->
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-5 mb-6 border-b border-stone-200/80">
            <div class="flex flex-wrap items-center gap-2.5 min-w-0">
                <!-- Folders / Timeline Switcher -->
                <div class="flex items-center bg-stone-200/70 p-0.5 rounded-lg border border-stone-300/40 shrink-0">
                    <button @click="$emit('close')" type="button"
                        class="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium text-stone-600 hover:text-slate-900 transition-all">
                        <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"></path>
                        </svg>
                        <span>Folders</span>
                    </button>
                    <button type="button" aria-current="page"
                        class="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-white text-slate-900 shadow-sm transition-all">
                        <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                        </svg>
                        <span>Timeline</span>
                    </button>
                </div>

                <!-- Active Day Filter Pill -->
                <span v-if="selectedDateLabel"
                    class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-900 text-white text-xs font-medium">
                    <span>{{ selectedDateLabel }}</span>
                    <button @click="selectDate(null)" type="button" aria-label="Clear date filter"
                        class="hover:text-stone-300 transition-colors">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </span>
            </div>

            <!-- Right Filter Controls -->
            <div class="flex flex-wrap items-center gap-2 shrink-0">
                <button @click="showCalendar = !showCalendar" type="button"
                    :aria-expanded="showCalendar"
                    :class="showCalendar || selectedDate ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-stone-700 border-stone-200/90 hover:bg-stone-50'"
                    class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold border shadow-sm transition-all">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                    </svg>
                    <span>Jump to Day</span>
                </button>

                <button @click="toggleStarredOnly" type="button"
                    :aria-pressed="starredOnly"
                    :class="starredOnly ? 'bg-amber-50 text-amber-800 border-amber-300' : 'bg-white text-stone-600 border-stone-200/90 hover:bg-stone-50'"
                    class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold border shadow-sm transition-all">
                    <svg class="w-3.5 h-3.5" :fill="starredOnly ? 'currentColor' : 'none'" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"></path>
                    </svg>
                    <span>Starred</span>
                </button>

                <button @click="toggleIncludeBlank" type="button"
                    :aria-pressed="includeBlank"
                    :class="includeBlank ? 'bg-stone-200/90 text-slate-900 border-stone-300' : 'bg-white text-stone-600 border-stone-200/90 hover:bg-stone-50'"
                    class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold border shadow-sm transition-all">
                    <span>Show blank</span>
                </button>
            </div>
        </div>

        <!-- Collapsible Mini-Calendar -->
        <div v-if="showCalendar" class="mb-6 bg-white rounded-2xl border border-stone-200/90 shadow-sm p-4 max-w-sm">
            <div class="flex items-center justify-between mb-3">
                <button @click="stepMonth(-1)" type="button" aria-label="Previous month"
                    class="p-1.5 rounded-lg text-stone-600 hover:text-slate-900 hover:bg-stone-100 transition-colors">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path>
                    </svg>
                </button>
                <span class="text-sm font-semibold text-slate-900">{{ calendarMonthLabel }}</span>
                <button @click="stepMonth(1)" type="button" aria-label="Next month"
                    class="p-1.5 rounded-lg text-stone-600 hover:text-slate-900 hover:bg-stone-100 transition-colors">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                    </svg>
                </button>
            </div>
            <div class="grid grid-cols-7 gap-1 text-center text-[11px] font-medium text-stone-500 mb-1">
                <span v-for="w in WEEKDAY_LABELS" :key="w">{{ w }}</span>
            </div>
            <div class="grid grid-cols-7 gap-1">
                <template v-for="cell in calendarCells" :key="cell.key">
                    <div v-if="cell.day === null" class="h-8"></div>
                    <button v-else @click="selectDate(cell.iso)" type="button"
                        :title="cell.count > 0 ? cell.iso + ' (' + cell.count + ' pages)' : cell.iso"
                        :class="selectedDate === cell.iso
                            ? 'bg-slate-900 text-white font-semibold'
                            : cell.count > 0
                                ? 'bg-stone-100 text-slate-900 font-semibold hover:bg-stone-200'
                                : 'text-stone-400 hover:bg-stone-50'"
                        class="h-8 rounded-lg text-xs flex flex-col items-center justify-center transition-colors relative">
                        <span>{{ cell.day }}</span>
                        <span v-if="cell.count > 0"
                            :class="selectedDate === cell.iso ? 'bg-white' : 'bg-slate-900'"
                            class="w-1 h-1 rounded-full mt-0.5"></span>
                    </button>
                </template>
            </div>
        </div>

        <!-- Error Banner -->
        <div v-if="error" class="mb-6 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl text-sm flex items-center justify-between gap-3">
            <span>{{ error }}</span>
            <button @click="refreshAll" type="button"
                class="px-3 py-1 bg-white border border-red-200 rounded-lg text-xs font-semibold hover:bg-red-50 transition-colors">
                Retry
            </button>
        </div>

        <!-- Loading State -->
        <div v-if="isLoading" class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
            <div v-for="n in 8" :key="n" class="bg-white rounded-2xl border border-stone-200/80 p-3 animate-pulse">
                <div class="aspect-[3/4] bg-stone-100 rounded-xl mb-3"></div>
                <div class="h-3.5 bg-stone-200/80 rounded w-3/4 mb-1.5"></div>
                <div class="h-3 bg-stone-100 rounded w-1/3"></div>
            </div>
        </div>

        <!-- Empty State -->
        <div v-else-if="groupedDays.length === 0"
            class="bg-white rounded-2xl border border-stone-200/80 p-10 text-center">
            <svg class="w-10 h-10 text-stone-300 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
            </svg>
            <p class="text-sm font-semibold text-slate-900 mb-1">
                {{ selectedDate ? 'No note pages found on ' + selectedDateLabel : 'No note pages in your timeline yet' }}
            </p>
            <p class="text-xs text-stone-500">
                {{ selectedDate ? 'Try clearing the date filter or choosing another day.' : 'Sync a Supernote notebook to browse your pages chronologically.' }}
            </p>
            <button v-if="selectedDate" @click="selectDate(null)" type="button"
                class="mt-4 px-3.5 py-1.5 bg-slate-900 text-white rounded-lg text-xs font-semibold hover:bg-slate-800 transition-colors">
                Show all dates
            </button>
        </div>

        <!-- Day-Grouped Timeline Feed -->
        <div v-else class="space-y-8">
            <section v-for="group in groupedDays" :key="group.date">
                <div class="flex items-baseline justify-between mb-3">
                    <h2 class="text-sm font-bold text-slate-900 tracking-tight">{{ group.label }}</h2>
                    <span class="text-xs font-mono text-stone-500">
                        {{ group.items.length }} {{ group.items.length === 1 ? 'page' : 'pages' }}
                    </span>
                </div>

                <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                    <button v-for="item in group.items"
                        :key="group.date + ':' + item.fileId + ':' + item.pageIndex"
                        @click="handleOpenPage(item)" type="button"
                        class="group text-left bg-white rounded-2xl border border-stone-200/90 hover:border-slate-400 shadow-sm hover:shadow-md transition-all overflow-hidden flex flex-col focus:outline-none focus:ring-2 focus:ring-slate-900/20">
                        <div class="relative aspect-[3/4] min-h-[180px] bg-stone-50 border-b border-stone-100 overflow-hidden flex items-center justify-center">
                            <img v-if="item.imageUrl" :src="item.imageUrl" loading="lazy"
                                :alt="item.fileName + ' page ' + (item.pageIndex + 1)"
                                class="w-full h-full object-contain bg-white group-hover:scale-[1.02] transition-transform duration-200" />
                            <div v-else class="flex flex-col items-center justify-center text-stone-400 px-3 text-center">
                                <svg class="w-8 h-8 mb-1.5 text-stone-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                                </svg>
                                <span class="text-[11px]">Page {{ item.pageIndex + 1 }}</span>
                            </div>

                            <!-- Top-right Provenance & Star Badges -->
                            <div class="absolute top-2 right-2 flex items-center gap-1">
                                <span v-if="activityBadgeLabel(item)"
                                    class="px-1.5 py-0.5 rounded-md bg-slate-900/80 text-white text-[10px] font-medium backdrop-blur-sm">
                                    {{ activityBadgeLabel(item) }}
                                </span>
                                <span v-if="item.hasFiveStar" title="Starred page"
                                    class="p-1 rounded-md bg-amber-100/95 text-amber-600 shadow-sm">
                                    <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
                                        <path d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"></path>
                                    </svg>
                                </span>
                            </div>
                        </div>

                        <div class="p-2.5 flex-1 flex flex-col justify-between gap-1.5">
                            <div class="flex items-baseline justify-between gap-2 min-w-0">
                                <span class="text-xs font-semibold text-slate-900 truncate" :title="item.fileName">
                                    {{ item.fileName }}
                                </span>
                                <span class="text-[11px] font-mono text-stone-500 shrink-0">
                                    p. {{ item.pageIndex + 1 }}
                                </span>
                            </div>
                            <div v-if="item.summary" class="text-[11px] text-stone-600 leading-snug line-clamp-2">
                                {{ item.summary }}
                            </div>
                            <div v-if="item.keywords.length > 0" class="flex flex-wrap gap-1">
                                <span v-for="kw in item.keywords.slice(0, 2)" :key="kw"
                                    class="px-1.5 py-0.5 rounded bg-stone-100 text-stone-600 text-[10px] font-medium truncate max-w-full">
                                    #{{ kw }}
                                </span>
                            </div>
                        </div>
                    </button>
                </div>
            </section>

            <!-- Pagination Footer -->
            <div v-if="hasMore" class="flex justify-center pt-2">
                <button @click="loadMore" :disabled="isLoadingMore" type="button"
                    class="px-4 py-2 bg-white hover:bg-stone-50 text-slate-800 border border-stone-200/90 rounded-xl text-xs font-semibold shadow-sm transition-all disabled:opacity-60">
                    {{ isLoadingMore ? 'Loading...' : 'Load more pages' }}
                </button>
            </div>
        </div>
    </div>
    `,
};
