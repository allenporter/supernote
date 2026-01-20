/**
 * API Client for Supernote Backend
 */

let authToken = localStorage.getItem('supernote_token');

export function setToken(token) {
    authToken = token;
    localStorage.setItem('supernote_token', token);
}

export function getToken() {
    return authToken;
}

export function logout() {
    authToken = null;
    localStorage.removeItem('supernote_token');
    window.location.reload();
}

/**
 * Secure Login Flow
 */
export async function login(email, password) {
    // 1. Wakeup / Get Token (Using query/token endpoint as a pre-check/wakeup)
    // This step in the CLI client ensures a clean session/CSRF token if needed,
    // although for the Web API we primarily rely on the random code flow.
    await fetch('/api/user/query/token', { method: 'POST', body: '{}' });

    // 2. Get Random Code (Challenge)
    const randomCodeResp = await fetch('/api/official/user/query/random/code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account: email })
    });

    if (!randomCodeResp.ok) throw new Error("Failed to get login challenge");
    const { randomCode, timestamp } = await randomCodeResp.json();

    // 3. Hash Password
    // Schema: SHA256(MD5(password) + randomCode)

    // Step 3a: MD5(password)
    // Using SparkMD5 global from CDN
    const md5Password = SparkMD5.hash(password);

    // Step 3b: SHA256(md5Password + randomCode)
    const contentToHash = md5Password + randomCode;
    const sha256Hash = await sha256(contentToHash);

    // 4. Authenticate
    const loginResp = await fetch('/api/official/user/account/login/new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            account: email,
            password: sha256Hash,
            timestamp: timestamp,
            loginMethod: "2", // Email
            equipment: 1 // WEB
        })
    });

    if (!loginResp.ok) {
        if (loginResp.status === 401) throw new Error("Invalid credentials");
        throw new Error("Login failed");
    }

    const loginData = await loginResp.json();
    setToken(loginData.token);
    return loginData;
}

// Helper: SHA-256 using Web Crypto API
async function sha256(message) {
    const msgBuffer = new TextEncoder().encode(message);
    const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Fetch files for a given directory.
 */
export async function fetchFiles(directoryId = "0", pageNo = 1, pageSize = 50) {
    const headers = {
        'Content-Type': 'application/json'
    };
    if (authToken) {
        headers['x-access-token'] = authToken;
    }

    const response = await fetch('/api/file/list/query', {
        method: 'POST',
        headers,
        body: JSON.stringify({
            directoryId: directoryId, // Pass as string/raw to preserve precision
            pageNo,
            pageSize,
            order: "filename",
            sequence: "asc"
        })
    });

    if (!response.ok) {
        if (response.status === 401) {
            // If the token is invalid, clear it
            if (authToken) {
                logout();
                throw new Error("Unauthorized");
            }
            throw new Error("Unauthorized");
        }
        throw new Error(`Failed to fetch files: ${response.statusText}`);
    }

    const data = await response.json();

    // Map backend VO to frontend interface
    return (data.userFileVOList || []).map(file => ({
        id: file.id,
        name: file.fileName,
        isDirectory: file.isFolder === "Y" || file.isFolder === true || file.isFolder === 1,
        size: file.size,
        updatedAt: file.updateTime,
        extension: file.isFolder === "Y" ? null : getExtension(file.fileName)
    }));
}

function getExtension(filename) {
    if (!filename) return null;
    const parts = filename.split('.');
    return parts.length > 1 ? parts.pop().toLowerCase() : null;
}

/**
 * Convert Note to PNG
 * @param {string} fileId
 * @returns {Promise<Array<{pageNo: number, url: string}>>}
 */
export async function convertNoteToPng(fileId) {
    // 1. Get Token
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    // 2. Call API
    const response = await fetch('/api/file/note/to/png', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        },
        body: JSON.stringify({ id: fileId }) // Pass as string to preserve 64-bit precision
    });

    if (!response.ok) {
        if (response.status === 401) {
            logout();
            throw new Error("Unauthorized");
        }
        throw new Error(`Conversion failed: ${response.statusText}`);
    }

    const data = await response.json();
    return data.pngPageVOList || [];
}

/**
 * Fetch summaries for a file
 * @param {string} fileId
 * @returns {Promise<Array<Object>>}
 */
export async function fetchSummaries(fileId) {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/extended/file/summary/list', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        },
        // Extension endpoint expects { fileId: ... }
        body: JSON.stringify({ fileId: fileId })
    });

    if (!response.ok) {
        if (response.status === 401) {
            logout();
            throw new Error("Unauthorized");
        }
        throw new Error(`Summary fetch failed: ${response.statusText}`);
    }

    const data = await response.json();
    return data.summaryDOList || [];
}

/**
 * Fetch system tasks (Extended API).
 * @returns {Promise<Object>} The system task list response.
 */
export async function fetchSystemTasks() {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/extended/system/tasks', {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        }
    });

    if (response.status === 401) {
        logout();
        throw new Error("Unauthorized");
    }

    if (!response.ok) {
        throw new Error(`Failed to fetch system tasks: ${response.statusText}`);
    }

    return await response.json();
}
