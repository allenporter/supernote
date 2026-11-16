/**
 * Composable lifecycle test helper that captures `onMounted`, `onUnmounted`,
 * and `watch` disposers registered during composable creation.
 *
 * @template T
 * @param {() => T} factory
 * @returns {Promise<{ result: T, unmount: () => void }>}
 */
export async function mountComposable(factory) {
    /** @type {{ mounted: Array<() => unknown>, unmounted: Array<() => void>, stops: Array<() => void> }} */
    const scope = { mounted: [], unmounted: [], stops: [] };
    const prev = globalThis.__vueMountScope;
    let unmounted = false;

    function unmount() {
        if (unmounted) return;
        unmounted = true;
        for (const stop of scope.stops) {
            stop();
        }
        for (const hook of scope.unmounted) {
            hook();
        }
    }

    globalThis.__vueMountScope = scope;
    /** @type {T} */
    let result;
    try {
        try {
            result = factory();
        } finally {
            globalThis.__vueMountScope = prev;
        }
        for (const hook of scope.mounted) {
            await hook();
        }
    } catch (err) {
        unmount();
        throw err;
    }

    return { result, unmount };
}
