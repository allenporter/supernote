import assert from 'node:assert/strict';
import test from 'node:test';

import { logout, setToken } from '../../supernote/server/static/js/api/http.js';
import { useFileSystem } from '../../supernote/server/static/js/composables/useFileSystem.js';

test('useFileSystem.js: loadDirectory ignores stale responses and surfaces 401 vs 500 errors', async () => {
    const origFetch = globalThis.fetch;
    const origWindow = globalThis.window;
    const origConsoleError = console.error;
    /** @type {Array<(items: any[]) => void>} */
    const resolvers = [];

    try {
        console.error = () => {};
        globalThis.window = /** @type {any} */ ({ location: { reload() {} } });
        setToken('vfs-tok');
        globalThis.fetch = async (url, init) => {
            const body = JSON.parse(String(init?.body || '{}'));
            if (body.directoryId === '500') {
                return new Response('Server error', { status: 500 });
            }
            if (body.directoryId === '401') {
                return new Response('Unauthorized', { status: 401 });
            }
            if (url === '/api/user/logout') {
                return new Response('{}', { status: 200 });
            }
            return new Promise((resolve) => {
                resolvers.push((items) =>
                    resolve(
                        new Response(JSON.stringify({ userFileVOList: items }), { status: 200 }),
                    ),
                );
            });
        };

        const vfs = useFileSystem();
        const firstLoad = vfs.loadDirectory('10');
        const secondLoad = vfs.loadDirectory('20');

        assert.equal(vfs.isLoading.value, true);
        resolvers[1]([{ id: '2', fileName: 'Newer.note', isFolder: 'N', size: 10, updateTime: 2 }]);
        await secondLoad;
        // First load is still in flight -> activeOps keeps isLoading true
        assert.equal(vfs.isLoading.value, true);
        assert.equal(vfs.currentDirectoryId.value, '20');

        resolvers[0]([{ id: '1', fileName: 'Stale.note', isFolder: 'N', size: 10, updateTime: 1 }]);
        await firstLoad;
        assert.equal(vfs.isLoading.value, false);
        assert.equal(vfs.currentDirectoryId.value, '20');
        assert.deepEqual(
            vfs.files.value.map((f) => f.name),
            ['Newer.note'],
        );

        await vfs.loadDirectory('500');
        assert.equal(vfs.error.value, 'Failed to load directory');
        assert.equal(vfs.loadedDirectoryId.value, null);

        await vfs.loadDirectory('401');
        assert.equal(vfs.error.value, 'Unauthorized');
        assert.equal(vfs.loadedDirectoryId.value, null);
    } finally {
        console.error = origConsoleError;
        await logout({ reload: false });
        globalThis.fetch = origFetch;
        globalThis.window = origWindow;
    }
});

test('useFileSystem.js: uploadFiles pins target directory across mid-upload navigation and resets cleanly', async () => {
    const origFetch = globalThis.fetch;
    const origFileReader = globalThis.FileReader;
    const origSpark = globalThis.SparkMD5;
    /** @type {Array<{ url: string, body: any }>} */
    const calls = [];

    try {
        setToken('upload-tok');
        globalThis.SparkMD5 = /** @type {any} */ ({
            hash: () => 'md5',
            ArrayBuffer: { hash: () => 'md5-buf' },
        });
        globalThis.FileReader = /** @type {any} */ (
            class MockFileReader {
                readAsArrayBuffer() {
                    this.result = new ArrayBuffer(4);
                    queueMicrotask(() => this.onload?.());
                }
            }
        );

        globalThis.fetch = async (url, init) => {
            const urlStr = String(url);
            if (urlStr === '/oss/upload') {
                // Simulate user navigating to folder '99' mid-upload
                vfs.currentDirectoryId.value = '99';
                return new Response('', { status: 200 });
            }
            const body = init?.body ? JSON.parse(String(init.body)) : {};
            calls.push({ url: urlStr, body });
            if (urlStr === '/api/file/upload/apply') {
                return new Response(
                    JSON.stringify({ fullUploadUrl: '/oss/upload', innerName: 'inner.note' }),
                    { status: 200 },
                );
            }
            return new Response(JSON.stringify({ userFileVOList: [] }), { status: 200 });
        };

        const vfs = useFileSystem();
        vfs.currentDirectoryId.value = '42';

        const liveFiles = [new File(['a'], 'One.note'), new File(['b'], 'Two.note')];
        const uploadPromise = vfs.uploadFiles(liveFiles);
        liveFiles.length = 0; // Mutating caller array after invocation must not drop files
        await uploadPromise;

        const applyDirs = calls
            .filter((c) => c.url === '/api/file/upload/apply')
            .map((c) => c.body.directoryId);
        const finishDirs = calls
            .filter((c) => c.url === '/api/file/upload/finish')
            .map((c) => c.body.directoryId);
        assert.deepEqual(applyDirs, ['42', '42']);
        assert.deepEqual(finishDirs, ['42', '42']);

        // Because currentDirectoryId moved to '99' mid-upload, uploadFiles did not clobber '99' with a reload of '42'
        assert.equal(calls.filter((c) => c.url === '/api/file/list/query').length, 0);

        vfs.resetFileSystem();
        assert.equal(vfs.currentDirectoryId.value, '0');
        assert.deepEqual(vfs.files.value, []);
        assert.equal(vfs.isLoading.value, false);
    } finally {
        await logout({ reload: false });
        globalThis.fetch = origFetch;
        globalThis.FileReader = origFileReader;
        globalThis.SparkMD5 = origSpark;
    }
});
