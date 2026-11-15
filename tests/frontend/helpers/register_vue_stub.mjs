/**
 * Minimal Node ESM loader hook & browser global shim so pure frontend modules
 * importing from 'vue' or reading localStorage can execute directly under `node --test`
 * without npm packages or a bundler.
 */

import * as nodeModule from 'node:module';

const storage = new Map();
Object.defineProperty(globalThis, 'localStorage', {
    value: {
        getItem: (key) => (storage.has(key) ? storage.get(key) : null),
        setItem: (key, val) => storage.set(key, String(val)),
        removeItem: (key) => storage.delete(key),
        clear: () => storage.clear(),
    },
    configurable: true,
    writable: true,
});

const VUE_STUB_SOURCE = `
export function ref(val) { return { value: val }; }
export function computed(fn) { return { get value() { return fn(); } }; }
export function watch() { return () => {}; }
export function nextTick(fn) { return Promise.resolve().then(() => fn && fn()); }
export function onMounted() {}
export function onUnmounted() {}
export function createApp() { return { component() { return this; }, mount() {} }; }
`;

const VUE_DATA_URL = `data:text/javascript;charset=utf-8,${encodeURIComponent(VUE_STUB_SOURCE)}`;

if (typeof nodeModule.registerHooks === 'function') {
    nodeModule.registerHooks({
        resolve(specifier, context, nextResolve) {
            if (specifier === 'vue') {
                return { url: VUE_DATA_URL, shortCircuit: true };
            }
            return nextResolve(specifier, context);
        },
    });
} else {
    const loaderCode = `
    const VUE_URL = ${JSON.stringify(VUE_DATA_URL)};
    export async function resolve(specifier, context, nextResolve) {
        if (specifier === 'vue') {
            return { url: VUE_URL, shortCircuit: true };
        }
        return nextResolve(specifier, context);
    }
    `;
    nodeModule.register(`data:text/javascript;charset=utf-8,${encodeURIComponent(loaderCode)}`);
}
