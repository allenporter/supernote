/**
 * API Client for Supernote Backend
 */

import { getFileExtension } from '../utils/format.js';
import { ApiError, apiRequest, getToken, onLogout, setToken } from './http.js';

/** @type {SocketClient | null} */
let socketInstance = null;
/** @type {Promise<SocketClient | null> | null} */
let connectingSocketPromise = null;
let socketEpoch = 0;
const SOCKET_IO_KEY = 'K+5xFzxbnB1iSZWqmu3Etw==';

/**
 * @param {ArrayBuffer} buffer
 * @returns {string}
 */
function arrayBufferToBase64Alnum(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary).replace(/[^a-zA-Z0-9]/g, '');
}

/**
 * @param {string} token
 * @param {string} connType
 * @param {string} randomVal
 * @returns {Promise<string>}
 */
export async function computeSocketSignature(token, connType, randomVal) {
    const raw = `${token}_${connType}_${randomVal}`;
    if (window.crypto?.subtle) {
        const enc = new TextEncoder();
        const cryptoKey = await window.crypto.subtle.importKey(
            'raw',
            enc.encode(SOCKET_IO_KEY),
            { name: 'HMAC', hash: 'SHA-256' },
            false,
            ['sign'],
        );
        const sigBuffer = await window.crypto.subtle.sign('HMAC', cryptoKey, enc.encode(raw));
        return arrayBufferToBase64Alnum(sigBuffer);
    }
    if (typeof window.sha256?.hmac?.arrayBuffer === 'function') {
        const sigBuffer = window.sha256.hmac.arrayBuffer(SOCKET_IO_KEY, raw);
        return arrayBufferToBase64Alnum(sigBuffer);
    }
    throw new Error('HMAC-SHA256 is not available.');
}

/**
 * @param {unknown} raw
 * @returns {Record<string, unknown> | null}
 */
function parseSocketPayload(raw) {
    if (!raw) return null;
    if (typeof raw === 'object') return /** @type {Record<string, unknown>} */ (raw);
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

export function connectSocket() {
    const token = getToken();
    const ioFactory = window.io;
    if (!token || typeof ioFactory !== 'function') return Promise.resolve(null);
    if (socketInstance?.connected) return Promise.resolve(socketInstance);
    if (connectingSocketPromise) return connectingSocketPromise;

    const epoch = ++socketEpoch;
    if (socketInstance) {
        socketInstance.disconnect();
        socketInstance = null;
    }

    connectingSocketPromise = (async () => {
        try {
            const connType = 'WEB';
            const randomVal = String(Date.now());
            const sign = await computeSocketSignature(token, connType, randomVal);
            if (epoch !== socketEpoch || getToken() !== token) {
                return null;
            }
            const socket = ioFactory('/', {
                path: '/socket.io',
                query: {
                    token,
                    type: connType,
                    random: randomVal,
                    sign,
                },
                transports: ['polling', 'websocket'],
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
        } finally {
            if (epoch === socketEpoch) {
                connectingSocketPromise = null;
            }
        }
    })();

    return connectingSocketPromise;
}

export function disconnectSocket() {
    socketEpoch++;
    connectingSocketPromise = null;
    if (socketInstance) {
        socketInstance.disconnect();
        socketInstance = null;
    }
}

onLogout(disconnectSocket);

/**
 * Secure challenge-response login flow.
 * @param {string} email
 * @param {string} password
 * @returns {Promise<void>}
 */
export async function login(email, password) {
    // Pre-check / wakeup token endpoint (mirrors the CLI client session flow
    // before starting the challenge-response handshake).
    await fetch('/api/user/query/token', { method: 'POST', body: '{}' }).catch(() => null);

    // Request login challenge (randomCode + timestamp); surfaces 429 rate-limit errorMsg via ApiError
    const { randomCode, timestamp } = await apiRequest('/api/official/user/query/random/code', {
        body: { account: email },
        requireAuth: false,
        reloadOnUnauthorized: false,
        errorPrefix: 'Failed to get login challenge',
    });

    // Hash password with challenge: SHA256(MD5(password) + randomCode)
    const md5Password = SparkMD5.hash(password);
    const sha256Hash = await sha256(md5Password + randomCode);

    // Submit challenge-response credentials
    let loginData;
    try {
        loginData = await apiRequest('/api/official/user/account/login/new', {
            body: {
                account: email,
                password: sha256Hash,
                timestamp,
                loginMethod: '2', // Email
                equipment: 1, // WEB
            },
            requireAuth: false,
            reloadOnUnauthorized: false,
            errorPrefix: 'Login failed',
        });
    } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
            throw new Error('Invalid credentials');
        }
        throw e;
    }

    if (!loginData?.success || !loginData.token) {
        throw new Error(loginData?.errorMsg || 'Invalid credentials');
    }
    setToken(loginData.token);
}

/**
 * Submit an OAuth 2.1 consent decision (`approve` or `deny`) to `/login-bridge`
 * and return the authorized redirect URL.
 * @param {string} bridgePathWithQuery
 * @param {'approve' | 'deny'} decision
 * @returns {Promise<string>}
 */
export async function submitOAuthBridgeDecision(bridgePathWithQuery, decision) {
    const data = await apiRequest(bridgePathWithQuery, {
        body: { decision },
        headers: { Accept: 'application/json' },
        reloadOnUnauthorized: false,
        errorPrefix: 'Authorization failed',
    });
    if (!data?.redirect_url) {
        throw new Error('Authorization failed: missing redirect URL');
    }
    return String(data.redirect_url);
}

/**
 * SHA-256 using Web Crypto API with fallback for non-secure contexts (e.g. plain HTTP on LAN IP).
 * @param {string} message
 * @returns {Promise<string>}
 */
async function sha256(message) {
    if (window.crypto?.subtle) {
        const msgBuffer = new TextEncoder().encode(message);
        const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
    }
    if (typeof window.sha256 === 'function') {
        return window.sha256(message);
    }
    throw new Error(
        'SHA-256 is not available. Please access via HTTPS/localhost or ensure js-sha256 is loaded.',
    );
}

const DEFAULT_FILE_PAGE_SIZE = 100;
const MAX_DIRECTORY_PAGES = 100;

/**
 * @param {Record<string, any>} file
 * @returns {FileItem}
 */
function mapUserFileVO(file) {
    const isDirectory = file.isFolder === 'Y' || file.isFolder === true || file.isFolder === 1;
    const ext = isDirectory ? null : getFileExtension(file.fileName) || null;
    return {
        id: String(file.id),
        name: file.fileName,
        isDirectory,
        size: file.size,
        updatedAt: file.updateTime,
        extension: ext,
    };
}

/**
 * @param {string | number} directoryId
 * @param {number} pageNo
 * @param {number} pageSize
 */
function fetchFilesPage(directoryId, pageNo, pageSize) {
    return apiRequest('/api/file/list/query', {
        body: {
            directoryId, // Pass as string/raw to preserve 64-bit VFS ID precision
            pageNo,
            pageSize,
            order: 'filename',
            sequence: 'asc',
        },
        errorPrefix: 'Failed to fetch files',
    });
}

/**
 * Fetch all files and folders for a given directory across pages.
 * @param {string | number} [directoryId='0']
 * @param {number} [pageSize]
 * @returns {Promise<FileItem[]>}
 */
export async function fetchFiles(directoryId = '0', pageSize = DEFAULT_FILE_PAGE_SIZE) {
    const firstPage = await fetchFilesPage(directoryId, 1, pageSize);
    const items = (firstPage.userFileVOList || []).map(mapUserFileVO);
    const totalPages = Math.min(MAX_DIRECTORY_PAGES, Math.max(1, Number(firstPage.pages) || 1));

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
 * @param {string | number} nodeId
 * @returns {Promise<PathInfo>}
 */
export async function fetchPathInfo(nodeId) {
    const data = await apiRequest('/api/file/path/query', {
        body: { id: String(nodeId) },
        errorPrefix: 'Path query failed',
    });
    return {
        path: data?.path || '',
        idPath: data?.idPath || '',
    };
}

/**
 * Convert Note to PNG pages.
 * @param {string} fileId
 * @returns {Promise<NotePngPage[]>}
 */
export async function convertNoteToPng(fileId) {
    const data = await apiRequest('/api/file/note/to/png', {
        body: { id: fileId }, // Pass as string to preserve 64-bit precision
        errorPrefix: 'Conversion failed',
    });
    return data.pngPageVOList || [];
}

/**
 * Normalize raw transcript page entries into canonical `TranscriptPage` objects.
 * @param {unknown} rawPages
 * @returns {TranscriptPage[]}
 */
export function normalizeTranscriptPages(rawPages) {
    if (!Array.isArray(rawPages)) return [];
    return rawPages.map((p, idx) => ({
        pageIndex:
            typeof p.pageIndex === 'number'
                ? p.pageIndex
                : typeof p.page_index === 'number'
                  ? p.page_index
                  : idx,
        pageId: String(p.pageId || p.page_id || `page-${idx}`),
        text: p.text ?? '',
        date: p.date || null,
    }));
}

/**
 * Fetch per-page OCR transcripts for a notebook file.
 * @param {string | number} fileId
 * @returns {Promise<TranscriptPage[]>}
 */
export async function fetchTranscript(fileId) {
    const data = await apiRequest('/api/extended/transcript', {
        body: { fileId: String(fileId) },
        fallbackValue: null,
    });
    return normalizeTranscriptPages(data?.pages);
}

/**
 * Fetch synthesized non-OCR summaries for a notebook file.
 * @param {string | number} fileId
 * @returns {Promise<NoteSummary[]>}
 */
export async function fetchSummaries(fileId) {
    const data = await apiRequest('/api/extended/file/summary/list', {
        // Extended endpoint expects { fileId } rather than official { id }
        body: { fileId: String(fileId) },
        errorPrefix: 'Summary fetch failed',
    });
    /** @type {Array<Record<string, any>>} */
    const rawList = Array.isArray(data?.summaryDOList) ? data.summaryDOList : [];
    return rawList
        .filter(
            (s) => s.isSummaryGroup !== 'Y' && String(s.dataSource || '').toUpperCase() !== 'OCR',
        )
        .map((s, idx) => ({
            id: String(s.id ?? s.uniqueIdentifier ?? idx),
            name: s.name || null,
            content: s.content || '',
            dataSource: s.dataSource || null,
        }));
}

/**
 * Search files and folders by keyword and map `EntriesVO` payloads into `SearchFileMatch` items.
 * @param {string} keyword
 * @returns {Promise<SearchFileMatch[]>}
 */
export async function searchFiles(keyword) {
    const data = await apiRequest('/api/file/label/list/search', {
        body: { keyword },
        fallbackValue: null,
    });
    /** @type {Array<Record<string, any>>} */
    const entries = Array.isArray(data?.entries) ? data.entries : [];
    return entries.map((f) => {
        const fileName = String(f.name || f.fileName || '');
        const isDirectory = f.tag === 'folder' || Boolean(f.isDirectory);
        const ext = isDirectory ? null : getFileExtension(fileName) || null;
        return {
            id: String(f.id),
            name: fileName,
            path: String(f.path_display || f.parent_path || fileName),
            isDirectory,
            size: typeof f.size === 'number' ? f.size : 0,
            updatedAt: f.lastUpdateTime || 0,
            extension: ext,
        };
    });
}

/**
 * Perform semantic vector search across notebook embeddings.
 * @param {string} query
 * @param {number} [topN=5]
 * @returns {Promise<SemanticSearchMatch[]>}
 */
export async function searchSemantic(query, topN = 5) {
    const data = await apiRequest('/api/extended/search', {
        body: { query, topN },
        fallbackValue: null,
    });
    /** @type {Array<Record<string, any>>} */
    const rawResults = Array.isArray(data?.results) ? data.results : [];
    return rawResults.map((r, idx) => {
        const fileId = String(r.fileId ?? r.file_id ?? '');
        const fileName = String(r.fileName ?? r.file_name ?? `Notebook ${fileId}`);
        const pageIndex =
            typeof r.pageIndex === 'number'
                ? r.pageIndex
                : typeof r.page_index === 'number'
                  ? r.page_index
                  : 0;
        const extension = getFileExtension(fileName) || 'note';
        return {
            key: String(r.pageId ?? r.page_id ?? `${fileId}-${pageIndex}-${idx}`),
            fileId,
            fileName,
            extension,
            pageIndex,
            pageNumber: pageIndex + 1,
            score: typeof r.score === 'number' ? r.score : 0,
            textPreview: String(r.textPreview ?? r.text_preview ?? ''),
            date: r.date || null,
        };
    });
}

/** @type {AiStatus} */
const DEFAULT_AI_STATUS = {
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
 * @returns {Promise<AiStatus>}
 */
export async function fetchAiStatus() {
    const data = await apiRequest('/api/extended/ai/status', {
        method: 'GET',
        requireAuth: false,
        fallbackValue: null,
    });
    if (!data) return { ...DEFAULT_AI_STATUS };
    return {
        hasApiKey: Boolean(data.hasApiKey),
        ocrEnabled: Boolean(data.ocrEnabled),
        ocrModel: data.ocrModel ?? null,
        summaryEnabled: Boolean(data.summaryEnabled),
        summaryModel: data.summaryModel ?? null,
        vectorSearchEnabled: Boolean(data.vectorSearchEnabled),
        embeddingModel: data.embeddingModel ?? null,
        model: data.model ?? null,
    };
}

/**
 * Fetch recent background system tasks (Extended API).
 * @returns {Promise<SystemTaskItem[]>}
 */
export async function fetchSystemTasks() {
    const data = await apiRequest('/api/extended/system/tasks', {
        method: 'GET',
        errorPrefix: 'Failed to fetch system tasks',
    });
    return Array.isArray(data?.tasks) ? data.tasks : [];
}

/**
 * Fetch storage capacity/quota.
 * @returns {Promise<CapacityInfo>}
 */
export function fetchCapacity() {
    return apiRequest('/api/file/capacity/query', {
        body: {},
        errorPrefix: 'Failed to fetch capacity',
    });
}

/**
 * Create a new folder.
 * @param {string | number} directoryId
 * @param {string} folderName
 * @returns {Promise<void>}
 */
export async function createFolder(directoryId, folderName) {
    await apiRequest('/api/file/folder/add', {
        body: { directoryId, fileName: folderName },
        errorPrefix: 'Failed to create folder',
    });
}

/**
 * Delete items (files or folders).
 * @param {string | number} directoryId
 * @param {Array<string | number>} idList
 * @returns {Promise<void>}
 */
export async function deleteItems(directoryId, idList) {
    await apiRequest('/api/file/delete', {
        body: { directoryId, idList },
        errorPrefix: 'Failed to delete items',
    });
}

/**
 * Move items to a new directory.
 * @param {Array<string | number>} idList
 * @param {string | number} targetDirectoryId
 * @returns {Promise<void>}
 */
export async function moveItems(idList, targetDirectoryId) {
    await apiRequest('/api/file/move', {
        body: {
            idList,
            directoryId: '0', // Not strictly required for move, included for official DTO compliance
            goDirectoryId: targetDirectoryId,
        },
        errorPrefix: 'Failed to move items',
    });
}

/**
 * Rename an item.
 * @param {string | number} id
 * @param {string} newName
 * @returns {Promise<void>}
 */
export async function renameItem(id, newName) {
    await apiRequest('/api/file/rename', {
        body: { id, newName },
        errorPrefix: 'Failed to rename item',
    });
}

/**
 * File Upload: Apply for signed OSS upload URL.
 * @param {string | number} directoryId
 * @param {string} fileName
 * @param {number} size
 * @param {string} md5
 * @returns {Promise<{ fullUploadUrl: string, innerName: string }>}
 */
function uploadApply(directoryId, fileName, size, md5) {
    return apiRequest('/api/file/upload/apply', {
        body: { directoryId, fileName, size, md5 },
        errorPrefix: 'Upload apply failed',
    });
}

/**
 * File Upload: Commit uploaded blob in VFS.
 * @param {string | number} directoryId
 * @param {string} fileName
 * @param {number} size
 * @param {string} md5
 * @param {string} innerName
 * @returns {Promise<void>}
 */
async function uploadFinish(directoryId, fileName, size, md5, innerName) {
    await apiRequest('/api/file/upload/finish', {
        body: {
            directoryId,
            fileName,
            fileSize: size,
            md5,
            innerName,
            type: '2', // CLOUD
        },
        errorPrefix: 'Upload finish failed',
    });
}

/**
 * Upload a file (orchestrates apply, put, and finish).
 * @param {string | number} directoryId
 * @param {File} file
 * @returns {Promise<void>}
 */
export async function uploadFile(directoryId, file) {
    // Calculate MD5 digest used for apply/finish integrity verification
    const md5 = await calculateFileMd5(file);

    // Apply for signed OSS upload URL
    const { fullUploadUrl, innerName } = await uploadApply(directoryId, file.name, file.size, md5);

    // Upload binary to blob storage as multipart FormData
    const formData = new FormData();
    formData.append('file', file);

    const uploadResp = await fetch(fullUploadUrl, {
        method: 'POST', // Both POST and PUT are supported by oss.py handle_oss_upload
        body: formData,
        // Note: Do NOT set Content-Type header; fetch sets it with the multipart boundary
    });

    if (!uploadResp.ok) {
        throw new Error(`File binary upload failed: ${uploadResp.statusText}`);
    }

    // Commit uploaded blob into the VFS
    await uploadFinish(directoryId, file.name, file.size, md5, innerName);
}

/**
 * @param {Blob} file
 * @returns {Promise<string>}
 */
function calculateFileMd5(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            if (!(reader.result instanceof ArrayBuffer)) {
                reject(new Error('Expected ArrayBuffer from FileReader'));
                return;
            }
            const hash = SparkMD5.ArrayBuffer.hash(reader.result);
            resolve(hash);
        };
        reader.onerror = reject;
        reader.readAsArrayBuffer(file);
    });
}

/**
 * Fetch processing status map (`fileId -> status`) for a list of files.
 * @param {Array<string | number>} fileIds
 * @returns {Promise<Record<string, ProcessingStatus>>}
 */
export async function fetchProcessingStatus(fileIds) {
    const data = await apiRequest('/api/extended/file/processing/status', {
        body: { fileIds: fileIds.map(String) },
        errorPrefix: 'Failed to fetch processing status',
    });
    return data?.statusMap || {};
}

/**
 * Get a signed download URL for a stored file.
 * @param {string | number} fileId
 * @returns {Promise<string>}
 */
export async function fetchDownloadUrl(fileId) {
    const data = await apiRequest('/api/file/download/url', {
        body: { id: fileId },
        errorPrefix: 'Download failed',
    });
    if (!data.url) throw new Error('No download URL returned');
    return data.url;
}

/**
 * Trigger a browser download of a stored file.
 *
 * Navigates to the signed URL rather than fetching the bytes into a Blob the
 * way the .ics export does: a notebook can be hundreds of megabytes, and this
 * way the browser streams it to disk with a progress bar and the server never
 * holds it in memory. The signature carries the identity, so no header is
 * needed on the request that actually moves the file.
 *
 * @param {string | number} fileId
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
 * @param {string | number} fileId
 * @returns {Promise<string | null>}
 */
export async function fetchNoteCover(fileId) {
    const data = await apiRequest('/api/extended/file/note/cover', {
        body: { fileId: String(fileId) },
        fallbackValue: null,
    });
    return data?.url || null;
}

/**
 * Fetch structural and per-page metadata for a .note file.
 * @param {string | number} fileId
 * @returns {Promise<NoteMetadata | null>}
 */
export function fetchNoteMetadata(fileId) {
    return apiRequest('/api/extended/file/note/metadata', {
        body: { fileId: String(fileId) },
        fallbackValue: null,
    });
}
