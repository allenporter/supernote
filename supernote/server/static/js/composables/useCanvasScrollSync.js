/**
 * Bidirectional canvas/transcript scroll synchronization, IntersectionObserver
 * active-page tracking, lazy-image target-page anchoring, and zoom controls
 * for FileViewer.
 */

import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue';
import { ZOOM_STEPS } from '../components/viewer/noteMeta.js';

/**
 * @typedef {Object} ScrollSyncOptions
 * @property {ScrollBehavior} [behavior]
 * @property {boolean} [keepAnchor]
 */

/**
 * @param {Object} options
 * @param {import('vue').Ref<NotePngPage[]>} options.pages
 * @param {import('vue').Ref<TranscriptPage[]>} options.transcriptPages
 */
export function useCanvasScrollSync({ pages, transcriptPages }) {
    const activePageIndex = ref(0);
    /** @type {import('vue').Ref<HTMLElement | null>} */
    const leftScrollPane = ref(null);
    /** @type {import('vue').Ref<{ scrollToPage: (pageIndex: number, options?: { behavior?: ScrollBehavior }) => void } | null>} */
    const sidePanelRef = ref(null);
    const zoomPercent = ref(100);

    /** @type {IntersectionObserver | null} */
    let pageObserver = null;
    let isProgrammaticScroll = false;
    /** @type {ReturnType<typeof setTimeout> | null} */
    let programmaticScrollTimer = null;
    /** @type {number | null} */
    let pendingTargetPage = null;
    /** @type {ReturnType<typeof setTimeout> | null} */
    let pendingTargetTimer = null;

    const canvasMaxWidthPx = computed(() => {
        return Math.round(540 * (zoomPercent.value / 100));
    });

    const zoomOut = () => {
        const idx = ZOOM_STEPS.indexOf(zoomPercent.value);
        if (idx > 0) zoomPercent.value = ZOOM_STEPS[idx - 1];
    };

    const zoomIn = () => {
        const idx = ZOOM_STEPS.indexOf(zoomPercent.value);
        if (idx !== -1 && idx < ZOOM_STEPS.length - 1) {
            zoomPercent.value = ZOOM_STEPS[idx + 1];
        }
    };

    const resetZoom = () => {
        zoomPercent.value = 100;
    };

    /**
     * @param {number} pageIndex
     * @param {{ behavior?: ScrollBehavior }} [options={}]
     */
    const scrollTranscriptToPage = (pageIndex, options = {}) => {
        sidePanelRef.value?.scrollToPage(pageIndex, options);
    };

    const clearPendingTargetPage = () => {
        pendingTargetPage = null;
        if (pendingTargetTimer) {
            clearTimeout(pendingTargetTimer);
            pendingTargetTimer = null;
        }
    };

    /**
     * @param {number} pageIndex
     */
    const armPendingTargetPage = (pageIndex) => {
        clearPendingTargetPage();
        pendingTargetPage = pageIndex;
        pendingTargetTimer = setTimeout(() => {
            pendingTargetPage = null;
            pendingTargetTimer = null;
        }, 2000);
    };

    const armProgrammaticScrollRelease = () => {
        if (programmaticScrollTimer) clearTimeout(programmaticScrollTimer);
        programmaticScrollTimer = setTimeout(() => {
            isProgrammaticScroll = false;
            programmaticScrollTimer = null;
        }, 180);
    };

    /**
     * @param {number} pageIndex
     * @param {ScrollSyncOptions} [options={}]
     */
    const scrollToCanvasPage = (pageIndex, options = {}) => {
        const behavior = options.behavior || 'smooth';
        if (!options.keepAnchor) {
            armPendingTargetPage(pageIndex);
        }
        activePageIndex.value = pageIndex;
        const pane = leftScrollPane.value;
        if (!pane) return;
        const pageEl = pane.querySelector(`[data-page-index="${pageIndex}"]`);
        if (!pageEl) return;

        isProgrammaticScroll = true;
        armProgrammaticScrollRelease();

        if (pane.scrollHeight > pane.clientHeight) {
            const paneRect = pane.getBoundingClientRect();
            const elRect = pageEl.getBoundingClientRect();
            const targetTop =
                pageIndex === 0 ? 0 : pane.scrollTop + (elRect.top - paneRect.top) - 16;
            pane.scrollTo({ top: Math.max(0, targetTop), behavior });
        } else if (pane.scrollTop !== 0) {
            pane.scrollTo({ top: 0, behavior: 'auto' });
        }
    };

    const prevPage = () => {
        if (activePageIndex.value > 0) {
            const target = activePageIndex.value - 1;
            scrollToCanvasPage(target);
            scrollTranscriptToPage(target);
        }
    };

    const nextPage = () => {
        if (activePageIndex.value < pages.value.length - 1) {
            const target = activePageIndex.value + 1;
            scrollToCanvasPage(target);
            scrollTranscriptToPage(target);
        }
    };

    /**
     * @param {number} rawPageIndex
     * @param {{ smooth?: boolean }} [options={}]
     */
    const jumpToTargetPage = async (rawPageIndex, { smooth = false } = {}) => {
        if (typeof rawPageIndex !== 'number' || Number.isNaN(rawPageIndex) || rawPageIndex < 0) {
            return;
        }
        const maxPageIdx =
            pages.value.length > 0
                ? pages.value.length - 1
                : transcriptPages.value.length > 0
                  ? transcriptPages.value.length - 1
                  : rawPageIndex;
        const targetIdx = Math.max(0, Math.min(rawPageIndex, maxPageIdx));
        /** @type {ScrollBehavior} */
        const behavior = smooth ? 'smooth' : 'auto';

        activePageIndex.value = targetIdx;
        await nextTick();
        if (pages.value.length > 0) {
            scrollToCanvasPage(targetIdx, { behavior });
        }
        scrollTranscriptToPage(targetIdx, { behavior });
    };

    const handlePageImageLoad = () => {
        if (pendingTargetPage !== null) {
            scrollToCanvasPage(pendingTargetPage, { behavior: 'auto', keepAnchor: true });
            scrollTranscriptToPage(pendingTargetPage, { behavior: 'auto' });
        }
    };

    const updateActivePageFromScroll = () => {
        if (isProgrammaticScroll || pendingTargetPage !== null) {
            if (isProgrammaticScroll) armProgrammaticScrollRelease();
            return;
        }
        if (!leftScrollPane.value) return;
        const pane = leftScrollPane.value;
        const paneRect = pane.getBoundingClientRect();
        const cards = pane.querySelectorAll('[data-page-index]');
        if (!cards.length) return;

        let bestIdx = activePageIndex.value;
        let bestScore = -Infinity;

        cards.forEach((card) => {
            const idx = Number(card.getAttribute('data-page-index'));
            if (Number.isNaN(idx)) return;
            const rect = card.getBoundingClientRect();
            const visibleTop = Math.max(rect.top, paneRect.top);
            const visibleBottom = Math.min(rect.bottom, paneRect.bottom);
            const visibleHeight = Math.max(0, visibleBottom - visibleTop);
            if (visibleHeight > 0) {
                const topOffset = Math.max(0, visibleTop - paneRect.top);
                const score = visibleHeight - topOffset * 0.25;
                if (score > bestScore) {
                    bestScore = score;
                    bestIdx = idx;
                }
            }
        });

        if (bestScore > -Infinity && bestIdx !== activePageIndex.value) {
            activePageIndex.value = bestIdx;
            scrollTranscriptToPage(bestIdx);
        }
    };

    const teardownPageObserver = () => {
        if (pageObserver) {
            pageObserver.disconnect();
            pageObserver = null;
        }
    };

    const setupPageObserver = async () => {
        teardownPageObserver();
        await nextTick();
        if (!leftScrollPane.value || typeof IntersectionObserver === 'undefined') return;
        const cards = leftScrollPane.value.querySelectorAll('[data-page-index]');
        if (!cards.length) return;

        const observer = new IntersectionObserver(
            (entries) => {
                if (isProgrammaticScroll || pendingTargetPage !== null) return;
                let updated = false;
                if (leftScrollPane.value) {
                    const paneRect = leftScrollPane.value.getBoundingClientRect();
                    if (paneRect.height > 0) {
                        updateActivePageFromScroll();
                        updated = true;
                    }
                }
                if (!updated) {
                    /** @type {IntersectionObserverEntry | null} */
                    let bestEntry = null;
                    for (const entry of entries) {
                        if (entry.isIntersecting) {
                            if (
                                !bestEntry ||
                                entry.intersectionRatio > bestEntry.intersectionRatio
                            ) {
                                bestEntry = entry;
                            }
                        }
                    }
                    if (bestEntry) {
                        const idx = Number(bestEntry.target.getAttribute('data-page-index'));
                        if (!Number.isNaN(idx) && idx !== activePageIndex.value) {
                            activePageIndex.value = idx;
                            scrollTranscriptToPage(idx);
                        }
                    }
                }
            },
            {
                root: leftScrollPane.value,
                threshold: [0, 0.15, 0.3, 0.5, 0.75, 1.0],
            },
        );
        pageObserver = observer;

        for (const card of cards) {
            observer.observe(card);
        }
    };

    onMounted(() => {
        window.addEventListener('wheel', clearPendingTargetPage, { passive: true });
        window.addEventListener('touchstart', clearPendingTargetPage, { passive: true });
        window.addEventListener('pointerdown', clearPendingTargetPage, { passive: true });
    });

    onUnmounted(() => {
        window.removeEventListener('wheel', clearPendingTargetPage);
        window.removeEventListener('touchstart', clearPendingTargetPage);
        window.removeEventListener('pointerdown', clearPendingTargetPage);
        teardownPageObserver();
        clearPendingTargetPage();
        if (programmaticScrollTimer) {
            clearTimeout(programmaticScrollTimer);
            programmaticScrollTimer = null;
        }
    });

    return {
        activePageIndex,
        leftScrollPane,
        sidePanelRef,
        zoomPercent,
        canvasMaxWidthPx,
        zoomIn,
        zoomOut,
        resetZoom,
        prevPage,
        nextPage,
        jumpToTargetPage,
        scrollToCanvasPage,
        scrollTranscriptToPage,
        handlePageImageLoad,
        updateActivePageFromScroll,
        setupPageObserver,
        teardownPageObserver,
        clearPendingTargetPage,
    };
}
