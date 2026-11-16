import { ref } from 'vue';

/** @type {import('vue').Ref<ToastMessage[]>} */
const toasts = ref([]);
/** @type {Map<number, ReturnType<typeof setTimeout>>} */
const toastTimers = new Map();
let nextToastId = 1;

/**
 * @param {number} id
 */
export function dismissToast(id) {
    const timer = toastTimers.get(id);
    if (timer !== undefined) {
        clearTimeout(timer);
        toastTimers.delete(id);
    }
    toasts.value = toasts.value.filter((t) => t.id !== id);
}

export function clearToasts() {
    for (const timer of toastTimers.values()) {
        clearTimeout(timer);
    }
    toastTimers.clear();
    toasts.value = [];
}

/**
 * @param {string} message
 * @param {ToastType} [type='error']
 * @param {number} [duration=4000]
 * @returns {number}
 */
export function showToast(message, type = 'error', duration = 4000) {
    const id = nextToastId++;
    toasts.value.push({
        id,
        message: String(message || ''),
        type,
    });
    if (duration > 0) {
        const timer = setTimeout(() => {
            toastTimers.delete(id);
            dismissToast(id);
        }, duration);
        toastTimers.set(id, timer);
    }
    return id;
}

export function useToast() {
    return {
        toasts,
        showToast,
        dismissToast,
        clearToasts,
    };
}
