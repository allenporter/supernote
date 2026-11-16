/**
 * Minimal Node ESM loader hook & browser global shim so frontend ES modules
 * importing from importmap specifiers ('vue', 'marked', 'dompurify') or reading
 * localStorage execute directly under `node --test` without npm packages or a bundler.
 *
 * Includes lightweight dependency-tracking `ref` / `computed` / `watch` reactivity
 * and `onMounted` / `onUnmounted` lifecycle capture (driven via `vue_test_scope.mjs`).
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
let activeTracker = null;

function withTracker(tracker, fn) {
    const prev = activeTracker;
    activeTracker = tracker;
    try {
        return fn();
    } finally {
        activeTracker = prev;
    }
}

export function ref(initialValue) {
    let current = initialValue;
    const subs = new Set();
    return {
        __v_isRef: true,
        get value() {
            if (activeTracker) {
                subs.add(activeTracker);
                activeTracker.deps.add(subs);
            }
            return current;
        },
        set value(next) {
            if (!Object.is(current, next)) {
                current = next;
                for (const sub of [...subs]) {
                    sub.notify();
                }
            }
        },
    };
}

export function computed(getter) {
    const subs = new Set();
    const tracker = {
        deps: new Set(),
        notify() {
            for (const sub of [...subs]) {
                sub.notify();
            }
        },
    };
    return {
        __v_isRef: true,
        get value() {
            for (const dep of tracker.deps) {
                dep.delete(tracker);
            }
            tracker.deps.clear();
            const val = withTracker(tracker, getter);
            if (activeTracker) {
                subs.add(activeTracker);
                activeTracker.deps.add(subs);
            }
            return val;
        },
    };
}

function readWatchSource(source) {
    if (Array.isArray(source)) {
        return source.map((item) => (typeof item === 'function' ? item() : item?.value));
    }
    if (typeof source === 'function') {
        return source();
    }
    return source?.value;
}

function valuesEqual(a, b) {
    if (Array.isArray(a) && Array.isArray(b)) {
        return a.length === b.length && a.every((item, idx) => Object.is(item, b[idx]));
    }
    return Object.is(a, b);
}

export function watch(source, cb, options = {}) {
    let stopped = false;
    let prevValue;
    const tracker = {
        deps: new Set(),
        notify() {
            if (stopped) return;
            const nextValue = evaluate();
            if (!valuesEqual(nextValue, prevValue)) {
                const oldValue = prevValue;
                prevValue = Array.isArray(nextValue) ? [...nextValue] : nextValue;
                void withTracker(null, () => cb(nextValue, oldValue));
            }
        },
    };

    function cleanupDeps() {
        for (const dep of tracker.deps) {
            dep.delete(tracker);
        }
        tracker.deps.clear();
    }

    function evaluate() {
        cleanupDeps();
        return withTracker(tracker, () => readWatchSource(source));
    }

    const initialValue = evaluate();
    prevValue = Array.isArray(initialValue) ? [...initialValue] : initialValue;

    const stop = () => {
        if (stopped) return;
        stopped = true;
        cleanupDeps();
    };
    if (globalThis.__vueMountScope) {
        globalThis.__vueMountScope.stops.push(stop);
    }

    if (options?.immediate) {
        void withTracker(null, () => cb(initialValue, undefined));
    }
    return stop;
}

export function nextTick(fn) {
    return Promise.resolve().then(() => (fn ? fn() : undefined));
}

export function onMounted(hook) {
    if (globalThis.__vueMountScope) {
        globalThis.__vueMountScope.mounted.push(hook);
    }
}

export function onUnmounted(hook) {
    if (globalThis.__vueMountScope) {
        globalThis.__vueMountScope.unmounted.push(hook);
    }
}

export function createApp() {
    return {
        component() {
            return this;
        },
        mount() {},
    };
}
`;

const MARKED_STUB_SOURCE = `
function renderInline(text) {
    return String(text)
        .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
        .replace(/\\[([^\\]]+)\\]\\(([^)]*)\\)/g, (_m, label, href) =>
            href ? '<a href="' + href + '">' + label + '</a>' : '<a>' + label + '</a>',
        );
}

export class Marked {
    constructor(ext = {}) {
        this.ext = ext;
    }

    parse(src) {
        const renderer = this.ext?.renderer || {};
        const parserCtx = {
            parser: {
                parse(tokens) {
                    return tokens.map((t) => t.html).join('');
                },
                parseInline(tokens) {
                    return tokens.map((t) => t.html).join('');
                },
            },
        };

        return String(src)
            .split('\\n\\n')
            .map((block) => {
                if (block.startsWith('## ')) {
                    return '<h2>' + renderInline(block.slice(3)) + '</h2>';
                }
                const lines = block.split('\\n');
                if (lines.every((line) => line.startsWith('- '))) {
                    const itemsHtml = lines
                        .map((line) => {
                            const taskMatch = /^- \\[( |x|X)\\] (.*)$/.exec(line);
                            if (taskMatch) {
                                const checked = taskMatch[1].toLowerCase() === 'x';
                                const boxHtml = renderer.checkbox
                                    ? renderer.checkbox.call(parserCtx, { checked })
                                    : '<input type="checkbox"' + (checked ? ' checked' : '') + '> ';
                                const bodyHtml = renderInline(taskMatch[2]);
                                const itemToken = {
                                    task: true,
                                    checked,
                                    tokens: [{ html: boxHtml + bodyHtml }],
                                };
                                return renderer.listitem
                                    ? renderer.listitem.call(parserCtx, itemToken)
                                    : '<li>' + boxHtml + bodyHtml + '</li>\\n';
                            }
                            const bodyHtml = renderInline(line.slice(2));
                            const itemToken = { task: false, tokens: [{ html: bodyHtml }] };
                            return renderer.listitem
                                ? renderer.listitem.call(parserCtx, itemToken)
                                : '<li>' + bodyHtml + '</li>\\n';
                        })
                        .join('');
                    return '<ul>\\n' + itemsHtml + '</ul>';
                }
                return '<p>' + renderInline(block) + '</p>';
            })
            .join('\\n');
    }
}
`;

const DOMPURIFY_STUB_SOURCE = `
export default {
    lastConfig: null,
    sanitize(dirty, cfg) {
        this.lastConfig = cfg;
        let out = String(dirty).replace(/<script[\\s\\S]*?<\\/script>/gi, '');
        const forbidden = Array.isArray(cfg?.FORBID_TAGS) ? cfg.FORBID_TAGS : [];
        for (const tag of forbidden) {
            const pairRe = new RegExp('<' + tag + '\\\\b[^>]*>[\\\\s\\\\S]*?<\\\\/' + tag + '>', 'gi');
            const singleRe = new RegExp('<' + tag + '\\\\b[^>]*\\\\/?>', 'gi');
            out = out.replace(pairRe, '').replace(singleRe, '');
        }
        return out;
    },
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
