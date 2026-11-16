import { ref } from 'vue';

/** @type {import('vue').Ref<ToastMessage[]>} */
const toasts = ref([]);
let nextToastId = 1;

/**
 * @param {number} id
 */
export function dismissToast(id) {
    toasts.value = toasts.value.filter((t) => t.id !== id);
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
        setTimeout(() => {
            dismissToast(id);
        }, duration);
    }
    return id;
}

export function useToast() {
    return {
        toasts,
        showToast,
        dismissToast,
    };
}
