import assert from 'node:assert/strict';
import test from 'node:test';

import {
    createDigest,
    createDigestCategory,
    deleteDigest,
    deleteDigestCategory,
    fetchDigestCategories,
    fetchDigests,
    formatDigestMarkdown,
    generateDigestUuid,
    normalizeDigestCategory,
    normalizeDigestItem,
    normalizeSourcePath,
    parseDigestMetadata,
    parseDigestTags,
    resolveSourceFileId,
    updateDigest,
    updateDigestCategory,
} from '../../supernote/server/static/js/api/digests.js';
import { logout, setToken } from '../../supernote/server/static/js/api/http.js';

/**
 * Install a deterministic SparkMD5 stub on globalThis and return a restore callback.
 */
function installSparkMd5Stub() {
    const prev = /** @type {any} */ (globalThis).SparkMD5;
    /** @type {any} */ (globalThis).SparkMD5 = {
        hash: (/** @type {string} */ value) => `md5:${value}`,
    };
    return () => {
        if (prev === undefined) {
            delete (/** @type {any} */ (globalThis).SparkMD5);
        } else {
            /** @type {any} */ (globalThis).SparkMD5 = prev;
        }
    };
}

test('digests.js: generateDigestUuid produces 32-char lowercase hex with LAN-HTTP fallback', () => {
    assert.match(generateDigestUuid(), /^[0-9a-f]{32}$/);

    const origRandomUUID = globalThis.crypto.randomUUID;
    try {
        Object.defineProperty(globalThis.crypto, 'randomUUID', {
            value: undefined,
            configurable: true,
        });
        const fallbackUuid = generateDigestUuid();
        assert.match(fallbackUuid, /^[0-9a-f]{32}$/);
        assert.equal(fallbackUuid[12], '4');
    } finally {
        Object.defineProperty(globalThis.crypto, 'randomUUID', {
            value: origRandomUUID,
            configurable: true,
        });
    }
});

test('digests.js: normalizeSourcePath, parseDigestMetadata, and parseDigestTags sanitize wire values', () => {
    assert.equal(normalizeSourcePath('/Document/Archive/Paper.pdf'), 'Document/Archive/Paper.pdf');
    assert.equal(normalizeSourcePath('  Note/Daily.note '), 'Note/Daily.note');
    assert.equal(normalizeSourcePath('///'), null);
    assert.equal(normalizeSourcePath(null), null);

    assert.deepEqual(parseDigestMetadata('{"author":"Ada","page":3}'), { author: 'Ada', page: 3 });
    assert.equal(parseDigestMetadata('not-json'), null);
    assert.equal(parseDigestMetadata('[1,2]'), null);
    assert.equal(parseDigestMetadata('   '), null);

    assert.deepEqual(parseDigestTags('work, design , , review'), ['work', 'design', 'review']);
    assert.deepEqual(parseDigestTags(null), []);
});

test('digests.js: normalizeDigestCategory and normalizeDigestItem unwrap fields and author fallback', () => {
    assert.deepEqual(
        normalizeDigestCategory({
            id: '750000000000000001',
            uniqueIdentifier: 'a'.repeat(32),
            name: '  ',
            description: '  Notes  ',
            createTime: 1000,
            updateTime: 2000,
        }),
        {
            id: '750000000000000001',
            uniqueIdentifier: 'a'.repeat(32),
            name: 'Untitled Category',
            description: 'Notes',
            creationTime: 1000,
            lastModifiedTime: 2000,
        },
    );

    const item = normalizeDigestItem({
        id: '750000000000000123',
        uniqueIdentifier: 'b'.repeat(32),
        parentUniqueIdentifier: '',
        fileId: null,
        content: 'Highlighted quote',
        commentStr: '  Great point  ',
        author: null,
        metadata: JSON.stringify({ author: 'Grace Hopper' }),
        sourcePath: '/Document/Book.pdf',
        handwriteInnerName: 'hw-key',
        tags: 'reading, classics',
        creationTime: 1700000000000,
        lastModifiedTime: 1700000005000,
    });
    assert.deepEqual(item, {
        id: '750000000000000123',
        uniqueIdentifier: 'b'.repeat(32),
        parentUniqueIdentifier: null,
        fileId: null,
        content: 'Highlighted quote',
        commentStr: 'Great point',
        author: 'Grace Hopper',
        sourcePath: 'Document/Book.pdf',
        dataSource: null,
        tags: ['reading', 'classics'],
        hasHandwriting: true,
        handwriting: null,
        handwriteInnerName: 'hw-key',
        commentHandwriteName: null,
        creationTime: 1700000000000,
        lastModifiedTime: 1700000005000,
        metadata: { author: 'Grace Hopper' },
    });

    const digestVo = normalizeDigestItem({
        id: '750000000000000124',
        uniqueIdentifier: 'e'.repeat(32),
        categoryId: 'f'.repeat(32),
        fileId: '750000000000000888',
        content: 'Latency matters',
        comment: 'Measure p99',
        author: 'Jeff Dean',
        sourcePath: 'Document/Systems.pdf',
        tags: ['perf', 'systems'],
        handwriting: {
            md5: 'abc123',
            transcript: 'Check tail latency under load',
            modelId: 'gemini-2.5-flash',
            updateTime: 1700000010000,
        },
        creationTime: 1700000000000,
        updateTime: 1700000009000,
    });
    assert.deepEqual(digestVo, {
        id: '750000000000000124',
        uniqueIdentifier: 'e'.repeat(32),
        parentUniqueIdentifier: 'f'.repeat(32),
        fileId: '750000000000000888',
        content: 'Latency matters',
        commentStr: 'Measure p99',
        author: 'Jeff Dean',
        sourcePath: 'Document/Systems.pdf',
        dataSource: null,
        tags: ['perf', 'systems'],
        hasHandwriting: true,
        handwriting: {
            md5: 'abc123',
            transcript: 'Check tail latency under load',
            modelId: 'gemini-2.5-flash',
            updateTime: 1700000010000,
        },
        handwriteInnerName: null,
        commentHandwriteName: null,
        creationTime: 1700000000000,
        lastModifiedTime: 1700000009000,
        metadata: null,
    });

    assert.equal(
        formatDigestMarkdown(digestVo),
        'Latency matters\n\n> Measure p99\n\n**Handwritten annotation:**\n\nCheck tail latency under load',
    );
});

test('digests.js: fetchDigestCategories and fetchDigests query categories and paginated /api/extended/digests', async () => {
    const origFetch = globalThis.fetch;
    /** @type {Array<{ url: string, method: string, body: any }>} */
    const calls = [];
    try {
        setToken('digest-fetch-tok');
        globalThis.fetch = async (url, init) => {
            calls.push({
                url: String(url),
                method: init?.method || 'GET',
                body: init?.body ? JSON.parse(String(init.body)) : null,
            });
            if (url === '/api/file/query/summary/group') {
                return new Response(
                    JSON.stringify({
                        summaryDOList: [
                            {
                                id: '750000000000000001',
                                uniqueIdentifier: 'c'.repeat(32),
                                name: 'AI Summaries',
                                creationTime: 1000,
                                lastModifiedTime: 2000,
                            },
                        ],
                    }),
                    { status: 200 },
                );
            }
            if (url === '/api/extended/digests?limit=200&offset=0') {
                return new Response(
                    JSON.stringify({
                        digests: [
                            {
                                id: '750000000000000010',
                                uniqueIdentifier: 'd'.repeat(32),
                                categoryId: 'c'.repeat(32),
                                fileId: '750000000000000999',
                                content: '# Daily Notes',
                                sourcePath: 'Note/Daily.note',
                                dataSource: 'GEMINI',
                            },
                        ],
                        total: 2,
                        limit: 200,
                        offset: 0,
                    }),
                    { status: 200 },
                );
            }
            return new Response(
                JSON.stringify({
                    digests: [
                        {
                            id: '750000000000000011',
                            uniqueIdentifier: 'e'.repeat(32),
                            content: 'Second page digest',
                            handwriting: {
                                md5: 'hw-md5',
                                transcript: 'Handwritten note',
                                modelId: 'gemini-2.5-flash',
                                updateTime: 3000,
                            },
                        },
                    ],
                    total: 2,
                    limit: 200,
                    offset: 1,
                }),
                { status: 200 },
            );
        };

        const categories = await fetchDigestCategories();
        const digests = await fetchDigests();
        assert.equal(categories.length, 1);
        assert.equal(categories[0].name, 'AI Summaries');
        assert.equal(digests.length, 2);
        assert.equal(digests[0].fileId, '750000000000000999');
        assert.equal(digests[1].handwriting?.transcript, 'Handwritten note');
        assert.deepEqual(calls[0], {
            url: '/api/file/query/summary/group',
            method: 'POST',
            body: { page: 1, size: 0 },
        });
        assert.deepEqual(calls[1], {
            url: '/api/extended/digests?limit=200&offset=0',
            method: 'GET',
            body: null,
        });
        assert.deepEqual(calls[2], {
            url: '/api/extended/digests?limit=200&offset=1',
            method: 'GET',
            body: null,
        });
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('digests.js: category CRUD verifies HTTP methods, md5Hash, and description clearing', async () => {
    const origFetch = globalThis.fetch;
    const restoreMd5 = installSparkMd5Stub();
    /** @type {Array<{ url: string, method: string, body: any }>} */
    const calls = [];
    try {
        setToken('digest-cat-tok');
        globalThis.fetch = async (url, init) => {
            calls.push({
                url: String(url),
                method: init?.method || 'GET',
                body: init?.body ? JSON.parse(String(init.body)) : null,
            });
            return new Response(JSON.stringify({ success: true, id: '750000000000000055' }), {
                status: 200,
            });
        };

        const created = await createDigestCategory('  Research  ', '  Papers  ');
        assert.equal(created.id, '750000000000000055');
        assert.equal(calls[0].method, 'POST');
        assert.equal(calls[0].url, '/api/file/add/summary/group');
        assert.equal(calls[0].body.name, 'Research');
        assert.equal(calls[0].body.description, 'Papers');
        assert.equal(calls[0].body.md5Hash, 'md5:Research');

        await updateDigestCategory(
            {
                id: '750000000000000055',
                uniqueIdentifier: created.uniqueIdentifier,
                name: 'Research',
                description: 'Papers',
                creationTime: 1,
                lastModifiedTime: 1,
            },
            { name: '  Renamed  ', description: null },
        );
        assert.equal(calls[1].method, 'PUT');
        assert.equal(calls[1].url, '/api/file/update/summary/group');
        assert.equal(calls[1].body.name, 'Renamed');
        assert.equal(calls[1].body.description, '');
        assert.equal(calls[1].body.md5Hash, 'md5:Renamed');

        await deleteDigestCategory('750000000000000055');
        assert.deepEqual(calls[2], {
            url: '/api/file/delete/summary/group',
            method: 'DELETE',
            body: { id: '750000000000000055' },
        });
    } finally {
        restoreMd5();
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('digests.js: createDigestCategory throws explicitly when SparkMD5 is unavailable', async () => {
    setToken('digest-nomd5-tok');
    try {
        await assert.rejects(() => createDigestCategory('Missing MD5'), /SparkMD5 is required/);
    } finally {
        await logout({ reload: false });
    }
});

test('digests.js: digest CRUD trims whitespace, clears category with empty string, and deletes by ID', async () => {
    const origFetch = globalThis.fetch;
    /** @type {Array<{ url: string, method: string, body: any }>} */
    const calls = [];
    try {
        setToken('digest-crud-tok');
        globalThis.fetch = async (url, init) => {
            calls.push({
                url: String(url),
                method: init?.method || 'GET',
                body: init?.body ? JSON.parse(String(init.body)) : null,
            });
            return new Response(JSON.stringify({ success: true, id: '750000000000000077' }), {
                status: 200,
            });
        };

        const created = await createDigest({
            parentUniqueIdentifier: 'c'.repeat(32),
            content: 'Excerpt text',
            commentStr: '  My note  ',
            author: '  Ada  ',
            sourcePath: '/Document/Paper.pdf',
        });
        assert.equal(created.id, '750000000000000077');
        assert.equal(calls[0].method, 'POST');
        assert.equal(calls[0].body.commentStr, 'My note');
        assert.equal(calls[0].body.author, 'Ada');
        assert.equal(calls[0].body.sourcePath, 'Document/Paper.pdf');

        await updateDigest('750000000000000077', {
            parentUniqueIdentifier: null,
            content: 'Updated text',
            commentStr: '   ',
            author: '  Grace  ',
        });
        assert.equal(calls[1].method, 'PUT');
        assert.equal(calls[1].body.id, '750000000000000077');
        assert.equal(calls[1].body.parentUniqueIdentifier, '');
        assert.equal(calls[1].body.commentStr, '');
        assert.equal(calls[1].body.author, 'Grace');

        await deleteDigest('750000000000000077');
        assert.deepEqual(calls[2], {
            url: '/api/file/delete/summary',
            method: 'DELETE',
            body: { id: '750000000000000077' },
        });
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});

test('digests.js: resolveSourceFileId handles files, rejects folders, and returns null on miss/error', async () => {
    const origFetch = globalThis.fetch;
    /** @type {Record<string, Response>} */
    let nextResponse = new Response(JSON.stringify({ entriesVO: null }), { status: 200 });
    try {
        setToken('digest-resolve-tok');
        globalThis.fetch = async () => nextResponse;

        assert.equal(await resolveSourceFileId('  '), null);

        nextResponse = new Response(
            JSON.stringify({
                entriesVO: { id: '750000000000000888', tag: 'file', name: 'Paper.pdf' },
            }),
            { status: 200 },
        );
        assert.equal(await resolveSourceFileId('Document/Paper.pdf'), '750000000000000888');

        nextResponse = new Response(
            JSON.stringify({
                entriesVO: { id: '750000000000000889', tag: 'folder', name: 'Document' },
            }),
            { status: 200 },
        );
        assert.equal(await resolveSourceFileId('Document'), null);

        nextResponse = new Response(JSON.stringify({ entriesVO: null }), { status: 200 });
        assert.equal(await resolveSourceFileId('Document/Missing.pdf'), null);

        nextResponse = new Response(JSON.stringify({ errorMsg: 'Server error' }), { status: 500 });
        assert.equal(await resolveSourceFileId('Document/Error.pdf'), null);
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
    }
});
