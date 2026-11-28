/**
 * Composable managing cross-notebook timeline pages, filters, and calendar day counts.
 */

import { computed, ref } from 'vue';
import { onLogout } from '../api/http.js';
import { fetchTimelineDays, fetchTimelinePages } from '../api/timeline.js';
import { getErrorMessage } from '../utils/format.js';

/**
 * Compute inclusive YYYY-MM-DD start/end bounds for a `YYYY-MM` month string.
 * @param {string} monthKey
 * @returns {{ startDate: string, endDate: string, year: number, monthIndex: number, daysInMonth: number, firstWeekday: number }}
 */
export function getMonthCalendarMeta(monthKey) {
    const [rawYear, rawMonth] = monthKey.split('-').map(Number);
    const now = new Date();
    const year = Number.isFinite(rawYear) ? rawYear : now.getFullYear();
    const monthIndex = Number.isFinite(rawMonth) ? rawMonth - 1 : now.getMonth();
    const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
    const firstWeekday = new Date(year, monthIndex, 1).getDay();
    const mm = String(monthIndex + 1).padStart(2, '0');
    const dd = String(daysInMonth).padStart(2, '0');
    return {
        startDate: `${year}-${mm}-01`,
        endDate: `${year}-${mm}-${dd}`,
        year,
        monthIndex,
        daysInMonth,
        firstWeekday,
    };
}

/**
 * Format a `YYYY-MM-DD` string into a readable day heading (e.g. "Sat, Mar 14, 2026").
 * @param {string} isoDate
 * @returns {string}
 */
export function formatTimelineDayHeading(isoDate) {
    const parts = isoDate.split('-').map(Number);
    if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) {
        return isoDate;
    }
    const dt = new Date(parts[0], parts[1] - 1, parts[2]);
    return dt.toLocaleDateString(undefined, {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        year: 'numeric',
    });
}

/**
 * Return current local month as `YYYY-MM`.
 * @returns {string}
 */
function currentMonthKey() {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

/**
 * Shift a `YYYY-MM` month key by `deltaMonths`.
 * @param {string} monthKey
 * @param {number} deltaMonths
 * @returns {string}
 */
export function shiftMonthKey(monthKey, deltaMonths) {
    const { year, monthIndex } = getMonthCalendarMeta(monthKey);
    const shifted = new Date(year, monthIndex + deltaMonths, 1);
    return `${shifted.getFullYear()}-${String(shifted.getMonth() + 1).padStart(2, '0')}`;
}

export function useTimeline() {
    /** @type {import('vue').Ref<TimelinePage[]>} */
    const items = ref([]);
    /** @type {import('vue').Ref<Record<string, TimelineDayCount>>} */
    const daysByDate = ref({});
    const isLoading = ref(false);
    const isLoadingMore = ref(false);
    const isLoadingDays = ref(false);
    /** @type {import('vue').Ref<string | null>} */
    const error = ref(null);
    /** @type {import('vue').Ref<string | null>} */
    const nextCursor = ref(null);
    const hasMore = ref(false);

    /** @type {import('vue').Ref<string | null>} */
    const selectedDate = ref(null);
    const calendarMonth = ref(currentMonthKey());
    const includeBlank = ref(false);
    const starredOnly = ref(false);

    let loadSeq = 0;
    let userNavigatedCalendar = false;

    const groupedDays = computed(() => {
        /** @type {Array<{ date: string, label: string, items: TimelinePage[] }>} */
        const groups = [];
        /** @type {Map<string, { date: string, label: string, items: TimelinePage[] }>} */
        const byDate = new Map();
        for (const item of items.value) {
            let group = byDate.get(item.date);
            if (!group) {
                group = {
                    date: item.date,
                    label: formatTimelineDayHeading(item.date),
                    items: [],
                };
                byDate.set(item.date, group);
                groups.push(group);
            }
            group.items.push(item);
        }
        return groups;
    });

    async function loadMonthDays(monthKey = calendarMonth.value, { userInitiated = false } = {}) {
        if (userInitiated) {
            userNavigatedCalendar = true;
        }
        calendarMonth.value = monthKey;
        const { startDate, endDate } = getMonthCalendarMeta(monthKey);
        isLoadingDays.value = true;
        try {
            const list = await fetchTimelineDays({
                startDate,
                endDate,
                includeBlank: includeBlank.value,
                starredOnly: starredOnly.value,
            });
            /** @type {Record<string, TimelineDayCount>} */
            const map = {};
            for (const day of list) {
                map[day.date] = day;
            }
            daysByDate.value = map;
        } catch (_e) {
            // Calendar dots are non-blocking; main feed displays errors.
        } finally {
            isLoadingDays.value = false;
        }
    }

    async function loadTimeline() {
        const seq = ++loadSeq;
        isLoading.value = true;
        error.value = null;
        try {
            const result = await fetchTimelinePages({
                startDate: selectedDate.value,
                endDate: selectedDate.value,
                includeBlank: includeBlank.value,
                starredOnly: starredOnly.value,
            });
            if (seq !== loadSeq) return;
            items.value = result.items;
            nextCursor.value = result.nextCursor;
            hasMore.value = result.hasMore;
        } catch (e) {
            if (seq !== loadSeq) return;
            error.value = getErrorMessage(e);
        } finally {
            if (seq === loadSeq) {
                isLoading.value = false;
            }
        }
    }

    async function loadMore() {
        if (!hasMore.value || !nextCursor.value || isLoadingMore.value || isLoading.value) {
            return;
        }
        const seq = loadSeq;
        isLoadingMore.value = true;
        try {
            const result = await fetchTimelinePages({
                startDate: selectedDate.value,
                endDate: selectedDate.value,
                includeBlank: includeBlank.value,
                starredOnly: starredOnly.value,
                cursor: nextCursor.value,
            });
            if (seq !== loadSeq) return;
            items.value = [...items.value, ...result.items];
            nextCursor.value = result.nextCursor;
            hasMore.value = result.hasMore;
        } catch (e) {
            if (seq !== loadSeq) return;
            error.value = getErrorMessage(e);
        } finally {
            if (seq === loadSeq) {
                isLoadingMore.value = false;
            }
        }
    }

    /**
     * @param {string | null} isoDate
     */
    async function selectDate(isoDate) {
        selectedDate.value = selectedDate.value === isoDate ? null : isoDate;
        await loadTimeline();
    }

    async function refreshAll() {
        await loadTimeline();
        if (
            !userNavigatedCalendar &&
            !selectedDate.value &&
            items.value.length > 0 &&
            items.value[0].date.length >= 7
        ) {
            const latestMonth = items.value[0].date.slice(0, 7);
            if (latestMonth !== calendarMonth.value) {
                calendarMonth.value = latestMonth;
            }
        }
        await loadMonthDays(calendarMonth.value);
    }

    function resetTimeline() {
        loadSeq += 1;
        userNavigatedCalendar = false;
        items.value = [];
        daysByDate.value = {};
        error.value = null;
        nextCursor.value = null;
        hasMore.value = false;
        selectedDate.value = null;
        includeBlank.value = false;
        starredOnly.value = false;
        calendarMonth.value = currentMonthKey();
    }

    onLogout(resetTimeline);

    return {
        items,
        groupedDays,
        daysByDate,
        isLoading,
        isLoadingMore,
        isLoadingDays,
        error,
        hasMore,
        selectedDate,
        calendarMonth,
        includeBlank,
        starredOnly,
        loadTimeline,
        loadMore,
        loadMonthDays,
        selectDate,
        refreshAll,
        resetTimeline,
    };
}
