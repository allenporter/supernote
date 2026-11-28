import assert from 'node:assert/strict';
import test from 'node:test';

import { logout, setToken } from '../../supernote/server/static/js/api/http.js';
import {
    formatSourceLabel,
    useDigests,
} from '../../supernote/server/static/js/composables/useDigests.js';
import { clearToasts, useToast } from '../../supernote/server/static/js/composables/useToast.js';
import { mountComposable } from './helpers/vue_test_scope.mjs';

function makeSeedResponses() {
    return {
        groups: [
            { id: '1', uniqueIdentifier: 'cat-ai', name: 'AI Summaries' },
            { id: '2', uniqueIdentifier: 'cat-books', name: 'Books' },
            { id: '3', uniqueIdentifier: '', name: 'Malformed empty UUID' },
        ],
        items: [
            {
                id: '10',
                uniqueIdentifier: 'd-ai',
                categoryId: 'cat-ai',
                fileId: '100',
                content: 'Weekly architecture synthesis',
                dataSource: 'gemini-2.5-flash',
                sourcePath: 'Note/Architecture.note',
                updateTime: 3000,
            },
            {
                id: '11',
                uniqueIdentifier: 'd-book',
                categoryId: 'cat-books',
                fileId: null,
                content: 'Distributed systems consensus',
                comment: 'Review Paxos section',
                author: 'Leslie Lamport',
                sourcePath: 'Document/Papers/Consensus.pdf',
                handwriting: {
                    md5: 'hw-1',
                    transcript: 'Compare Raft leader election',
                    modelId: 'gemini-2.5-flash',
                    updateTime: 5100,
                },
                updateTime: 5000,
            },
            {
                id: '12',
                uniqueIdentifier: 'd-uncat',
                categoryId: '',
                fileId: null,
                content: 'Standalone reading quote',
                sourcePath: 'Document/Papers/Consensus.pdf',
                updateTime: 4000,
            },
            {
                id: '13',
                uniqueIdentifier: 'd-orphan',
                categoryId: 'deleted-cat-uuid',
                fileId: null,
                content: 'Orphaned digest falls into uncategorized',
                updateTime: 2000,
            },
        ],
    };
}

test('useDigests.js: formatSourceLabel extracts basename from VFS paths', () => {
    assert.equal(formatSourceLabel('Document/Archive/Paper.pdf'), 'Paper.pdf');
    assert.equal(formatSourceLabel('Daily.note'), 'Daily.note');
});

test('useDigests.js: filters by category, orphaned-uncategorized, source, and search query', async () => {
    const origFetch = globalThis.fetch;
    const mounted = await mountComposable(() => useDigests());
    try {
        setToken('digests-filter-tok');
        const seed = makeSeedResponses();
        globalThis.fetch = async (url) => {
            if (url === '/api/file/query/summary/group') {
                return new Response(JSON.stringify({ summaryDOList: seed.groups }), {
                    status: 200,
                });
            }
            return new Response(JSON.stringify({ digests: seed.items, total: seed.items.length }), {
                status: 200,
            });
        };

        const state = mounted.result;
        await state.loadDigests();

        // Sorted by lastModifiedTime desc
        assert.deepEqual(
            state.filteredDigests.value.map((d) => d.id),
            ['11', '12', '10', '13'],
        );
        assert.equal(state.categoryCounts.value.all, 4);
        assert.equal(state.categoryCounts.value.digests, 3);
        assert.equal(state.categoryCounts.value['ai-summaries'], 1);
        assert.equal(state.categoryCounts.value.uncategorized, 2);
        assert.equal(state.categoryCounts.value['cat-ai'], 1);
        assert.equal(state.categoryCounts.value['cat-books'], 1);
        assert.equal('' in state.categoryCounts.value, false);

        assert.deepEqual(state.availableSources.value, [
            { path: 'Note/Architecture.note', label: 'Architecture.note', count: 1 },
            { path: 'Document/Papers/Consensus.pdf', label: 'Consensus.pdf', count: 2 },
        ]);

        state.selectedCategoryFilter.value = 'digests';
        assert.deepEqual(
            state.filteredDigests.value.map((d) => d.id),
            ['11', '12', '13'],
        );

        state.selectedCategoryFilter.value = 'ai-summaries';
        assert.deepEqual(
            state.filteredDigests.value.map((d) => d.id),
            ['10'],
        );

        state.selectedCategoryFilter.value = 'uncategorized';
        assert.deepEqual(
            state.filteredDigests.value.map((d) => d.id),
            ['12', '13'],
        );

        state.selectedCategoryFilter.value = 'all';
        state.selectedSourcePath.value = 'Document/Papers/Consensus.pdf';
        assert.deepEqual(
            state.filteredDigests.value.map((d) => d.id),
            ['11', '12'],
        );

        state.searchQuery.value = 'lamport';
        assert.deepEqual(
            state.filteredDigests.value.map((d) => d.id),
            ['11'],
        );

        state.searchQuery.value = 'raft leader';
        assert.deepEqual(
            state.filteredDigests.value.map((d) => d.id),
            ['11'],
        );
    } finally {
        mounted.unmount();
        clearToasts();
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('useDigests.js: clears stale selectedSourcePath and deleted selectedCategoryFilter automatically', async () => {
    const origFetch = globalThis.fetch;
    const mounted = await mountComposable(() => useDigests());
    let includeBooks = true;
    try {
        setToken('digests-stale-tok');
        const seed = makeSeedResponses();
        globalThis.fetch = async (url) => {
            if (url === '/api/file/query/summary/group') {
                const groups = includeBooks
                    ? seed.groups
                    : seed.groups.filter((g) => g.uniqueIdentifier !== 'cat-books');
                return new Response(JSON.stringify({ summaryDOList: groups }), { status: 200 });
            }
            return new Response(JSON.stringify({ digests: seed.items, total: seed.items.length }), {
                status: 200,
            });
        };

        const state = mounted.result;
        await state.loadDigests();

        // Switching from 'digests' to 'ai-summaries' narrows availableSources and clears stale source
        state.selectedCategoryFilter.value = 'digests';
        state.selectedSourcePath.value = 'Document/Papers/Consensus.pdf';
        state.selectedCategoryFilter.value = 'ai-summaries';
        assert.equal(state.selectedSourcePath.value, null);
        assert.deepEqual(state.availableSources.value, [
            { path: 'Note/Architecture.note', label: 'Architecture.note', count: 1 },
        ]);

        // Select Consensus.pdf, then switch to cat-ai where Consensus.pdf does not exist
        state.selectedSourcePath.value = 'Document/Papers/Consensus.pdf';
        state.selectedCategoryFilter.value = 'cat-ai';
        assert.equal(state.selectedSourcePath.value, null);
        assert.deepEqual(
            state.filteredDigests.value.map((d) => d.id),
            ['10'],
        );

        // Built-in views survive reload without being reset to 'all'
        state.selectedCategoryFilter.value = 'ai-summaries';
        await state.loadDigests();
        assert.equal(state.selectedCategoryFilter.value, 'ai-summaries');

        // Select cat-books, then reload after it disappears remotely
        state.selectedCategoryFilter.value = 'cat-books';
        includeBooks = false;
        await state.loadDigests();
        assert.equal(state.selectedCategoryFilter.value, 'all');
    } finally {
        mounted.unmount();
        clearToasts();
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('useDigests.js: mutations enforce whitespace guards, reload on success, and toast on error', async () => {
    const origFetch = globalThis.fetch;
    const prevSpark = /** @type {any} */ (globalThis).SparkMD5;
    /** @type {any} */ (globalThis).SparkMD5 = { hash: (/** @type {string} */ s) => `md5:${s}` };
    const mounted = await mountComposable(() => useDigests());
    const { toasts } = useToast();
    let failWrites = false;
    try {
        setToken('digests-mut-tok');
        globalThis.fetch = async (url, init) => {
            const isWrite =
                url === '/api/file/add/summary/group' ||
                url === '/api/file/update/summary/group' ||
                url === '/api/file/delete/summary/group' ||
                url === '/api/file/add/summary' ||
                url === '/api/file/update/summary' ||
                url === '/api/file/delete/summary';
            if (isWrite && failWrites) {
                return new Response(JSON.stringify({ errorMsg: 'Disk full' }), { status: 500 });
            }
            if (isWrite) {
                assert.ok(
                    init?.method === 'POST' || init?.method === 'PUT' || init?.method === 'DELETE',
                );
                return new Response(JSON.stringify({ success: true, id: '99' }), { status: 200 });
            }
            return new Response(JSON.stringify({ summaryDOList: [] }), { status: 200 });
        };

        const state = mounted.result;
        const sampleCat = {
            id: '750000000000000002',
            uniqueIdentifier: 'cat-books',
            name: 'Books',
            description: null,
            creationTime: 0,
            lastModifiedTime: 0,
        };

        // Whitespace guards short-circuit without network calls
        assert.equal(await state.addCategory('   '), false);
        assert.equal(await state.renameCategory(sampleCat, '   '), false);
        assert.equal(await state.addDigest({ content: '   ' }), false);

        // Success paths
        assert.equal(await state.addCategory('Books'), true);
        assert.equal(await state.renameCategory(sampleCat, 'Reading'), true);
        assert.equal(await state.addDigest({ content: 'New highlight' }), true);
        assert.equal(await state.editDigest('99', { content: 'Edited' }), true);
        assert.equal(await state.removeDigest('99'), true);

        state.selectedCategoryFilter.value = 'cat-books';
        assert.equal(await state.removeCategory(sampleCat), true);
        assert.equal(state.selectedCategoryFilter.value, 'all');

        // Failure path surfaces error toast and returns false
        clearToasts();
        failWrites = true;
        assert.equal(await state.addDigest({ content: 'Will fail' }), false);
        assert.match(toasts.value[0]?.message || '', /Failed to create digest: Disk full/);
    } finally {
        mounted.unmount();
        clearToasts();
        if (prevSpark === undefined) {
            delete (/** @type {any} */ (globalThis).SparkMD5);
        } else {
            /** @type {any} */ (globalThis).SparkMD5 = prevSpark;
        }
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('useDigests.js: loadDigests ignores stale responses and captures error state', async () => {
    const origFetch = globalThis.fetch;
    const mounted = await mountComposable(() => useDigests());
    try {
        setToken('digests-race-tok');
        /** @type {Array<(res: Response) => void>} */
        const resolvers = [];
        globalThis.fetch = () =>
            new Promise((resolve) => {
                resolvers.push(resolve);
            });

        const state = mounted.result;
        const firstLoad = state.loadDigests();
        const secondLoad = state.loadDigests();

        // Resolve second load first (indices 2, 3), then stale first load (indices 0, 1)
        resolvers[2](new Response(JSON.stringify({ summaryDOList: [] }), { status: 200 }));
        resolvers[3](
            new Response(
                JSON.stringify({
                    digests: [{ id: '20', uniqueIdentifier: 'fresh', content: 'Fresh' }],
                    total: 1,
                }),
                { status: 200 },
            ),
        );
        await secondLoad;

        resolvers[0](new Response(JSON.stringify({ summaryDOList: [] }), { status: 200 }));
        resolvers[1](
            new Response(
                JSON.stringify({
                    digests: [{ id: '10', uniqueIdentifier: 'stale', content: 'Stale' }],
                    total: 1,
                }),
                { status: 200 },
            ),
        );
        await firstLoad;

        assert.deepEqual(
            state.digests.value.map((d) => d.id),
            ['20'],
        );

        // Error state
        globalThis.fetch = async () =>
            new Response(JSON.stringify({ errorMsg: 'Backend down' }), { status: 500 });
        await state.loadDigests();
        assert.equal(state.error.value, 'Backend down');

        state.resetDigests();
        assert.equal(state.error.value, null);
        assert.equal(state.digests.value.length, 0);
    } finally {
        mounted.unmount();
        clearToasts();
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});
