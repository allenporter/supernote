/**
 * Server feature availability composable.
 *
 * Tracks which built-in server components are running (via
 * `GET /api/extended/system/features`) so the UI can hide features whose
 * backing component is disabled. State is shared module-wide. Until loaded, or
 * when the server cannot report its components, every feature is treated as
 * available.
 */

import { ref } from 'vue';
import { fetchServerFeatures } from '../api/client.js';

/**
 * Host tabs backed by an optional server component.
 * @type {Readonly<Record<string, string>>}
 */
export const TAB_COMPONENTS = Object.freeze({
    digests: 'summary',
    tasks: 'schedule',
    wiki: 'wiki',
});

/** @type {import('vue').Ref<string[] | null>} */
const runningComponents = ref(null);

/**
 * @param {string} domain
 * @returns {boolean}
 */
export function isComponentRunning(domain) {
    const running = runningComponents.value;
    return running === null || running.includes(domain);
}

/**
 * @param {string} tab
 * @returns {boolean}
 */
export function isTabAvailable(tab) {
    const domain = TAB_COMPONENTS[tab];
    return domain === undefined || isComponentRunning(domain);
}

export async function loadServerFeatures() {
    runningComponents.value = await fetchServerFeatures();
}

export function resetServerFeatures() {
    runningComponents.value = null;
}

export function useServerFeatures() {
    return {
        runningComponents,
        isComponentRunning,
        isTabAvailable,
        loadServerFeatures,
        resetServerFeatures,
    };
}
