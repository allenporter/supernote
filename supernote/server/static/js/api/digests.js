/**
 * Digest & Category API Client Functions (`GET /api/extended/digests` and `/api/file/<op>/summary`).
 *
 * Unwraps `DigestVO` (from `GET /api/extended/digests`) and `SummaryItem` category
 * envelopes into normalized `DigestCategory` and `DigestItem` models aligned with
 * Partner App / Digest 2.0 conventions:
 * - Categories map to `SummaryGroup` (`isSummaryGroup === 'Y'`).
 * - Leaf digests link to categories via `categoryId` (`""` or `null` = Uncategorized).
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
 * Normalize an inline `DigestHandwritingVO` payload into a `DigestHandwriting` object.
 * @param {unknown} raw
 * @returns {DigestHandwriting | null}
 */
function normalizeDigestHandwriting(raw) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
    const hw = /** @type {Record<string, unknown>} */ (raw);
    const updateTime = Number(hw.updateTime);
    return {
        md5: nonEmptyStr(hw.md5),
        transcript: nonEmptyStr(hw.transcript),
        modelId: nonEmptyStr(hw.modelId),
        updateTime: Number.isFinite(updateTime) && updateTime > 0 ? updateTime : null,
    };
}

/**
 * Normalize a raw `DigestVO` (from `GET /api/extended/digests`) into a `DigestItem`.
 * @param {Record<string, any>} raw
 * @returns {DigestItem}
 */
export function normalizeDigestItem(raw) {
    const handwriting = normalizeDigestHandwriting(raw.handwriting);
    const tags = Array.isArray(raw.tags)
        ? raw.tags.map((t) => String(t).trim()).filter(Boolean)
        : [];

    return {
        id: String(raw.id ?? ''),
        uniqueIdentifier: String(raw.uniqueIdentifier ?? ''),
        parentUniqueIdentifier: nonEmptyStr(raw.categoryId),
        fileId: toOptionalId(raw.fileId),
        name: nonEmptyStr(raw.name),
        content: typeof raw.content === 'string' ? raw.content : '',
        commentStr: nonEmptyStr(raw.comment),
        author: nonEmptyStr(raw.author),
        sourcePath: normalizeSourcePath(raw.sourcePath),
        dataSource: nonEmptyStr(raw.dataSource),
        tags,
        hasHandwriting: Boolean(handwriting),
        handwriting,
        creationTime: Number(raw.creationTime ?? 0) || 0,
        lastModifiedTime: Number(raw.updateTime ?? raw.creationTime ?? 0) || 0,
    };
}

const AI_MODEL_SOURCE_PATTERN =
    /^(AI|LLM|AI SYNTHESIS)$|(GEMINI|GEMMA|GPT-|\bO[134](?:-|$)|CLAUDE|LLAMA|MISTRAL|QWEN|DEEPSEEK|PHI-|OLLAMA|MODELS\/|OPENAI|ANTHROPIC|SUMMARY)/;

/**
 * Classify whether a Digest entry is a server-generated AI Notebook Summary.
 * Matches either the canonical `"AI Summaries"` category name or an LLM
 * provider/model identifier in `dataSource` (for example `gemini-2.5-flash`).
 * @param {Pick<DigestItem, 'dataSource'>} digest
 * @param {string | null} [categoryName=null]
 * @returns {boolean}
 */
export function isAiSummaryDigest(digest, categoryName = null) {
    if (typeof categoryName === 'string' && categoryName.trim().toLowerCase() === 'ai summaries') {
        return true;
    }
    const ds = String(digest?.dataSource || '')
        .trim()
        .toUpperCase();
    if (!ds) return false;
    return AI_MODEL_SOURCE_PATTERN.test(ds);
}

/**
 * Format a Digest entry as Markdown for clipboard copy, including any typed
 * comment and handwritten annotation transcript.
 * @param {DigestItem} digest
 * @returns {string}
 */
export function formatDigestMarkdown(digest) {
    const parts = [];
    const content = (digest.content || '').trim();
    if (content) parts.push(content);
    const comment = (digest.commentStr || '').trim();
    if (comment) {
        parts.push(
            comment
                .split(/\r?\n/)
                .map((line) => (line ? `> ${line}` : '>'))
                .join('\n'),
        );
    }
    const transcript = (digest.handwriting?.transcript || '').trim();
    if (transcript) {
        parts.push(`**Handwritten annotation:**\n\n${transcript}`);
    }
    return parts.join('\n\n');
}

/**
 * Collapse embedded newlines so Markdown headings and inline labels stay single-line.
 * @param {string} text
 * @returns {string}
 */
function collapseMarkdownLine(text) {
    return text.replace(/[\r\n]+/g, ' ').trim();
}

/**
 * Wrap text in a safe Markdown inline code span even if it contains backticks.
 * @param {string} text
 * @returns {string}
 */
function formatMarkdownCodeSpan(text) {
    const cleaned = collapseMarkdownLine(text);
    const runs = cleaned.match(/`+/g) || [];
    const longest = runs.reduce((max, r) => Math.max(max, r.length), 0);
    const fence = '`'.repeat(longest + 1);
    if (cleaned.startsWith('`') || cleaned.endsWith('`')) {
        return `${fence} ${cleaned} ${fence}`;
    }
    return `${fence}${cleaned}${fence}`;
}

/**
 * Format a UTC `YYYY-MM-DD` date string from epoch ms, or `null`.
 * @param {number | null | undefined} epochMs
 * @returns {string | null}
 */
function formatExportIsoDate(epochMs) {
    if (!epochMs || !Number.isFinite(epochMs) || epochMs <= 0) return null;
    const d = new Date(epochMs);
    if (Number.isNaN(d.getTime())) return null;
    return d.toISOString().slice(0, 10);
}

/**
 * Build a safe `.md` download filename from a heading or source label.
 * @param {string | null | undefined} label
 * @returns {string}
 */
export function buildDigestExportFilename(label) {
    const slug = String(label || '')
        .trim()
        .toLowerCase()
        .replace(/\.[a-z0-9]{1,8}$/i, '')
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
    if (!slug || slug === 'digests') return 'digests.md';
    return slug.endsWith('-digests') ? `${slug}.md` : `${slug}-digests.md`;
}

/**
 * Format a list of Digests as grouped, PKM-ready Markdown for file download.
 * @param {DigestItem[]} digests
 * @param {{ title?: string }} [options]
 * @returns {string}
 */
export function formatDigestsMarkdownExport(digests, options = {}) {
    const heading = collapseMarkdownLine(options.title || '') || 'Digests';
    if (!Array.isArray(digests) || digests.length === 0) {
        return `# ${heading}\n\n_No digests found._\n`;
    }

    /** @type {Map<string, DigestItem[]>} */
    const groups = new Map();
    for (const digest of digests) {
        const rawSource = normalizeSourcePath(digest.sourcePath);
        const key = rawSource ? collapseMarkdownLine(rawSource) : '';
        const list = groups.get(key);
        if (list) {
            list.push(digest);
        } else {
            groups.set(key, [digest]);
        }
    }

    const sections = [`# ${heading}`];
    for (const [sourcePath, items] of groups.entries()) {
        const formattedItems = items
            .map((digest) => {
                const body = formatDigestMarkdown(digest);
                const meta = [];
                const author = digest.author ? collapseMarkdownLine(digest.author) : '';
                if (author) meta.push(author);
                if (Array.isArray(digest.tags) && digest.tags.length > 0) {
                    const tagsStr = digest.tags
                        .map((t) => String(t).trim())
                        .filter(Boolean)
                        .map((t) => `#${t}`)
                        .join(' ');
                    if (tagsStr) meta.push(tagsStr);
                }
                const dateStr = formatExportIsoDate(digest.lastModifiedTime || digest.creationTime);
                if (dateStr) meta.push(dateStr);
                const parts = [];
                if (body) parts.push(body);
                if (meta.length > 0) parts.push(`_${meta.join(' · ')}_`);
                return parts.join('\n\n');
            })
            .filter(Boolean);
        if (formattedItems.length === 0) continue;

        const sourceName = sourcePath
            ? sourcePath.split('/').filter(Boolean).pop() || sourcePath
            : 'Standalone Digests';
        const groupLines = [`## ${sourceName}`];
        if (sourcePath) {
            groupLines.push(`Source: ${formatMarkdownCodeSpan(sourcePath)}`);
        }
        groupLines.push(formattedItems.join('\n\n---\n\n'));
        sections.push(groupLines.join('\n\n'));
    }

    if (sections.length === 1) {
        return `# ${heading}\n\n_No digests found._\n`;
    }

    return `${sections.join('\n\n')}\n`;
}

const DIGEST_PAGE_SIZE = 200;

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
 * Fetch leaf Digests with inline handwriting OCR transcripts via GET /api/extended/digests.
 * @param {{ fileId?: string | number | null, errorPrefix?: string }} [options]
 * @returns {Promise<DigestItem[]>}
 */
export async function fetchDigests(options = {}) {
    /** @type {DigestItem[]} */
    const items = [];
    /** @type {Set<string>} */
    const seenKeys = new Set();
    let offset = 0;
    let total = Number.POSITIVE_INFINITY;
    const errorPrefix = options.errorPrefix || 'Failed to fetch digests';
    const fileIdParam =
        options.fileId !== undefined && options.fileId !== null
            ? `&fileId=${encodeURIComponent(String(options.fileId))}`
            : '';

    while (offset < total) {
        const data = await apiRequest(
            `/api/extended/digests?limit=${DIGEST_PAGE_SIZE}&offset=${offset}${fileIdParam}`,
            {
                method: 'GET',
                errorPrefix,
            },
        );
        /** @type {Array<Record<string, any>>} */
        const batch = Array.isArray(data?.digests) ? data.digests : [];
        for (const raw of batch) {
            const item = normalizeDigestItem(raw);
            const dedupeKey = item.id || item.uniqueIdentifier;
            if (dedupeKey && seenKeys.has(dedupeKey)) continue;
            if (dedupeKey) seenKeys.add(dedupeKey);
            items.push(item);
        }
        if (typeof data?.total === 'number' && Number.isFinite(data.total)) {
            total = data.total;
        } else if (batch.length < DIGEST_PAGE_SIZE) {
            total = offset + batch.length;
        }
        if (batch.length === 0) break;
        offset += batch.length;
    }

    return items;
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
 * Render a Digest entry's handwritten `.mark` annotation to per-page PNG URLs
 * via POST /api/extended/file/summary/to/png.
 * @param {string | number} digestId
 * @returns {Promise<NotePngPage[]>}
 */
export async function fetchDigestHandwritingPages(digestId) {
    const data = await apiRequest('/api/extended/file/summary/to/png', {
        body: { id: String(digestId) },
        errorPrefix: 'Failed to load handwriting preview',
    });
    /** @type {Array<Record<string, unknown>>} */
    const rawPages = Array.isArray(data?.pngPageVOList) ? data.pngPageVOList : [];
    return rawPages
        .map((page, index) => {
            const rawPageNo = page?.pageNo;
            const parsed =
                rawPageNo === null || rawPageNo === undefined || rawPageNo === ''
                    ? Number.NaN
                    : Number(rawPageNo);
            const url = nonEmptyStr(page?.url);
            if (!url) return null;
            return {
                pageNo: Number.isFinite(parsed) ? parsed : index,
                url,
            };
        })
        .filter((page) => page !== null)
        .sort((a, b) => a.pageNo - b.pageNo);
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
