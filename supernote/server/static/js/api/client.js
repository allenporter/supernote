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

/**
 * Fetch files for a given directory.
 * Maps the backend UserFileVO to the frontend SupernoteFile interface.
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
            directoryId: parseInt(directoryId),
            pageNo,
            pageSize,
            order: "filename",
            sequence: "asc"
        })
    });

    if (!response.ok) {
        if (response.status === 401) {
            throw new Error("Unauthorized");
        }
        throw new Error(`Failed to fetch files: ${response.statusText}`);
    }

    const data = await response.json();

    // Map backend VO to frontend interface
    return (data.userFileVOList || []).map(file => ({
        id: file.id,
        name: file.fileName,
        isDirectory: file.isFolder === "Y" || file.isFolder === true || file.isFolder === 1, // Handle various BooleanEnum serializations
        size: file.size,
        updatedAt: file.updateTime, // Expected to be ISO string or similar
        extension: file.isFolder === "Y" ? null : getExtension(file.fileName)
    }));
}

function getExtension(filename) {
    if (!filename) return null;
    const parts = filename.split('.');
    return parts.length > 1 ? parts.pop().toLowerCase() : null;
}
