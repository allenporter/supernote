import assert from 'node:assert/strict';
import test from 'node:test';
import { ref } from 'vue';

import {
    dispatchEscapeKey,
    pushEscapeHandler,
    resetEscapeStack,
    useModalEscape,
} from '../../supernote/server/static/js/composables/useModalEscape.js';
import { mountComposable } from './helpers/vue_test_scope.mjs';

test('useModalEscape.js: LIFO stack, preventDefault, reactive isActive toggle, and unmount cleanup', async () => {
    const origWindow = globalThis.window;
    let addedListeners = 0;
    let removedListeners = 0;
    let prevented = 0;
    /** @type {string[]} */
    const closed = [];

    try {
        globalThis.window = /** @type {any} */ ({
            addEventListener(type) {
                if (type === 'keydown') addedListeners++;
            },
            removeEventListener(type) {
                if (type === 'keydown') removedListeners++;
            },
        });

        const makeEsc = () => ({
            key: 'Escape',
            defaultPrevented: false,
            preventDefault() {
                prevented++;
            },
        });

        const isFolderOpen = ref(false);
        const mounted = await mountComposable(() => {
            useModalEscape(() => closed.push('folder-modal'), isFolderOpen);
        });
        assert.equal(addedListeners, 0);

        isFolderOpen.value = true;
        assert.equal(addedListeners, 1);

        const popSearch = pushEscapeHandler(() => closed.push('search-modal'));
        assert.equal(
            dispatchEscapeKey({
                key: 'Enter',
                defaultPrevented: false,
                preventDefault() {
                    prevented++;
                },
            }),
            false,
        );
        assert.equal(
            dispatchEscapeKey({
                key: 'Escape',
                defaultPrevented: true,
                preventDefault() {
                    prevented++;
                },
            }),
            false,
        );
        assert.equal(prevented, 0);

        assert.equal(dispatchEscapeKey(makeEsc()), true);
        assert.deepEqual(closed, ['search-modal']);
        assert.equal(prevented, 1);

        popSearch();
        popSearch();
        assert.equal(removedListeners, 0);

        assert.equal(dispatchEscapeKey(makeEsc()), true);
        assert.deepEqual(closed, ['search-modal', 'folder-modal']);
        assert.equal(prevented, 2);

        mounted.unmount();
        assert.equal(removedListeners, 1);
        assert.equal(dispatchEscapeKey(makeEsc()), false);

        // Verify mountComposable cleans up registered watchers if setup throws midway
        const brokenOpen = ref(true);
        await assert.rejects(() =>
            mountComposable(() => {
                useModalEscape(() => closed.push('leaked'), brokenOpen);
                throw new Error('setup failed');
            }),
        );
        assert.equal(dispatchEscapeKey(makeEsc()), false);
    } finally {
        resetEscapeStack();
        globalThis.window = origWindow;
    }
});
