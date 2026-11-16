/**
 * Shared formatting utilities for file sizes, timestamps, dates, and error messages.
 */

/**
 * Extract a human-readable message from an unknown caught error value.
 * @param {unknown} err
 * @param {string} [fallback='Unknown error']
 * @returns {string}
 */
export function getErrorMessage(err, fallback = 'Unknown error') {
    if (err instanceof Error && err.message) return err.message;
    if (typeof err === 'string' && err) return err;
    return fallback;
}

/**
 * Extract the lowercase file extension from a filename or path, ignoring leading dotfiles
 * (e.g. `.gitignore` -> `''`, `Meeting.NOTE` -> `'note'`).
 * @param {string | null | undefined} filename
 * @returns {string}
 */
export function getFileExtension(filename) {
    if (!filename) return '';
    const base = String(filename).split('/').pop() || '';
    const dot = base.lastIndexOf('.');
    if (dot <= 0 || dot === base.length - 1) return '';
    return base.slice(dot + 1).toLowerCase();
}

/**
 * Resolve the normalized lowercase extension for a `FileItem`-like object.
 * @param {{ extension?: string | null, name?: string | null } | null | undefined} file
 * @returns {string}
 */
export function resolveFileExt(file) {
    if (!file) return '';
    if (file.extension) return String(file.extension).toLowerCase();
    return getFileExtension(file.name);
}

/**
 * @param {number | string | null | undefined} timestamp
 * @returns {number | null}
 */
export function normalizeEpochMs(timestamp) {
    if (timestamp === null || timestamp === undefined || timestamp === '') {
        return null;
    }
    if (typeof timestamp === 'number') {
        if (!Number.isFinite(timestamp) || timestamp <= 0) return null;
        return timestamp < 1e11 ? timestamp * 1000 : timestamp;
    }
    const trimmed = String(timestamp).trim();
    if (!trimmed) return null;
    if (/^\d+(\.\d+)?$/.test(trimmed)) {
        const num = Number(trimmed);
        if (!Number.isFinite(num) || num <= 0) return null;
        return num < 1e11 ? num * 1000 : num;
    }
    const parsed = Date.parse(trimmed);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/**
 * @param {number | string | null | undefined} bytes
 * @param {string} [emptyFallback='']
 * @returns {string}
 */
export function formatSize(bytes, emptyFallback = '') {
    if (!bytes || bytes === '0' || bytes === 0) return emptyFallback;
    const num = Number(bytes);
    if (!Number.isFinite(num) || num <= 0) return emptyFallback;
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.max(0, Math.min(sizes.length - 1, Math.floor(Math.log(num) / Math.log(k))));
    return `${parseFloat((num / k ** i).toFixed(2))} ${sizes[i]}`;
}

/**
 * @param {number | string | null | undefined} timestamp
 * @param {{ includeTime?: boolean }} [options]
 * @returns {string}
 */
export function formatShortDate(timestamp, { includeTime = true } = {}) {
    const ms = normalizeEpochMs(timestamp);
    if (ms === null) return '';
    const d = new Date(ms);
    if (Number.isNaN(d.getTime())) return '';
    const now = new Date();
    if (d.toDateString() === now.toDateString()) {
        return includeTime
            ? `Today, ${d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
            : 'Today';
    }
    if (d.getFullYear() === now.getFullYear()) {
        return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

/**
 * @param {number | string | null | undefined} timestamp
 * @returns {string}
 */
export function formatSystemTimestamp(timestamp) {
    const ms = normalizeEpochMs(timestamp);
    if (ms === null) return '—';
    const d = new Date(ms);
    if (Number.isNaN(d.getTime())) return '—';
    const datePart = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const timePart = d.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
    });
    return `${datePart}, ${timePart}`;
}
