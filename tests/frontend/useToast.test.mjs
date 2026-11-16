import assert from 'node:assert/strict';
import test from 'node:test';

import {
    clearToasts,
    dismissToast,
    showToast,
    useToast,
} from '../../supernote/server/static/js/composables/useToast.js';

test('useToast.js: cancels active timer on manual dismiss, auto-expires on tick, and clears all on clearToasts', (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const { toasts } = useToast();
    clearToasts();

    const manualId = showToast('Dismissed early', 'info', 4000);
    const autoId = showToast('Auto expires', 'success', 4000);
    assert.deepEqual(toasts.value, [
        { id: manualId, message: 'Dismissed early', type: 'info' },
        { id: autoId, message: 'Auto expires', type: 'success' },
    ]);

    // Dismissing a timed toast clears its pending setTimeout cleanly
    dismissToast(manualId);
    assert.deepEqual(toasts.value, [{ id: autoId, message: 'Auto expires', type: 'success' }]);

    t.mock.timers.tick(3999);
    assert.equal(toasts.value.length, 1);
    t.mock.timers.tick(1);
    assert.deepEqual(toasts.value, []);

    showToast('Session toast', 'error', 5000);
    assert.equal(toasts.value.length, 1);
    clearToasts();
    assert.deepEqual(toasts.value, []);
    t.mock.timers.tick(5000);
    assert.deepEqual(toasts.value, []);
});
