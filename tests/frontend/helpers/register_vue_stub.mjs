/**
 * Minimal Node ESM loader hook & browser global shim so pure frontend modules
 * importing from importmap specifiers ('vue', 'marked', 'dompurify') or reading
 * localStorage can execute directly under `node --test` without npm packages or a bundler.
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

const MARKED_STUB_SOURCE = `
export class Marked {
    constructor(ext = {}) { this.ext = ext; }
    parse(src) {
        return String(src)
            .split('\\n\\n')
            .map((block) => block.startsWith('## ') ? '<h2>' + block.slice(3) + '</h2>' : '<p>' + block + '</p>')
            .join('\\n');
    }
}
`;

const DOMPURIFY_STUB_SOURCE = `
export default {
    lastConfig: null,
    sanitize(dirty, cfg) {
        this.lastConfig = cfg;
        return String(dirty).replace(/<script[\\s\\S]*?<\\/script>/gi, '');
    }
};
`;

const STUB_URLS = {
    vue: `data:text/javascript;charset=utf-8,${encodeURIComponent(VUE_STUB_SOURCE)}`,
    marked: `data:text/javascript;charset=utf-8,${encodeURIComponent(MARKED_STUB_SOURCE)}`,
    dompurify: `data:text/javascript;charset=utf-8,${encodeURIComponent(DOMPURIFY_STUB_SOURCE)}`,
};

if (typeof nodeModule.registerHooks === 'function') {
    nodeModule.registerHooks({
        resolve(specifier, context, nextResolve) {
            if (Object.hasOwn(STUB_URLS, specifier)) {
                return { url: STUB_URLS[specifier], shortCircuit: true };
            }
            return nextResolve(specifier, context);
        },
    });
} else {
    const loaderCode = `
    const STUBS = ${JSON.stringify(STUB_URLS)};
    export async function resolve(specifier, context, nextResolve) {
        if (Object.prototype.hasOwnProperty.call(STUBS, specifier)) {
            return { url: STUBS[specifier], shortCircuit: true };
        }
        return nextResolve(specifier, context);
    }
    `;
    nodeModule.register(`data:text/javascript;charset=utf-8,${encodeURIComponent(loaderCode)}`);
}
