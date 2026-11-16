/**
 * Pure file classification, notebook metadata, and link/transcript formatting helpers
 * for the FileViewer component suite.
 */

import { normalizeTranscriptPages } from '../../api/client.js';
import { resolveFileExt } from '../../utils/format.js';

export { normalizeTranscriptPages, resolveFileExt };

export const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg']);
export const TEXT_EXTENSIONS = new Set(['txt', 'md', 'csv', 'json', 'yaml', 'yml', 'log']);
export const MAX_TEXT_PREVIEW_BYTES = 2 * 1024 * 1024; // 2 MB
export const ZOOM_STEPS = [75, 100, 125, 150];

/** @type {Record<string, string>} */
export const PAGE_STYLE_LABELS = {
    '8mm_ruled_line': '8mm ruled',
    '9mm_ruled_line': '9mm ruled',
    '10mm_ruled_line': '10mm ruled',
    '5mm_dots': '5mm dots',
    '5mm_engineering_grid': '5mm grid',
    '10mm_engineering_grid': '10mm grid',
    cornell_note: 'Cornell',
    four_wire_grid: 'Four-wire',
    task_list: 'Task list',
    weekly_2_columns: 'Weekly (2 col)',
    daily: 'Daily',
    weekly: 'Weekly',
    monthly: 'Monthly',
    custom: 'Custom template',
};

/**
 * @param {string} ext
 * @returns {'note' | 'image' | 'pdf' | 'text' | 'unsupported'}
 */
export function resolveFileCategory(ext) {
    if (ext === 'note') return 'note';
    if (IMAGE_EXTENSIONS.has(ext)) return 'image';
    if (ext === 'pdf') return 'pdf';
    if (TEXT_EXTENSIONS.has(ext)) return 'text';
    return 'unsupported';
}

/**
 * @param {string | null | undefined} style
 * @returns {string | null}
 */
export function formatPageStyle(style) {
    if (!style || style === 'white') return null;
    if (PAGE_STYLE_LABELS[style]) return PAGE_STYLE_LABELS[style];
    const cleaned = String(style).replaceAll('_', ' ');
    return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

/**
 * Return a normalized `http:` / `https:` URL string, or `null` for unsafe or malformed schemes.
 * @param {string | null | undefined} rawUrl
 * @returns {string | null}
 */
export function parseSafeHttpUrl(rawUrl) {
    if (!rawUrl || typeof rawUrl !== 'string') return null;
    try {
        const parsed = new URL(rawUrl.trim());
        if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
            return parsed.href;
        }
    } catch {
        // Reject malformed or relative non-HTTP URLs
    }
    return null;
}

/**
 * @param {NoteLink | null | undefined} link
 * @param {string | number | null | undefined} currentFileId
 * @returns {string}
 */
export function formatLinkLabel(link, currentFileId) {
    if (!link) return 'Link';
    const isExternalFile = Boolean(
        (link.targetFileId && String(link.targetFileId) !== String(currentFileId ?? '')) ||
            link.linkType === 'file',
    );
    const targetBaseName = link.target ? link.target.split('/').pop() || link.target : null;
    if (link.linkType === 'web') {
        return link.target ? link.target.replace(/^https?:\/\//i, '') : 'Web link';
    }
    if (isExternalFile) {
        const name = targetBaseName || 'Notebook';
        if (typeof link.targetPageIndex === 'number') {
            return `${name} · p.${link.targetPageIndex + 1}`;
        }
        return name;
    }
    if (typeof link.targetPageIndex === 'number') {
        return `Page ${link.targetPageIndex + 1}`;
    }
    return targetBaseName || 'Linked notebook';
}

/**
 * @param {string | null | undefined} str
 * @returns {string}
 */
export function formatContent(str) {
    if (!str) return '';
    return str.replaceAll('\\n', '\n');
}

/**
 * @param {Partial<TranscriptPage> | null | undefined} pageItem
 * @returns {boolean}
 */
export function hasCopyablePageText(pageItem) {
    return Boolean(pageItem?.hasTranscript && formatContent(pageItem.text).trim());
}

/**
 * @param {TranscriptPage[]} transcriptPages
 * @param {NoteMetadata | null | undefined} noteMetadata
 * @param {Map<number, NotePageMeta>} pageMetaByIndex
 * @param {Map<number, NoteLink[]>} linksByPageIndex
 * @returns {TranscriptPage[]}
 */
export function buildDisplayTranscriptPages(
    transcriptPages,
    noteMetadata,
    pageMetaByIndex,
    linksByPageIndex,
) {
    const merged = new Map();
    for (const item of transcriptPages) {
        if (typeof item.pageIndex === 'number') {
            merged.set(item.pageIndex, {
                pageIndex: item.pageIndex,
                pageId: item.pageId,
                text: item.text ?? '',
                date: item.date || pageMetaByIndex.get(item.pageIndex)?.date || null,
                hasTranscript: true,
            });
        }
    }
    const metaPages = noteMetadata?.pages;
    if (Array.isArray(metaPages)) {
        for (const mp of metaPages) {
            const idx = mp.pageIndex;
            if (typeof idx !== 'number') continue;
            const hasKws = Array.isArray(mp.keywords) && mp.keywords.length > 0;
            const hasLinks = (linksByPageIndex.get(idx)?.length || 0) > 0;
            if (!merged.has(idx) && (hasKws || hasLinks)) {
                merged.set(idx, {
                    pageIndex: idx,
                    pageId: mp.pageId || `page-${idx}`,
                    text: '',
                    date: mp.date || null,
                    hasTranscript: false,
                });
            }
        }
    }
    return Array.from(merged.values()).sort((a, b) => a.pageIndex - b.pageIndex);
}
