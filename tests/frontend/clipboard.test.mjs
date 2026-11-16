import assert from 'node:assert/strict';
import test from 'node:test';

import { copyTextToClipboard } from '../../supernote/server/static/js/utils/clipboard.js';

test('clipboard.js: rejects empty input, writes via navigator.clipboard, and falls back to execCommand on LAN HTTP', async () => {
    const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
    const originalDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');

    try {
        assert.equal(await copyTextToClipboard(''), false);
        assert.equal(await copyTextToClipboard(null), false);

        let writtenText = null;
        Object.defineProperty(globalThis, 'navigator', {
            value: {
                clipboard: {
                    async writeText(val) {
                        writtenText = val;
                    },
                },
            },
            configurable: true,
        });
        assert.equal(await copyTextToClipboard('Page 1 transcript'), true);
        assert.equal(writtenText, 'Page 1 transcript');

        /** @type {any[]} */
        const appended = [];
        let copiedViaExec = false;
        Object.defineProperty(globalThis, 'navigator', {
            value: {
                clipboard: {
                    async writeText() {
                        throw new Error('Insecure context');
                    },
                },
            },
            configurable: true,
        });
        Object.defineProperty(globalThis, 'document', {
            value: {
                body: {
                    appendChild(el) {
                        appended.push(el);
                    },
                    removeChild(el) {
                        const idx = appended.indexOf(el);
                        if (idx !== -1) appended.splice(idx, 1);
                    },
                },
                createElement() {
                    return {
                        value: '',
                        style: {},
                        setAttribute() {},
                        focus() {},
                        select() {},
                        setSelectionRange() {},
                    };
                },
                execCommand(cmd) {
                    if (cmd === 'copy') {
                        copiedViaExec = true;
                        return true;
                    }
                    return false;
                },
            },
            configurable: true,
        });

        assert.equal(await copyTextToClipboard('LAN fallback transcript'), true);
        assert.equal(copiedViaExec, true);
        assert.equal(appended.length, 0);
    } finally {
        if (originalNavigator) {
            Object.defineProperty(globalThis, 'navigator', originalNavigator);
        } else {
            delete globalThis.navigator;
        }
        if (originalDocument) {
            Object.defineProperty(globalThis, 'document', originalDocument);
        } else {
            delete globalThis.document;
        }
    }
});
