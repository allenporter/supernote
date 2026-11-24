import assert from 'node:assert/strict';
import test from 'node:test';
import { setToken } from '../../supernote/server/static/js/api/http.js';
import {
    fetchWikiPage,
    fetchWikiPages,
    fetchWikiStatus,
    saveWikiPage,
    searchWikiPages,
} from '../../supernote/server/static/js/api/wiki.js';

test('wiki API client fetches pages, handles 404 disabled gracefully, and saves pages', async () => {
    const origFetch = globalThis.fetch;
    setToken('test-token');
    try {
        globalThis.fetch = async (url, init) => {
            const s = String(url);
            if (s.includes('/api/extended/wiki/pages?')) {
                return new Response(
                    JSON.stringify({ pages: [{ slug: 'projects/a', title: 'A' }] }),
                    {
                        status: 200,
                    },
                );
            }
            if (s.endsWith('/api/extended/wiki/pages/projects/a') && init?.method === 'PUT') {
                return new Response(
                    JSON.stringify({ page: { slug: 'projects/a', title: 'A2', version: 2 } }),
                    { status: 200 },
                );
            }
            if (s.includes('/api/extended/wiki/search?')) {
                return new Response(
                    JSON.stringify({ hits: [{ slug: 'projects/a', score: 4.0 }] }),
                    {
                        status: 200,
                    },
                );
            }
            if (s.endsWith('/api/extended/wiki/status')) {
                return new Response(JSON.stringify({ error: 'Not found' }), { status: 404 });
            }
            return new Response(JSON.stringify({ error: 'Not found' }), { status: 404 });
        };

        const pages = await fetchWikiPages();
        assert.equal(pages?.length, 1);
        assert.equal(pages?.[0].slug, 'projects/a');

        const saved = await saveWikiPage('projects/a', { title: 'A2', body_md: 'Updated' });
        assert.equal(saved.version, 2);

        const hits = await searchWikiPages('a');
        assert.equal(hits[0].slug, 'projects/a');

        assert.equal(await fetchWikiPage('missing'), null);
        assert.equal(await fetchWikiStatus(), null);
    } finally {
        globalThis.fetch = origFetch;
    }
});
