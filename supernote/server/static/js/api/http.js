/**
 * Shared HTTP transport and session token state for the Supernote Web UI.
 */

const TOKEN_STORAGE_KEY = 'supernote_token';

let authToken = localStorage.getItem(TOKEN_STORAGE_KEY);
const logoutListeners = new Set();

export function setToken(token) {
    authToken = token;
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

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
 * @param {string} path
 * @param {Object} [options]
 * @param {string} [options.method='POST']
 * @param {unknown} [options.body]
 * @param {boolean} [options.requireAuth=true]
 * @param {'json'|'text'} [options.responseType='json']
 * @param {string} [options.errorPrefix='Request failed']
 * @param {unknown} [options.fallbackValue]
 */
export async function apiRequest(
    path,
    {
        method = 'POST',
        body = undefined,
        requireAuth = true,
        responseType = 'json',
        errorPrefix = 'Request failed',
        fallbackValue = undefined,
    } = {}
) {
    const token = getToken();
    if (requireAuth && !token) {
        throw new Error('Unauthorized');
    }

    const headers = {};
    if (body !== undefined) {
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
            logout();
        }
        throw new Error('Unauthorized');
    }

    if (!response.ok) {
        if (fallbackValue !== undefined) {
            return fallbackValue;
        }
        throw new Error(`${errorPrefix}: ${response.statusText}`);
    }

    if (responseType === 'text') {
        return await response.text();
    }
    return await response.json();
}
