import assert from 'node:assert/strict';
import test from 'node:test';

import { logout, setToken } from '../../supernote/server/static/js/api/http.js';
import { compareRecycleItems } from '../../supernote/server/static/js/components/RecycleBinPanel.js';
import { useRecycleBin } from '../../supernote/server/static/js/composables/useRecycleBin.js';

test('useRecycleBin.js: loads, restores, permanently deletes, empties, and resets cleanly', async () => {
    const origFetch = globalThis.fetch;
    /** @type {Array<Record<string, any>>} */
    let serverItems = [
        {
            fileId: '101',
            isFolder: 'Y',
            fileName: 'Archive',
            size: 0,
            updateTime: '1700000000000',
        },
        {
            fileId: '102',
            isFolder: 'N',
            fileName: 'Notes.note',
            size: 2048,
            updateTime: '1700000200000',
        },
        {
            fileId: '103',
            isFolder: 'N',
            fileName: 'Draft.pdf',
            size: 1024,
            updateTime: '1700000100000',
        },
    ];

    try {
        setToken('rb-tok');
        globalThis.fetch = async (url, init) => {
            const body = JSON.parse(String(init?.body || '{}'));
            if (url === '/api/file/recycle/list/query') {
                return new Response(
                    JSON.stringify({
                        success: true,
                        total: serverItems.length,
                        recycleFileVOList: serverItems,
                    }),
                    { status: 200 },
                );
            }
            if (url === '/api/file/recycle/revert' || url === '/api/file/recycle/delete') {
                const removed = new Set((body.idList || []).map(String));
                serverItems = serverItems.filter((item) => !removed.has(String(item.fileId)));
                return new Response(JSON.stringify({ success: true }), { status: 200 });
            }
            if (url === '/api/file/recycle/clear') {
                serverItems = [];
                return new Response(JSON.stringify({ success: true }), { status: 200 });
            }
            return new Response('{}', { status: 200 });
        };

        const rb = useRecycleBin();
        await rb.loadRecycleBin();
        assert.equal(rb.items.value.length, 3);
        assert.equal(rb.isLoading.value, false);
        assert.equal(rb.error.value, null);

        rb.selectedIds.value = ['102', '103'];
        assert.equal(await rb.restoreItems(['102']), true);
        assert.deepEqual(
            rb.items.value.map((i) => i.id),
            ['101', '103'],
        );
        assert.deepEqual(rb.selectedIds.value, ['103']);

        assert.equal(await rb.deleteItemsPermanently(['103']), true);
        assert.deepEqual(
            rb.items.value.map((i) => i.id),
            ['101'],
        );
        assert.deepEqual(rb.selectedIds.value, []);

        assert.equal(await rb.emptyRecycleBin(), true);
        assert.deepEqual(rb.items.value, []);

        rb.selectedIds.value = ['101'];
        rb.resetRecycleBin();
        assert.deepEqual(rb.items.value, []);
        assert.deepEqual(rb.selectedIds.value, []);
        assert.equal(rb.isLoading.value, false);
        assert.equal(rb.isMutating.value, false);
        assert.equal(rb.error.value, null);
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('useRecycleBin.js: ignores stale load responses after resetRecycleBin', async () => {
    const origFetch = globalThis.fetch;
    /** @type {(() => void) | null} */
    let releaseFetch = null;

    try {
        setToken('rb-race-tok');
        globalThis.fetch = (url) => {
            if (url === '/api/user/logout') {
                return Promise.resolve(new Response('{}', { status: 200 }));
            }
            return new Promise((resolve) => {
                releaseFetch = () =>
                    resolve(
                        new Response(
                            JSON.stringify({
                                success: true,
                                total: 1,
                                recycleFileVOList: [
                                    {
                                        fileId: '999',
                                        isFolder: 'N',
                                        fileName: 'Stale.note',
                                        size: 100,
                                        updateTime: '1700000000000',
                                    },
                                ],
                            }),
                            { status: 200 },
                        ),
                    );
            });
        };

        const rb = useRecycleBin();
        const pending = rb.loadRecycleBin();
        rb.resetRecycleBin();
        releaseFetch?.();
        await pending;

        assert.deepEqual(rb.items.value, []);
        assert.equal(rb.isLoading.value, false);
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('RecycleBinPanel.js: compareRecycleItems groups folders first and orders nulls last', () => {
    const folder = { isDirectory: true, name: 'Beta', deletedAt: 100, size: 0 };
    const datedNew = { isDirectory: false, name: 'Alpha.note', deletedAt: 300, size: 100 };
    const datedOld = { isDirectory: false, name: 'Gamma.note', deletedAt: 200, size: 500 };
    const undated = { isDirectory: false, name: 'AAA.note', deletedAt: null, size: 50 };

    const byDeletedDesc = [undated, datedOld, datedNew, folder].sort((a, b) =>
        compareRecycleItems(a, b, 'deletedAt', 'desc'),
    );
    assert.deepEqual(
        byDeletedDesc.map((i) => i.name),
        ['Beta', 'Alpha.note', 'Gamma.note', 'AAA.note'],
    );

    const bySizeDesc = [datedNew, datedOld, folder].sort((a, b) =>
        compareRecycleItems(a, b, 'size', 'desc'),
    );
    assert.deepEqual(
        bySizeDesc.map((i) => i.name),
        ['Beta', 'Gamma.note', 'Alpha.note'],
    );
});
