import assert from 'node:assert/strict';
import test from 'node:test';
import { ref } from 'vue';

import { useCanvasScrollSync } from '../../supernote/server/static/js/composables/useCanvasScrollSync.js';
import { mountComposable } from './helpers/vue_test_scope.mjs';

test('useCanvasScrollSync.js: steps zoom levels, clamps page jumps, tracks scroll visibility, and cleans up listeners', async (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const origWindow = globalThis.window;
    /** @type {Set<string>} */
    const attachedEvents = new Set();

    try {
        globalThis.window = /** @type {any} */ ({
            addEventListener(type) {
                attachedEvents.add(type);
            },
            removeEventListener(type) {
                attachedEvents.delete(type);
            },
        });

        const pages = ref([
            { pageNo: 1, url: '/p1.png' },
            { pageNo: 2, url: '/p2.png' },
            { pageNo: 3, url: '/p3.png' },
        ]);
        const transcriptPages = ref(/** @type {any[]} */ ([]));

        const { result, unmount } = await mountComposable(() =>
            useCanvasScrollSync({ pages, transcriptPages }),
        );
        assert.deepEqual([...attachedEvents].sort(), ['pointerdown', 'touchstart', 'wheel']);

        // Zoom controls step through [75, 100, 125, 150] and clamp at bounds
        assert.equal(result.zoomPercent.value, 100);
        assert.equal(result.canvasMaxWidthPx.value, 540);
        result.zoomOut();
        assert.equal(result.zoomPercent.value, 75);
        result.zoomOut();
        assert.equal(result.zoomPercent.value, 75);
        result.zoomIn();
        result.zoomIn();
        result.zoomIn();
        result.zoomIn();
        assert.equal(result.zoomPercent.value, 150);
        result.resetZoom();
        assert.equal(result.zoomPercent.value, 100);

        /** @type {Array<{ page: number, options: any }>} */
        const sideScrolls = [];
        /** @type {Array<{ top: number, behavior: string }>} */
        const canvasScrolls = [];
        const cardRects = [
            { top: -350, bottom: 50 },
            { top: 60, bottom: 460 },
            { top: 470, bottom: 870 },
        ];
        const cardEls = cardRects.map((rect, idx) => ({
            getAttribute: (name) => (name === 'data-page-index' ? String(idx) : null),
            getBoundingClientRect: () => rect,
        }));

        result.sidePanelRef.value = {
            scrollToPage(page, options) {
                sideScrolls.push({ page, options });
            },
        };
        result.leftScrollPane.value = /** @type {any} */ ({
            scrollHeight: 1200,
            clientHeight: 500,
            scrollTop: 350,
            getBoundingClientRect: () => ({ top: 0, bottom: 500, height: 500 }),
            querySelector: (sel) => {
                const m = /data-page-index="(\d+)"/.exec(sel);
                return m ? cardEls[Number(m[1])] : null;
            },
            querySelectorAll: () => cardEls,
            scrollTo(opts) {
                canvasScrolls.push(opts);
            },
        });

        // jumpToTargetPage clamps out-of-range index 99 -> 2 and arms programmatic/pending guards
        await result.jumpToTargetPage(99, { smooth: false });
        assert.equal(result.activePageIndex.value, 2);
        assert.equal(canvasScrolls.length, 1);

        // Release programmatic + pending target timers so manual scroll spy updates activePageIndex
        t.mock.timers.tick(2000);
        result.updateActivePageFromScroll();
        assert.equal(result.activePageIndex.value, 1);
        assert.equal(sideScrolls[sideScrolls.length - 1]?.page, 1);

        result.prevPage();
        assert.equal(result.activePageIndex.value, 0);
        result.nextPage();
        assert.equal(result.activePageIndex.value, 1);

        unmount();
        assert.deepEqual([...attachedEvents], []);
    } finally {
        globalThis.window = origWindow;
    }
});
