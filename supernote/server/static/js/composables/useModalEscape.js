import { onMounted, onUnmounted, watch } from 'vue';

/** @type {Array<() => void>} */
const escapeStack = [];
let windowListenerAttached = false;

/**
 * Dispatch an `Escape` key event to the most recently registered active modal/drawer handler.
 * @param {Pick<KeyboardEvent, 'key' | 'defaultPrevented' | 'preventDefault'>} event
 * @returns {boolean}
 */
export function dispatchEscapeKey(event) {
    if (event.key !== 'Escape' || event.defaultPrevented || escapeStack.length === 0) {
        return false;
    }
    const topHandler = escapeStack[escapeStack.length - 1];
    event.preventDefault();
    topHandler();
    return true;
}

/**
 * @param {KeyboardEvent} event
 */
function handleWindowKeydown(event) {
    dispatchEscapeKey(event);
}

function syncWindowListener() {
    if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') {
        return;
    }
    if (escapeStack.length > 0 && !windowListenerAttached) {
        window.addEventListener('keydown', handleWindowKeydown);
        windowListenerAttached = true;
    } else if (escapeStack.length === 0 && windowListenerAttached) {
        window.removeEventListener('keydown', handleWindowKeydown);
        windowListenerAttached = false;
    }
}

/**
 * Push an `Escape` dismissal callback onto the LIFO stack and return an unregister function.
 * @param {() => void} handler
 * @returns {() => void}
 */
export function pushEscapeHandler(handler) {
    let active = true;
    escapeStack.push(handler);
    syncWindowListener();
    return () => {
        if (!active) return;
        active = false;
        const idx = escapeStack.lastIndexOf(handler);
        if (idx !== -1) {
            escapeStack.splice(idx, 1);
        }
        syncWindowListener();
    };
}

export function resetEscapeStack() {
    escapeStack.length = 0;
    syncWindowListener();
}

/**
 * Register a LIFO `Escape` handler for a mounted modal component or reactive open-state ref/getter.
 * @param {() => void} onEscape
 * @param {import('vue').Ref<boolean> | import('vue').ComputedRef<boolean> | (() => boolean)} [isActive]
 */
export function useModalEscape(onEscape, isActive) {
    /** @type {(() => void) | null} */
    let unregister = null;

    function deactivate() {
        if (unregister) {
            unregister();
            unregister = null;
        }
    }

    if (isActive !== undefined) {
        watch(
            isActive,
            (open) => {
                deactivate();
                if (open) {
                    unregister = pushEscapeHandler(onEscape);
                }
            },
            { immediate: true },
        );
    } else {
        onMounted(() => {
            unregister = pushEscapeHandler(onEscape);
        });
    }

    onUnmounted(deactivate);
}
