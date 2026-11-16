/**
 * Shared HTTP transport and session token state for the Supernote Web UI.
 */

const TOKEN_STORAGE_KEY = 'supernote_token';

/**
 * Structured HTTP error raised by `apiRequest` with status code and parsed body.
 */
export class ApiError extends Error {
    /**
     * @param {string} message
     * @param {number} status
     * @param {unknown} [data=null]
     */
    constructor(message, status, data = null) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.data = data;
    }
}

/** @type {string | null} */
let authToken = localStorage.getItem(TOKEN_STORAGE_KEY);
/** @type {Set<() => void>} */
const logoutListeners = new Set();

/**
 * @param {string} token
 */
export function setToken(token) {
    authToken = token;
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

/**
 * @returns {string | null}
 */
export function getToken() {
    return authToken;
}

/**
 * Register a cleanup callback invoked synchronously when the session logs out.
 * @param {() => void} listener
 * @returns {() => boolean} Unsubscribe function
 */
export function onLogout(listener) {
    logoutListeners.add(listener);
    return () => logoutListeners.delete(listener);
}

/**
 * @param {{ reload?: boolean }} [options]
 */
export async function logout({ reload = true } = {}) {
    const token = authToken;
    authToken = null;
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    for (const listener of logoutListeners) {
        try {
            listener();
        } catch (e) {
            console.error('Logout listener error:', e);
        }
    }
    if (token) {
        try {
            await fetch('/api/user/logout', {
                method: 'POST',
                headers: { 'x-access-token': token },
                keepalive: true,
            });
        } catch {
            // Ignore network errors during logout
        }
    }
    if (reload && typeof window !== 'undefined' && window.location) {
        window.location.reload();
    }
}

/**
 * Perform an API request with unified token headers, 401 session teardown,
 * and consistent error/fallback handling.
 *
 * @template [T=any]
 * @param {string} path
 * @param {Object} [options]
 * @param {string} [options.method='POST']
 * @param {unknown} [options.body]
 * @param {Record<string, string>} [options.headers]
 * @param {boolean} [options.requireAuth=true]
 * @param {boolean} [options.reloadOnUnauthorized=true]
 * @param {'json'|'text'} [options.responseType='json']
 * @param {string} [options.errorPrefix='Request failed']
 * @param {unknown} [options.fallbackValue]
 * @returns {Promise<T>}
 */
export async function apiRequest(
    path,
    {
        method = 'POST',
        body = undefined,
        headers: extraHeaders = undefined,
        requireAuth = true,
        reloadOnUnauthorized = true,
        responseType = 'json',
        errorPrefix = 'Request failed',
        fallbackValue = undefined,
    } = {},
) {
    const token = getToken();
    if (requireAuth && !token) {
        throw new ApiError('Unauthorized', 401);
    }

    /** @type {Record<string, string>} */
    const headers = { ...(extraHeaders || {}) };
    if (body !== undefined && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
    }
    if (token) {
        headers['x-access-token'] = token;
    }

    const response = await fetch(path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    if (response.status === 401) {
        if (token) {
            await logout({ reload: reloadOnUnauthorized });
        }
        throw new ApiError('Unauthorized', 401);
    }

    if (!response.ok) {
        if (fallbackValue !== undefined) {
            return /** @type {T} */ (fallbackValue);
        }
        const errorData = await response.json().catch(() => null);
        const serverDetail =
            errorData?.error_description ||
            errorData?.errorMsg ||
            errorData?.error ||
            errorData?.message;
        const message = serverDetail
            ? String(serverDetail)
            : `${errorPrefix}: ${response.statusText || `HTTP ${response.status}`}`;
        throw new ApiError(message, response.status, errorData);
    }

    if (responseType === 'text') {
        return /** @type {T} */ (await response.text());
    }
    return await response.json();
}
