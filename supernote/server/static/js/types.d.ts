/**
 * Ambient TypeScript declarations for the no-build Supernote Cloud Web UI:
 * - Browser CDN globals (SparkMD5, js-sha256, Socket.IO, Vue 3 ESM importmap)
 * - Backend API DTOs and frontend domain models
 * - Host UI extension contract (PluginHostContext / SupernoteUiPlugin)
 */

interface SocketClient {
    connected: boolean;
    on(event: string, listener: (data: any) => void): this;
    emit(event: string, ...args: any[]): this;
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
    'supernote:file-sync': CustomEvent<any>;
    'supernote:task-sync': CustomEvent<any>;
    'supernote:digest-sync': CustomEvent<any>;
}

declare module 'vue' {
    export interface Ref<T = any> {
        value: T;
    }

    export interface ComputedRef<T = any> {
        readonly value: T;
    }

    export interface WatchOptions {
        immediate?: boolean;
        deep?: boolean;
        flush?: 'pre' | 'post' | 'sync';
        once?: boolean;
    }

    export function ref(value: null): Ref<any>;
    export function ref(value: never[]): Ref<any[]>;
    export function ref<T>(value: T): Ref<T>;
    export function ref<T = any>(): Ref<T | undefined>;
    export function computed<T>(getter: () => T): ComputedRef<T>;
    export function watch<T>(
        source: Ref<T> | ComputedRef<T> | (() => T),
        callback: (newValue: T, oldValue: T) => void | Promise<void>,
        options?: WatchOptions
    ): () => void;
    export function watch(
        sources: ReadonlyArray<any>,
        callback: (newValues: any[], oldValues: any[]) => void | Promise<void>,
        options?: WatchOptions
    ): () => void;
    export function nextTick(fn?: () => void): Promise<void>;
    export function onMounted(hook: () => void | Promise<void>): void;
    export function onUnmounted(hook: () => void): void;

    export interface AppInstance {
        component(name: string, definition: Record<string, any>): AppInstance;
        mount(rootContainer: string | Element): any;
    }

    export function createApp(rootComponent: Record<string, any>): AppInstance;
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

interface BreadcrumbItem {
    id: string;
    name: string;
}

type TaskImportance = 'high' | 'medium' | 'low';
type TaskStatus = 'needsAction' | 'completed';

interface ScheduleTaskGroup {
    id: string;
    title: string;
}

interface RawScheduleTaskGroup {
    taskListId: string | number;
    title?: string;
}

interface ScheduleTask {
    id: string;
    taskListId: string | null;
    title: string;
    detail: string;
    status: TaskStatus | string;
    importance: TaskImportance;
    dueTime: number;
    completedTime: number;
    isReminderOn: boolean;
    links: unknown;
    sort: number | null;
    sortCompleted: number | null;
    planerSort: number | null;
    allSort: number | null;
    createTime: number;
    updateTime: number;
}

interface ScheduleTaskInput {
    id?: string | number;
    taskId?: string | number;
    taskListId?: string | number | null;
    title?: string;
    detail?: string;
    importance?: string;
    status?: string;
    dueTime?: number;
    completedTime?: number;
    lastModified?: number;
    isReminderOn?: boolean;
}

interface TranscriptPage {
    pageIndex: number;
    pageId: string;
    text: string;
    date: string | null;
    hasTranscript?: boolean;
}

interface NotePageMeta {
    pageIndex: number;
    pageId?: string;
    date?: string | null;
    style?: string | null;
    hasFiveStar?: boolean;
    keywords?: string[];
}

interface NoteLink {
    pageIndex: number;
    linkType?: 'page' | 'file' | 'web' | string;
    target?: string | null;
    targetFileId?: string | number | null;
    targetPageIndex?: number | null;
}

interface NoteMetadata {
    equipment?: string | null;
    pages?: NotePageMeta[];
    links?: NoteLink[];
}

interface AiStatus {
    success: boolean;
    hasApiKey: boolean;
    ocrEnabled: boolean;
    ocrModel: string | null;
    summaryEnabled: boolean;
    summaryModel: string | null;
    vectorSearchEnabled: boolean;
    embeddingModel: string | null;
    model: string | null;
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
    component: Record<string, any>;
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
    fetchJson<T = any>(
        path: string,
        options?: { method?: string; body?: unknown; headers?: Record<string, string> }
    ): Promise<T>;
    showToast(message: string, type?: ToastType, duration?: number): number;
    openTab(tabId: string, props?: Record<string, unknown>): void;
    openFileByPath(fileOrPath: string | { id?: string; name?: string; path?: string }): Promise<void>;
    refreshFiles(): Promise<void>;
    getCurrentFolderPath(): string;
    registerNavTab(tab: PluginNavTab): void;
    registerFileToolbarAction(action: PluginToolbarAction): void;
    registerFileViewerAction(action: PluginViewerAction): void;
}

interface SupernoteUiPlugin {
    register(host: PluginHostContext): void | Promise<void>;
}
