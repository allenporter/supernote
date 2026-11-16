import assert from 'node:assert/strict';
import test from 'node:test';

import {
    formatSize,
    getErrorMessage,
    getFileExtension,
    normalizeEpochMs,
    resolveFileExt,
} from '../../supernote/server/static/js/utils/format.js';

test('format.js: normalizes seconds, milliseconds, and ISO timestamps to epoch ms', () => {
    assert.equal(normalizeEpochMs(1700000000), 1700000000000);
    assert.equal(normalizeEpochMs('1700000000000'), 1700000000000);
    assert.equal(normalizeEpochMs('2026-01-15T00:00:00Z'), Date.parse('2026-01-15T00:00:00Z'));
    assert.equal(normalizeEpochMs(0), null);
    assert.equal(normalizeEpochMs(''), null);
});

test('format.js: formats byte sizes, extracts dotfile-safe extensions, and unwraps errors', () => {
    assert.equal(formatSize(0, '—'), '—');
    assert.equal(formatSize(1536), '1.5 KB');

    assert.equal(getFileExtension('.gitignore'), '');
    assert.equal(getFileExtension('/Note/.hidden'), '');
    assert.equal(getFileExtension('Archive.tar.GZ'), 'gz');
    assert.equal(resolveFileExt({ name: '.env' }), '');
    assert.equal(resolveFileExt({ name: 'Notes.NOTE' }), 'note');

    assert.equal(getErrorMessage(new Error('Disk full')), 'Disk full');
    assert.equal(getErrorMessage('Plain string failure'), 'Plain string failure');
    assert.equal(getErrorMessage(null, 'Fallback'), 'Fallback');
});
