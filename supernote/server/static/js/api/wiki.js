/**
 * LLM Wiki API client wrapping `/api/extended/wiki/*` endpoints.
 */

import { ApiError, apiRequest, getToken } from './http.js';

/**
 * @typedef {Object} WikiSourceRef
 * @property {string} source_type
 * @property {string} source_key
 * @property {number | null} [file_id]
 * @property {number | null} [last_event_seq]
 * @property {boolean} [is_source_deleted]
 */

/**
 * @typedef {Object} WikiPage
 * @property {number} page_id
 * @property {string} slug
 * @property {string} title
 * @property {string} page_kind
 * @property {string} summary
 * @property {string} body_md
 * @property {Record<string, any>[]} claims
 * @property {string} edit_policy
 * @property {string} last_author_kind
 * @property {number} version
 * @property {number} create_time
 * @property {number} update_time
 * @property {string[]} aliases
 * @property {string[]} outbound_links
 * @property {string[]} backlinks
 * @property {WikiSourceRef[]} source_refs
 */

/**
 * @typedef {Object} WikiLintIssue
 * @property {number} issue_id
 * @property {string} dedup_key
 * @property {string} issue_type
 * @property {string} severity
 * @property {number | null} page_id
 * @property {number | null} target_page_id
 * @property {string} description
 * @property {Record<string, any> | null} proposal
 * @property {string} status
 * @property {number} create_time
 * @property {number} update_time
 */

/**
 * @typedef {Object} WikiStatus
 * @property {number} page_count
 * @property {number} open_lint_count
 * @property {string | null} last_sync_token
 * @property {number} pending_events_since_lint
 * @property {number} tokens_used_day
 * @property {string | null} budget_day_utc
 * @property {string} status
 * @property {string | null} last_error
 * @property {number} [backfill_remaining_files]
 * @property {number} [backfill_total_files]
 * @property {number} [backfill_untranscribed_files]
 * @property {string[]} [backfill_next_files]
 */

/**
 * @typedef {Object} WikiSearchHit
 * @property {string} slug
 * @property {string} title
 * @property {string} page_kind
 * @property {string} summary
 * @property {number} score
 * @property {string[]} neighbor_slugs
 * @property {WikiSourceRef[]} source_refs
 */

/**
 * Validate and percent-encode each segment of a wiki slug for URL interpolation.
 *
 * @param {string} slug
 * @returns {string}
 */
export function encodeSlugPath(slug) {
    const cleaned = String(slug || '')
        .trim()
        .replace(/^\/+|\/+$/g, '');
    if (!cleaned) {
        throw new Error('Wiki slug must be non-empty');
    }
    const segments = cleaned.split('/');
    for (const seg of segments) {
        if (!seg || seg === '.' || seg === '..') {
            throw new Error(`Invalid wiki slug: ${slug}`);
        }
    }
    return segments.map((seg) => encodeURIComponent(seg)).join('/');
}

/**
 * Fetch active wiki pages. Returns `null` when the wiki component is disabled (404).
 *
 * @param {{ pageKind?: string | null, limit?: number }} [options]
 * @returns {Promise<WikiPage[] | null>}
 */
export async function fetchWikiPages({ pageKind = null, limit = 200 } = {}) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (pageKind) params.set('page_kind', pageKind);
    try {
        const data = await apiRequest(`/api/extended/wiki/pages?${params.toString()}`, {
            method: 'GET',
            errorPrefix: 'Failed to load wiki pages',
        });
        return Array.isArray(data?.pages) ? data.pages : [];
    } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
            return null;
        }
        throw err;
    }
}

/**
 * @param {string} slug
 * @returns {Promise<WikiPage | null>}
 */
export async function fetchWikiPage(slug) {
    try {
        const data = await apiRequest(`/api/extended/wiki/pages/${encodeSlugPath(slug)}`, {
            method: 'GET',
            errorPrefix: 'Failed to load wiki page',
        });
        return data?.page || null;
    } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
            return null;
        }
        throw err;
    }
}

/**
 * @param {string} slug
 * @param {Record<string, any>} payload
 * @returns {Promise<WikiPage>}
 */
export async function saveWikiPage(slug, payload) {
    const data = await apiRequest(`/api/extended/wiki/pages/${encodeSlugPath(slug)}`, {
        method: 'PUT',
        body: payload,
        errorPrefix: 'Failed to save wiki page',
    });
    return data.page;
}

/**
 * @param {string} slug
 * @returns {Promise<void>}
 */
export async function deleteWikiPage(slug) {
    await apiRequest(`/api/extended/wiki/pages/${encodeSlugPath(slug)}`, {
        method: 'DELETE',
        errorPrefix: 'Failed to delete wiki page',
    });
}

/**
 * @param {string} query
 * @param {number} [topK=20]
 * @returns {Promise<WikiSearchHit[]>}
 */
export async function searchWikiPages(query, topK = 20) {
    const params = new URLSearchParams({ q: query, top_k: String(topK) });
    const data = await apiRequest(`/api/extended/wiki/search?${params.toString()}`, {
        method: 'GET',
        errorPrefix: 'Failed to search wiki',
    });
    return Array.isArray(data?.hits) ? data.hits : [];
}

/**
 * @returns {Promise<WikiStatus | null>}
 */
export async function fetchWikiStatus() {
    try {
        const data = await apiRequest('/api/extended/wiki/status', {
            method: 'GET',
            errorPrefix: 'Failed to load wiki status',
        });
        return data?.status || null;
    } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
            return null;
        }
        throw err;
    }
}

/**
 * @typedef {Object} WikiCompileResult
 * @property {string} mode
 * @property {number | null} [events_processed]
 * @property {number | null} [pages_updated]
 * @property {number | null} [skipped_policy_pages]
 * @property {number | null} [lint_issues_open]
 * @property {string | null} [status]
 * @property {WikiLintIssue[] | null} [issues]
 * @property {string[]} [files_processed]
 * @property {string[]} [updated_pages]
 * @property {number | null} [remaining_files]
 */

const PAGE_KIND_LABELS = {
    project: 'Project',
    entity: 'Entity',
    topic: 'Topic',
    source_digest: 'Source',
    index: 'Index',
    log: 'Log',
};

/**
 * Format an internal wiki `page_kind` into a concise user-facing label.
 *
 * @param {string} kind
 * @returns {string}
 */
export function formatPageKindLabel(kind) {
    return PAGE_KIND_LABELS[/** @type {keyof typeof PAGE_KIND_LABELS} */ (kind)] || kind;
}

/**
 * Format an internal lint `issue_type` into a readable label.
 *
 * @param {string} issueType
 * @returns {string}
 */
export function formatLintTypeLabel(issueType) {
    return String(issueType || '').replace(/_/g, ' ');
}

/**
 * @param {'incremental' | 'backfill' | 'lint'} [mode='incremental']
 * @returns {Promise<WikiCompileResult>}
 */
export async function triggerWikiCompile(mode = 'incremental') {
    return apiRequest('/api/extended/wiki/compile', {
        method: 'POST',
        body: { mode },
        errorPrefix: `Failed to run wiki ${mode}`,
    });
}

/**
 * Format a user-facing toast message and severity for a wiki compile/backfill/lint response.
 *
 * @param {'incremental' | 'backfill' | 'lint'} mode
 * @param {WikiCompileResult | null | undefined} result
 * @returns {{ message: string, type: 'success' | 'info' | 'error' }}
 */
export function formatWikiActionResult(mode, result) {
    if (result?.status === 'paused') {
        return {
            message: 'Wiki compiler is paused — check the status banner for details.',
            type: 'error',
        };
    }
    if (mode === 'lint') {
        const count = Array.isArray(result?.issues) ? result.issues.length : 0;
        return {
            message: `Wiki lint finished (${count} open ${count === 1 ? 'issue' : 'issues'}).`,
            type: 'success',
        };
    }
    const processed = result?.events_processed ?? 0;
    const updated = result?.pages_updated ?? 0;
    if (mode === 'backfill') {
        const filesCount = Array.isArray(result?.files_processed)
            ? result.files_processed.length
            : 0;
        if (processed === 0 && filesCount === 0) {
            return {
                message: 'No remaining OCR’d notebooks to backfill.',
                type: 'info',
            };
        }
        const notebookPart =
            filesCount > 0
                ? `compiled ${filesCount} ${filesCount === 1 ? 'notebook' : 'notebooks'} (`
                : 'backfilled batch (';
        const pageSummary = `${updated} ${updated === 1 ? 'page' : 'pages'} updated`;
        if (result?.remaining_files === 0) {
            return {
                message: `Backfill complete — ${notebookPart}${pageSummary}).`,
                type: 'success',
            };
        }
        if (typeof result?.remaining_files === 'number' && result.remaining_files > 0) {
            return {
                message: `Backfilled batch — ${notebookPart}${pageSummary}). ${result.remaining_files} ${result.remaining_files === 1 ? 'notebook' : 'notebooks'} remaining.`,
                type: 'success',
            };
        }
        return {
            message: `Backfilled batch (${pageSummary}).`,
            type: 'success',
        };
    }
    if (processed === 0) {
        return {
            message: 'Wiki is up to date — no new notebook or task changes.',
            type: 'info',
        };
    }
    return {
        message: `Updated ${updated} ${updated === 1 ? 'page' : 'pages'} from ${processed} recent ${processed === 1 ? 'change' : 'changes'}.`,
        type: 'success',
    };
}

/**
 * @param {'open' | 'resolved' | 'dismissed' | 'all'} [status='open']
 * @returns {Promise<WikiLintIssue[]>}
 */
export async function fetchWikiLintIssues(status = 'open') {
    const data = await apiRequest(`/api/extended/wiki/lint?status=${encodeURIComponent(status)}`, {
        method: 'GET',
        errorPrefix: 'Failed to load wiki lint issues',
    });
    return Array.isArray(data?.issues) ? data.issues : [];
}

/**
 * @param {number} issueId
 * @param {'resolved' | 'dismissed'} [status='resolved']
 * @returns {Promise<WikiLintIssue>}
 */
export async function resolveWikiLintIssue(issueId, status = 'resolved') {
    const data = await apiRequest(`/api/extended/wiki/lint/${issueId}/resolve`, {
        method: 'POST',
        body: { status },
        errorPrefix: 'Failed to resolve lint issue',
    });
    return data.issue;
}

/**
 * Download the authenticated user's Obsidian `.zip` vault.
 *
 * @returns {Promise<void>}
 */
export async function downloadWikiVaultZip() {
    const token = getToken();
    if (!token) throw new ApiError('Unauthorized', 401);
    const res = await fetch('/api/extended/wiki/export.zip', {
        headers: { 'x-access-token': token },
    });
    if (!res.ok) {
        throw new ApiError(`Export failed (${res.status})`, res.status);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'supernote-wiki.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}
