/**
 * Timeline API client (`POST /api/extended/timeline/*`).
 *
 * Unwraps backend envelopes into normalized `TimelinePagesResult` and
 * `TimelineDayCount[]` domain models.
 */

import { apiRequest } from './http.js';

/**
 * Fetch paginated cross-notebook page activity entries.
 * @param {TimelineFilterOptions & { limit?: number, cursor?: string | null }} [options]
 * @returns {Promise<TimelinePagesResult>}
 */
export async function fetchTimelinePages(options = {}) {
    const body = {
        startDate: options.startDate ?? null,
        endDate: options.endDate ?? null,
        includeBlank: Boolean(options.includeBlank),
        starredOnly: Boolean(options.starredOnly),
        tzOffsetMinutes:
            typeof options.tzOffsetMinutes === 'number'
                ? options.tzOffsetMinutes
                : -new Date().getTimezoneOffset(),
        limit: options.limit ?? 40,
        cursor: options.cursor ?? null,
    };
    const data = await apiRequest('/api/extended/timeline/pages', {
        method: 'POST',
        body,
    });
    /** @type {Record<string, any>[]} */
    const rawItems = Array.isArray(data?.items) ? data.items : [];
    /** @type {TimelinePage[]} */
    const items = rawItems.map((item) => ({
        date: String(item.date || ''),
        timestampMs: Number(item.timestampMs || 0),
        fileId: String(item.fileId || ''),
        fileName: String(item.fileName || ''),
        pageIndex: Number(item.pageIndex || 0),
        pageId: String(item.pageId || ''),
        sources: Array.isArray(item.sources) ? item.sources.map(String) : [],
        isBlank: Boolean(item.isBlank),
        hasFiveStar: Boolean(item.hasFiveStar),
        keywords: Array.isArray(item.keywords) ? item.keywords.map(String) : [],
        summary:
            typeof item.summary === 'string' && item.summary.trim() ? item.summary.trim() : null,
        imageUrl: typeof item.imageUrl === 'string' ? item.imageUrl : null,
    }));
    return {
        items,
        nextCursor: typeof data?.nextCursor === 'string' ? data.nextCursor : null,
        hasMore: Boolean(data?.hasMore),
    };
}

/**
 * Fetch per-day activity counts for calendar navigation.
 * @param {TimelineFilterOptions} [options]
 * @returns {Promise<TimelineDayCount[]>}
 */
export async function fetchTimelineDays(options = {}) {
    const body = {
        startDate: options.startDate ?? null,
        endDate: options.endDate ?? null,
        includeBlank: Boolean(options.includeBlank),
        starredOnly: Boolean(options.starredOnly),
        tzOffsetMinutes:
            typeof options.tzOffsetMinutes === 'number'
                ? options.tzOffsetMinutes
                : -new Date().getTimezoneOffset(),
    };
    const data = await apiRequest('/api/extended/timeline/days', {
        method: 'POST',
        body,
    });
    /** @type {Record<string, any>[]} */
    const rawDays = Array.isArray(data?.days) ? data.days : [];
    return rawDays.map((day) => ({
        date: String(day.date || ''),
        count: Number(day.count || 0),
        createdCount: Number(day.createdCount || 0),
        editedCount: Number(day.editedCount || 0),
        datedCount: Number(day.datedCount || 0),
    }));
}
