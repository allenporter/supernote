/**
 * API Client for Supernote Backend
 */

import { apiRequest, getToken, logout, onLogout, setToken } from './http.js';

export { apiRequest, getToken, logout, setToken };

let socketInstance = null;
const SOCKET_IO_KEY = 'K+5xFzxbnB1iSZWqmu3Etw==';

function arrayBufferToBase64Alnum(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary).replace(/[^a-zA-Z0-9]/g, '');
}

export async function computeSocketSignature(token, connType, randomVal) {
    const raw = `${token}_${connType}_${randomVal}`;
    if (window.crypto && window.crypto.subtle) {
        const enc = new TextEncoder();
        const cryptoKey = await window.crypto.subtle.importKey(
            'raw',
            enc.encode(SOCKET_IO_KEY),
            { name: 'HMAC', hash: 'SHA-256' },
            false,
            ['sign']
        );
        const sigBuffer = await window.crypto.subtle.sign('HMAC', cryptoKey, enc.encode(raw));
        return arrayBufferToBase64Alnum(sigBuffer);
    }
    if (window.sha256 && window.sha256.hmac && typeof window.sha256.hmac.arrayBuffer === 'function') {
        const sigBuffer = window.sha256.hmac.arrayBuffer(SOCKET_IO_KEY, raw);
        return arrayBufferToBase64Alnum(sigBuffer);
    }
    throw new Error('HMAC-SHA256 is not available.');
}

function parseSocketPayload(raw) {
    if (!raw) return null;
    if (typeof raw === 'object') return raw;
    if (typeof raw === 'string') {
        if (raw === 'true' || raw === 'Received') return null;
        try {
            return JSON.parse(raw);
        } catch {
            return null;
        }
    }
    return null;
}

export async function connectSocket() {
    const token = getToken();
    if (!token || typeof window.io !== 'function') return null;
    if (socketInstance && socketInstance.connected) return socketInstance;
    if (socketInstance) {
        socketInstance.disconnect();
        socketInstance = null;
    }

    try {
        const connType = 'WEB';
        const randomVal = String(Date.now());
        const sign = await computeSocketSignature(token, connType, randomVal);
        const socket = window.io('/', {
            path: '/socket.io',
            query: {
                token,
                type: connType,
                random: randomVal,
                sign
            },
            transports: ['polling', 'websocket']
        });

        socket.on('ServerMessage', (data) => {
            const parsed = parseSocketPayload(data);
            if (!parsed) return;
            if (String(parsed.code) === '403') {
                disconnectSocket();
                return;
            }
            socket.emit('ClientMessage', 'Received');
            window.dispatchEvent(new CustomEvent('supernote:file-sync', { detail: parsed }));
        });

        socket.on('to-do', (data) => {
            const parsed = parseSocketPayload(data);
            if (!parsed) return;
            socket.emit('to-do', 'Received');
            window.dispatchEvent(new CustomEvent('supernote:task-sync', { detail: parsed }));
        });

        socket.on('digest', (data) => {
            const parsed = parseSocketPayload(data);
            if (!parsed) return;
            socket.emit('digest', 'Received');
            window.dispatchEvent(new CustomEvent('supernote:digest-sync', { detail: parsed }));
        });

        socketInstance = socket;
        return socket;
    } catch (e) {
        console.error('Failed to connect Socket.IO:', e);
        return null;
    }
}

export function disconnectSocket() {
    if (socketInstance) {
        socketInstance.disconnect();
        socketInstance = null;
    }
}

onLogout(disconnectSocket);

/**
 * Secure Login Flow
 */
export async function login(email, password) {
    await fetch('/api/user/query/token', { method: 'POST', body: '{}' });

    const randomCodeResp = await fetch('/api/official/user/query/random/code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account: email })
    });

    if (!randomCodeResp.ok) throw new Error('Failed to get login challenge');
    const { randomCode, timestamp } = await randomCodeResp.json();

    const md5Password = SparkMD5.hash(password);
    const sha256Hash = await sha256(md5Password + randomCode);

    const loginResp = await fetch('/api/official/user/account/login/new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            account: email,
            password: sha256Hash,
            timestamp,
            loginMethod: '2',
            equipment: 1
        })
    });

    if (!loginResp.ok) {
        if (loginResp.status === 401) throw new Error('Invalid credentials');
        throw new Error('Login failed');
    }

    const loginData = await loginResp.json();
    if (!loginData.success) {
        throw new Error(loginData.errorMsg || 'Invalid credentials');
    }
    setToken(loginData.token);
    return loginData;
}

// SHA-256 using Web Crypto API with fallback for non-secure contexts (e.g. plain HTTP on LAN IP)
async function sha256(message) {
    if (window.crypto && window.crypto.subtle) {
        const msgBuffer = new TextEncoder().encode(message);
        const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    }
    if (typeof window.sha256 === 'function') {
        return window.sha256(message);
    }
    throw new Error('SHA-256 is not available. Please access via HTTPS/localhost or ensure js-sha256 is loaded.');
}

const DEFAULT_FILE_PAGE_SIZE = 100;
const MAX_DIRECTORY_PAGES = 100;

function getExtension(filename) {
    if (!filename) return null;
    const parts = filename.split('.');
    return parts.length > 1 ? parts.pop().toLowerCase() : null;
}

function mapUserFileVO(file) {
    const isDirectory = file.isFolder === 'Y' || file.isFolder === true || file.isFolder === 1;
    return {
        id: file.id,
        name: file.fileName,
        isDirectory,
        size: file.size,
        updatedAt: file.updateTime,
        extension: isDirectory ? null : getExtension(file.fileName)
    };
}

function fetchFilesPage(directoryId, pageNo, pageSize) {
    return apiRequest('/api/file/list/query', {
        body: {
            directoryId,
            pageNo,
            pageSize,
            order: 'filename',
            sequence: 'asc'
        },
        errorPrefix: 'Failed to fetch files'
    });
}

/**
 * Fetch all files and folders for a given directory across pages.
 */
export async function fetchFiles(directoryId = '0', pageSize = DEFAULT_FILE_PAGE_SIZE) {
    const firstPage = await fetchFilesPage(directoryId, 1, pageSize);
    const items = (firstPage.userFileVOList || []).map(mapUserFileVO);
    const totalPages = Math.min(
        MAX_DIRECTORY_PAGES,
        Math.max(1, Number(firstPage.pages) || 1)
    );

    for (let pageNo = 2; pageNo <= totalPages; pageNo++) {
        const nextPage = await fetchFilesPage(directoryId, pageNo, pageSize);
        const pageItems = nextPage.userFileVOList || [];
        if (pageItems.length === 0) break;
        items.push(...pageItems.map(mapUserFileVO));
    }

    return items;
}

/**
 * Query path and ID path for a file or folder.
 * @param {string|number} nodeId
 * @returns {Promise<{success: boolean, path: string, idPath: string}>}
 */
export function fetchPathInfo(nodeId) {
    return apiRequest('/api/file/path/query', {
        body: { id: String(nodeId) },
        errorPrefix: 'Path query failed'
    });
}

/**
 * Convert Note to PNG
 * @param {string} fileId
 * @returns {Promise<Array<{pageNo: number, url: string}>>}
 */
export async function convertNoteToPng(fileId) {
    const data = await apiRequest('/api/file/note/to/png', {
        body: { id: fileId },
        errorPrefix: 'Conversion failed'
    });
    return data.pngPageVOList || [];
}

/**
 * Fetch per-page OCR transcripts for a notebook file.
 * @param {string|number} fileId
 * @returns {Promise<Array<{pageIndex: number, pageId: string, text: string|null, date: string|null}>>}
 */
export async function fetchTranscript(fileId) {
    const data = await apiRequest('/api/extended/transcript', {
        body: { fileId: String(fileId) },
        fallbackValue: null
    });
    return data && Array.isArray(data.pages) ? data.pages : [];
}

/**
 * Fetch summaries for a file
 * @param {string} fileId
 * @returns {Promise<Array<Object>>}
 */
export async function fetchSummaries(fileId) {
    const data = await apiRequest('/api/extended/file/summary/list', {
        body: { fileId: String(fileId) },
        errorPrefix: 'Summary fetch failed'
    });
    return data.summaryDOList || [];
}

/**
 * Search files by keyword.
 */
export async function searchFiles(keyword) {
    const data = await apiRequest('/api/file/label/list/search', {
        body: { keyword },
        fallbackValue: null
    });
    return (data && data.entries) || [];
}

/**
 * Perform semantic vector search across notebook embeddings.
 */
export async function searchSemantic(query, topN = 5) {
    const data = await apiRequest('/api/extended/search', {
        body: { query, topN },
        fallbackValue: null
    });
    return (data && data.results) || [];
}

const DEFAULT_AI_STATUS = {
    success: false,
    hasApiKey: false,
    ocrEnabled: false,
    ocrModel: null,
    summaryEnabled: false,
    summaryModel: null,
    vectorSearchEnabled: false,
    embeddingModel: null,
    model: null,
};

/**
 * Fetch server AI processing configuration status.
 */
export async function fetchAiStatus() {
    const data = await apiRequest('/api/extended/ai/status', {
        method: 'GET',
        requireAuth: false,
        fallbackValue: null
    });
    return data || { ...DEFAULT_AI_STATUS };
}

/**
 * Fetch system tasks (Extended API).
 * @returns {Promise<Object>} The system task list response.
 */
export function fetchSystemTasks() {
    return apiRequest('/api/extended/system/tasks', {
        method: 'GET',
        errorPrefix: 'Failed to fetch system tasks'
    });
}

/**
 * Fetch storage capacity/quota.
 * @returns {Promise<{usedCapacity: number, totalCapacity: number}>}
 */
export function fetchCapacity() {
    return apiRequest('/api/file/capacity/query', {
        body: {},
        errorPrefix: 'Failed to fetch capacity'
    });
}

/**
 * Create a new folder.
 */
export function createFolder(directoryId, folderName) {
    return apiRequest('/api/file/folder/add', {
        body: { directoryId, fileName: folderName },
        errorPrefix: 'Failed to create folder'
    });
}

/**
 * Delete items (files or folders).
 */
export function deleteItems(directoryId, idList) {
    return apiRequest('/api/file/delete', {
        body: { directoryId, idList },
        errorPrefix: 'Failed to delete items'
    });
}

/**
 * Move items to a new directory.
 */
export function moveItems(idList, targetDirectoryId) {
    return apiRequest('/api/file/move', {
        body: {
            idList,
            directoryId: '0',
            goDirectoryId: targetDirectoryId
        },
        errorPrefix: 'Failed to move items'
    });
}

/**
 * Rename an item.
 */
export function renameItem(id, newName) {
    return apiRequest('/api/file/rename', {
        body: { id, newName },
        errorPrefix: 'Failed to rename item'
    });
}

function uploadApply(directoryId, fileName, size, md5) {
    return apiRequest('/api/file/upload/apply', {
        body: { directoryId, fileName, size, md5 },
        errorPrefix: 'Upload apply failed'
    });
}

function uploadFinish(directoryId, fileName, size, md5, innerName) {
    return apiRequest('/api/file/upload/finish', {
        body: {
            directoryId,
            fileName,
            fileSize: size,
            md5,
            innerName,
            type: '2'
        },
        errorPrefix: 'Upload finish failed'
    });
}

/**
 * Upload a file (orchestrates apply, put, and finish).
 */
export async function uploadFile(directoryId, file) {
    const md5 = await calculateFileMd5(file);
    const { fullUploadUrl, innerName } = await uploadApply(directoryId, file.name, file.size, md5);

    const formData = new FormData();
    formData.append('file', file);

    const uploadResp = await fetch(fullUploadUrl, {
        method: 'POST',
        body: formData,
    });

    if (!uploadResp.ok) {
        throw new Error(`File binary upload failed: ${uploadResp.statusText}`);
    }

    return await uploadFinish(directoryId, file.name, file.size, md5, innerName);
}

function calculateFileMd5(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            const hash = SparkMD5.ArrayBuffer.hash(e.target.result);
            resolve(hash);
        };
        reader.onerror = reject;
        reader.readAsArrayBuffer(file);
    });
}

/**
 * Fetch processing status for a list of files.
 * @param {Array<string|number>} fileIds
 * @returns {Promise<{success: boolean, statusMap: Object}>}
 */
export async function fetchProcessingStatus(fileIds) {
    const data = await apiRequest('/api/extended/file/processing/status', {
        body: { fileIds: fileIds.map(String) },
        errorPrefix: 'Failed to fetch processing status'
    });
    return {
        success: true,
        statusMap: data.statusMap
    };
}

/**
 * Get a signed download URL for a stored file.
 */
export async function fetchDownloadUrl(fileId) {
    const data = await apiRequest('/api/file/download/url', {
        body: { id: fileId },
        errorPrefix: 'Download failed'
    });
    if (!data.url) throw new Error('No download URL returned');
    return data.url;
}

/**
 * Trigger a browser download of a stored file.
 */
export async function downloadFile(fileId) {
    const url = await fetchDownloadUrl(fileId);
    const link = document.createElement('a');
    link.href = url;
    link.rel = 'noopener';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

/**
 * Fetch a lightweight single-page cover preview URL (page 0) for a notebook.
 * @param {string|number} fileId
 * @returns {Promise<string|null>}
 */
export async function fetchNoteCover(fileId) {
    const data = await apiRequest('/api/extended/file/note/cover', {
        body: { fileId: String(fileId) },
        fallbackValue: null
    });
    return (data && data.url) || null;
}

/**
 * Fetch structural and per-page metadata for a .note file.
 * @param {string|number} fileId
 * @returns {Promise<Object|null>}
 */
export function fetchNoteMetadata(fileId) {
    return apiRequest('/api/extended/file/note/metadata', {
        body: { fileId: String(fileId) },
        fallbackValue: null
    });
}
