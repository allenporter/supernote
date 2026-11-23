/**
 * Digest & Summary API Client Functions (`/api/file/<op>/summary`).
 *
 * Unwraps Supernote `SummaryItem` wire envelopes into normalized `DigestCategory`
 * and `DigestItem` models aligned with Partner App / Digest 2.0 conventions:
 * - Categories map to `SummaryGroup` (`isSummaryGroup === 'Y'`).
 * - Leaf digests link to categories via `parentUniqueIdentifier` (`""` or `null` = Uncategorized).
 * - `author` falls back to `parsedMetadata.author` when top-level `author` is null.
 * - `sourcePath` is normalized without a leading `/` for display and grouping.
 */
import { apiRequest } from './http.js';

/**
 * Generate a 32-character lowercase hex identifier matching Partner App / Digest 2.0 UUIDs.
 * Uses `crypto.randomUUID` in secure contexts and `crypto.getRandomValues` on LAN HTTP.
 * @returns {string}
 */
export function generateDigestUuid() {
    if (typeof globalThis.crypto?.randomUUID === 'function') {
        return globalThis.crypto.randomUUID().replace(/-/g, '').toLowerCase();
    }
    const bytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Compute an MD5 hex hash for group sync integrity via the loaded `SparkMD5` CDN script.
 * @param {string} text
 * @returns {string}
 */
function computeMd5(text) {
    if (typeof SparkMD5 === 'undefined' || typeof SparkMD5.hash !== 'function') {
        throw new Error('SparkMD5 is required to compute digest sync hashes');
    }
    return SparkMD5.hash(text);
}

/**
 * Return a trimmed non-empty string, or `null`.
 * @param {unknown} raw
 * @returns {string | null}
 */
function nonEmptyStr(raw) {
    if (typeof raw !== 'string') return null;
    const trimmed = raw.trim();
    return trimmed.length > 0 ? trimmed : null;
}

/**
 * Normalize an optional stringified 64-bit ID into `string | null`.
 * @param {unknown} raw
 * @returns {string | null}
 */
function toOptionalId(raw) {
    if (raw === null || raw === undefined) return null;
    const str = String(raw).trim();
    return str.length > 0 ? str : null;
}

/**
 * Normalize a VFS-relative source path without a leading slash.
 * @param {unknown} rawPath
 * @returns {string | null}
 */
export function normalizeSourcePath(rawPath) {
    if (typeof rawPath !== 'string') return null;
    const cleaned = rawPath.trim().replace(/^\/+/, '');
    return cleaned.length > 0 ? cleaned : null;
}

/**
 * Defensively parse a JSON-encoded `metadata` string on a `SummaryItem`.
 * @param {unknown} raw
 * @returns {Record<string, unknown> | null}
 */
export function parseDigestMetadata(raw) {
    if (typeof raw !== 'string' || !raw.trim()) return null;
    try {
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
    } catch {
        return null;
    }
}

/**
 * Parse legacy comma-separated summary tags into trimmed non-empty labels.
 * @param {unknown} raw
 * @returns {string[]}
 */
export function parseDigestTags(raw) {
    if (typeof raw !== 'string' || !raw.trim()) return [];
    return raw
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean);
}

/**
 * Normalize a raw `SummaryItem` group record into a `DigestCategory`.
 * @param {Record<string, any>} raw
 * @returns {DigestCategory}
 */
export function normalizeDigestCategory(raw) {
    return {
        id: String(raw.id ?? ''),
        uniqueIdentifier: String(raw.uniqueIdentifier ?? ''),
        name: nonEmptyStr(raw.name) || 'Untitled Category',
        description: nonEmptyStr(raw.description),
        creationTime: Number(raw.creationTime ?? raw.createTime ?? 0) || 0,
        lastModifiedTime:
            Number(raw.lastModifiedTime ?? raw.updateTime ?? raw.createTime ?? 0) || 0,
    };
}

/**
 * Normalize a raw `SummaryItem` leaf record into a `DigestItem`.
 * @param {Record<string, any>} raw
 * @returns {DigestItem}
 */
export function normalizeDigestItem(raw) {
    const metadata = parseDigestMetadata(raw.metadata);
    const handwriteInnerName = nonEmptyStr(raw.handwriteInnerName);
    const commentHandwriteName = nonEmptyStr(raw.commentHandwriteName);

    return {
        id: String(raw.id ?? ''),
        uniqueIdentifier: String(raw.uniqueIdentifier ?? ''),
        parentUniqueIdentifier: nonEmptyStr(raw.parentUniqueIdentifier),
        fileId: toOptionalId(raw.fileId),
        content: typeof raw.content === 'string' ? raw.content : '',
        commentStr: nonEmptyStr(raw.commentStr),
        author: nonEmptyStr(raw.author) || nonEmptyStr(metadata?.author),
        sourcePath: normalizeSourcePath(raw.sourcePath),
        dataSource: nonEmptyStr(raw.dataSource),
        tags: parseDigestTags(raw.tags),
        hasHandwriting: Boolean(handwriteInnerName || commentHandwriteName),
        handwriteInnerName,
        commentHandwriteName,
        creationTime: Number(raw.creationTime ?? raw.createTime ?? 0) || 0,
        lastModifiedTime:
            Number(raw.lastModifiedTime ?? raw.updateTime ?? raw.createTime ?? 0) || 0,
        metadata,
    };
}

/**
 * Fetch all Digest categories (`SummaryGroup`) via POST /api/file/query/summary/group.
 * @returns {Promise<DigestCategory[]>}
 */
export async function fetchDigestCategories() {
    const data = await apiRequest('/api/file/query/summary/group', {
        body: { page: 1, size: 0 },
        errorPrefix: 'Failed to fetch digest categories',
    });
    /** @type {Array<Record<string, any>>} */
    const rawList = Array.isArray(data?.summaryDOList) ? data.summaryDOList : [];
    return rawList.map(normalizeDigestCategory);
}

/**
 * Fetch all leaf digests/summaries via POST /api/file/query/summary.
 * @returns {Promise<DigestItem[]>}
 */
export async function fetchDigests() {
    const data = await apiRequest('/api/file/query/summary', {
        body: { page: 1, size: 0 },
        errorPrefix: 'Failed to fetch digests',
    });
    /** @type {Array<Record<string, any>>} */
    const rawList = Array.isArray(data?.summaryDOList) ? data.summaryDOList : [];
    return rawList.map(normalizeDigestItem);
}

/**
 * Create a new Digest category via POST /api/file/add/summary/group.
 * @param {string} name
 * @param {string | null} [description=null]
 * @returns {Promise<{ id: string, uniqueIdentifier: string }>}
 */
export async function createDigestCategory(name, description = null) {
    const trimmedName = name.trim();
    const uniqueIdentifier = generateDigestUuid();
    const now = Date.now();
    const data = await apiRequest('/api/file/add/summary/group', {
        body: {
            uniqueIdentifier,
            name: trimmedName,
            md5Hash: computeMd5(trimmedName),
            description: nonEmptyStr(description),
            creationTime: now,
            lastModifiedTime: now,
        },
        errorPrefix: 'Failed to create category',
    });
    return {
        id: String(data?.id ?? ''),
        uniqueIdentifier,
    };
}

/**
 * Rename or update an existing Digest category via PUT /api/file/update/summary/group.
 * @param {DigestCategory} category
 * @param {{ name?: string, description?: string | null }} updates
 * @returns {Promise<void>}
 */
export async function updateDigestCategory(category, updates) {
    const nextName = updates.name !== undefined ? updates.name.trim() : category.name;
    /** @type {Record<string, unknown>} */
    const body = {
        id: String(category.id),
        uniqueIdentifier: category.uniqueIdentifier,
        name: nextName,
        md5Hash: computeMd5(nextName),
        lastModifiedTime: Date.now(),
    };
    if (updates.description !== undefined) {
        body.description = updates.description?.trim() ?? '';
    }
    await apiRequest('/api/file/update/summary/group', {
        method: 'PUT',
        body,
        errorPrefix: 'Failed to update category',
    });
}

/**
 * Soft-delete a Digest category (and its child digests) via DELETE /api/file/delete/summary/group.
 * @param {string | number} categoryId
 * @returns {Promise<void>}
 */
export async function deleteDigestCategory(categoryId) {
    await apiRequest('/api/file/delete/summary/group', {
        method: 'DELETE',
        body: { id: String(categoryId) },
        errorPrefix: 'Failed to delete category',
    });
}

/**
 * Create a new leaf Digest via POST /api/file/add/summary.
 * @param {DigestInput} input
 * @returns {Promise<{ id: string, uniqueIdentifier: string }>}
 */
export async function createDigest(input) {
    const uniqueIdentifier = generateDigestUuid();
    const now = Date.now();
    const data = await apiRequest('/api/file/add/summary', {
        body: {
            uniqueIdentifier,
            parentUniqueIdentifier: input.parentUniqueIdentifier || '',
            content: input.content,
            commentStr: nonEmptyStr(input.commentStr),
            author: nonEmptyStr(input.author),
            sourcePath: normalizeSourcePath(input.sourcePath),
            dataSource: 'USER',
            creationTime: now,
            lastModifiedTime: now,
        },
        errorPrefix: 'Failed to create digest',
    });
    return {
        id: String(data?.id ?? ''),
        uniqueIdentifier,
    };
}

/**
 * Update an existing leaf Digest via PUT /api/file/update/summary.
 * @param {string | number} digestId
 * @param {DigestUpdateInput} updates
 * @returns {Promise<void>}
 */
export async function updateDigest(digestId, updates) {
    /** @type {Record<string, unknown>} */
    const body = {
        id: String(digestId),
        lastModifiedTime: Date.now(),
    };
    if (updates.parentUniqueIdentifier !== undefined) {
        body.parentUniqueIdentifier = updates.parentUniqueIdentifier ?? '';
    }
    if (updates.content !== undefined) {
        body.content = updates.content;
    }
    if (updates.commentStr !== undefined) {
        body.commentStr = updates.commentStr?.trim() ?? '';
    }
    if (updates.author !== undefined) {
        body.author = updates.author?.trim() ?? '';
    }
    if (updates.sourcePath !== undefined) {
        body.sourcePath = normalizeSourcePath(updates.sourcePath) ?? '';
    }
    await apiRequest('/api/file/update/summary', {
        method: 'PUT',
        body,
        errorPrefix: 'Failed to update digest',
    });
}

/**
 * Soft-delete a leaf Digest via DELETE /api/file/delete/summary.
 * @param {string | number} digestId
 * @returns {Promise<void>}
 */
export async function deleteDigest(digestId) {
    await apiRequest('/api/file/delete/summary', {
        method: 'DELETE',
        body: { id: String(digestId) },
        errorPrefix: 'Failed to delete digest',
    });
}

/**
 * Resolve a VFS-relative `sourcePath` (e.g. `Document/Paper.pdf`) to a Cloud `fileId`.
 * Returns `null` if the path is missing or points to a folder.
 * @param {string | null | undefined} sourcePath
 * @returns {Promise<string | null>}
 */
export async function resolveSourceFileId(sourcePath) {
    const normalized = normalizeSourcePath(sourcePath);
    if (!normalized) return null;
    const data = await apiRequest('/api/file/3/files/query/by/path_v3', {
        body: { path: `/${normalized}` },
        errorPrefix: 'Failed to resolve source file',
        fallbackValue: null,
    });
    const entry = data?.entriesVO;
    if (!entry || entry.tag === 'folder') return null;
    return toOptionalId(entry.id);
}
