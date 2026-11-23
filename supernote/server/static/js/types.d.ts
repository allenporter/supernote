/**
 * Ambient TypeScript declarations for the no-build Supernote Cloud Web UI:
 * - Browser CDN globals (SparkMD5, js-sha256, Socket.IO, Vue 3 ESM importmap)
 * - Backend API DTOs and frontend domain models
 * - Host UI extension contract (PluginHostContext / SupernoteUiPlugin)
 */

interface SocketClient {
    connected: boolean;
    on(event: string, listener: (data: unknown) => void): this;
    emit(event: string, ...args: unknown[]): this;
    disconnect(): this;
}

declare const SparkMD5: {
    hash(str: string): string;
    ArrayBuffer: {
        hash(arr: ArrayBuffer): string;
    };
};

interface Window {
    sha256?: ((message: string) => string) & {
        hmac?: {
            arrayBuffer?: (key: string, message: string) => ArrayBuffer;
        };
    };
    io?: (url: string, options?: Record<string, unknown>) => SocketClient;
}

interface WindowEventMap {
    'supernote:file-sync': CustomEvent<Record<string, unknown>>;
    'supernote:task-sync': CustomEvent<Record<string, unknown>>;
    'supernote:digest-sync': CustomEvent<Record<string, unknown>>;
}

declare module 'vue' {
    export interface Ref<T = unknown> {
        value: T;
    }

    export interface ComputedRef<T = unknown> {
        readonly value: T;
    }

    export interface WatchOptions {
        immediate?: boolean;
        deep?: boolean;
        flush?: 'pre' | 'post' | 'sync';
        once?: boolean;
    }

    export function ref<T>(value: T): Ref<T>;
    export function ref<T = undefined>(): Ref<T | undefined>;
    export function computed<T>(getter: () => T): ComputedRef<T>;
    export function watch<T>(
        source: Ref<T> | ComputedRef<T> | (() => T),
        callback: (newValue: T, oldValue: T) => void | Promise<void>,
        options?: WatchOptions,
    ): () => void;
    export function watch(
        sources: ReadonlyArray<unknown>,
        callback: (newValues: any[], oldValues: any[]) => void | Promise<void>,
        options?: WatchOptions,
    ): () => void;
    export function nextTick(fn?: () => void): Promise<void>;
    export function onMounted(hook: () => void | Promise<void>): void;
    export function onUnmounted(hook: () => void): void;

    export interface AppInstance {
        component(name: string, definition: Record<string, unknown>): AppInstance;
        mount(rootContainer: string | Element): unknown;
    }

    export function createApp(rootComponent: Record<string, unknown>): AppInstance;
}

declare module 'marked' {
    export interface MarkedCheckboxToken {
        checked: boolean;
    }

    export interface MarkedListItemToken {
        tokens: unknown[];
        task: boolean;
        checked?: boolean;
    }

    export interface MarkedRendererThis {
        parser: {
            parse(tokens: unknown[]): string;
            parseInline(tokens: unknown[]): string;
        };
    }

    export interface MarkedRendererExtension {
        checkbox?: (this: MarkedRendererThis, token: MarkedCheckboxToken) => string | false;
        listitem?: (this: MarkedRendererThis, token: MarkedListItemToken) => string | false;
        [key: string]: ((this: MarkedRendererThis, token: any) => string | false) | undefined;
    }

    export interface MarkedExtension {
        gfm?: boolean;
        breaks?: boolean;
        renderer?: MarkedRendererExtension;
    }

    export class Marked {
        constructor(...extensions: MarkedExtension[]);
        parse(src: string, options?: { async?: false }): string;
    }
}

declare module 'dompurify' {
    export interface DOMPurifyConfig {
        USE_PROFILES?: {
            html?: boolean;
            svg?: boolean;
            svgFilters?: boolean;
            mathMl?: boolean;
        };
        FORBID_TAGS?: string[];
        FORBID_ATTR?: string[];
        ADD_TAGS?: string[];
        ADD_ATTR?: string[];
    }

    const DOMPurify: {
        sanitize(dirty: string, cfg?: DOMPurifyConfig): string;
    };

    export default DOMPurify;
}

// ---------------------------------------------------------------------------
// Core Frontend Domain & API DTO Models
// ---------------------------------------------------------------------------

type ToastType = 'error' | 'success' | 'info';
type ProcessingStatus = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';

interface ToastMessage {
    id: number;
    message: string;
    type: ToastType;
}

interface FileItem {
    id: string;
    name: string;
    isDirectory: boolean;
    size?: number;
    updatedAt?: number | string;
    extension?: string | null;
    pageIndex?: number;
}

interface RecycleItem {
    id: string;
    name: string;
    isDirectory: boolean;
    size: number;
    deletedAt: number | null;
    extension: string | null;
}

interface SearchFileMatch extends FileItem {
    path: string;
}

interface SemanticSearchMatch {
    key: string;
    fileId: string;
    fileName: string;
    extension: string;
    pageIndex: number;
    pageNumber: number;
    score: number;
    textPreview: string;
    date: string | null;
}

interface BreadcrumbItem {
    id: string;
    name: string;
}

interface PathInfo {
    path: string;
    idPath: string;
}

interface CapacityInfo {
    usedCapacity: number;
    totalCapacity: number;
}

interface NotePngPage {
    pageNo: number;
    url: string;
}

interface NoteSummary {
    id: string;
    name: string | null;
    content: string;
    dataSource: string | null;
}

interface SystemTaskItem {
    id: string;
    fileId: string;
    taskType: string;
    key: string;
    status: ProcessingStatus;
    retryCount: number;
    updateTime: number;
    lastError: string | null;
}

type TaskImportance = 'high' | 'medium' | 'low';
type TaskStatus = 'needsAction' | 'completed';

interface ScheduleTaskGroup {
    id: string;
    title: string;
}

interface ScheduleTask {
    id: string;
    taskListId: string | null;
    title: string;
    detail: string;
    status: TaskStatus;
    importance: TaskImportance;
    dueTime: number;
    completedTime: number;
    isReminderOn: boolean;
    links: string | null;
    sort: number | null;
    sortCompleted: number | null;
    planerSort: number | null;
    allSort: number | null;
    updateTime: number;
}

interface ScheduleTaskInput {
    id?: string | number | null;
    taskId?: string | number | null;
    taskListId?: string | number | null;
    title?: string;
    detail?: string;
    importance?: string;
    status?: TaskStatus | string;
    dueTime?: number;
    completedTime?: number;
    lastModified?: number;
    isReminderOn?: boolean;
}

interface FocusedTaskRequest {
    id: string;
    title: string;
    status: TaskStatus;
    seq: number;
}

interface TranscriptPage {
    pageIndex: number;
    pageId: string;
    text: string;
    date: string | null;
    hasTranscript?: boolean;
}

interface NoteTitle {
    pageIndex: number;
    level: number;
}

interface NotePageMeta {
    pageIndex: number;
    pageId?: string;
    date?: string | null;
    style?: string | null;
    isBlank?: boolean;
    hasFiveStar?: boolean;
    keywords?: string[];
}

interface NoteLink {
    pageIndex: number;
    linkType?: 'page' | 'file' | 'web';
    target?: string | null;
    targetFileId?: string | number | null;
    targetPageIndex?: number | null;
}

interface NoteMetadata {
    fileId?: string;
    equipment?: string | null;
    totalPages?: number;
    keywords?: Record<string, number[]>;
    titles?: NoteTitle[];
    pages?: NotePageMeta[];
    links?: NoteLink[];
}

interface AiStatus {
    hasApiKey: boolean;
    ocrEnabled: boolean;
    ocrModel: string | null;
    summaryEnabled: boolean;
    summaryModel: string | null;
    vectorSearchEnabled: boolean;
    embeddingModel: string | null;
    model: string | null;
}

interface OAuthGrant {
    id: string;
    clientId: string;
    scopes: string[];
    createdAt: number;
    expiresAt: number;
    lastUsedAt: number | null;
}

interface ApiKeyInfo {
    id: string;
    name: string;
    keyPrefix: string;
    createdAt: number;
    lastUsedAt: number | null;
    expiresAt: number | null;
}

interface CreatedApiKey {
    id: string;
    name: string;
    key: string;
    createdAt: number;
    expiresAt: number | null;
}

interface OAuthRedirectTarget {
    scheme: string;
    isCustomScheme: boolean;
    hostLabel: string;
    fullUri: string;
}

interface OAuthBridgeRequest {
    isValid: boolean;
    error: string | null;
    clientId: string;
    redirectUri: string;
    codeChallenge: string;
    state: string | null;
    resource: string | null;
    scopes: string[];
    redirectTarget: OAuthRedirectTarget;
    bridgePathWithQuery: string | null;
}

// ---------------------------------------------------------------------------
// Host UI Extension Contract (for dynamic ES module plugins)
// ---------------------------------------------------------------------------

interface ServerPluginDescriptor {
    id: string;
    name: string;
    version?: string;
    description?: string;
    uiModuleUrl?: string | null;
}

interface PluginNavTab {
    id: string;
    label: string;
    iconSvg?: string;
    component: Record<string, unknown>;
}

interface PluginToolbarAction {
    id: string;
    label: string;
    iconSvg?: string;
    onClick: (context: { directoryId: string; folderPath: string }) => void | Promise<void>;
}

interface PluginViewerAction {
    id: string;
    label: string;
    iconSvg?: string;
    fileCategories?: Array<'note' | 'pdf' | 'image' | 'text' | 'unsupported'>;
    onClick: (context: { file: FileItem; activePageIndex: number }) => void | Promise<void>;
}

interface PluginHostContext {
    fetchJson<T = unknown>(
        path: string,
        options?: { method?: string; body?: unknown; headers?: Record<string, string> },
    ): Promise<T>;
    showToast(message: string, type?: ToastType, duration?: number): number;
    openTab(tabId: string, props?: Record<string, unknown>): void;
    openFileByPath(
        fileOrPath: string | { id?: string; name?: string; path?: string },
    ): Promise<void>;
    refreshFiles(): Promise<void>;
    getCurrentFolderPath(): string;
    registerNavTab(tab: PluginNavTab): void;
    registerFileToolbarAction(action: PluginToolbarAction): void;
    registerFileViewerAction(action: PluginViewerAction): void;
}

interface SupernoteUiPlugin {
    register(host: PluginHostContext): void | Promise<void>;
}
