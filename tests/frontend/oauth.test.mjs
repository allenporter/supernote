import assert from 'node:assert/strict';
import test from 'node:test';

import {
    describeRedirectTarget,
    describeScope,
    parseOAuthBridgeReturnTo,
} from '../../supernote/server/static/js/utils/oauth.js';

test('oauth.js: describes scopes/redirect targets and validates same-origin /login-bridge return_to', () => {
    assert.match(describeScope('supernote:all'), /Full access/);
    assert.deepEqual(describeRedirectTarget('cursor://anysphere.cursor-mcp/cb'), {
        scheme: 'cursor',
        isCustomScheme: true,
        hostLabel: 'cursor://anysphere.cursor-mcp',
        fullUri: 'cursor://anysphere.cursor-mcp/cb',
    });
    assert.deepEqual(describeRedirectTarget('https://claude.ai/api/mcp/auth_callback'), {
        scheme: 'https',
        isCustomScheme: false,
        hostLabel: 'claude.ai',
        fullUri: 'https://claude.ai/api/mcp/auth_callback',
    });

    assert.equal(
        parseOAuthBridgeReturnTo(
            `#/login?return_to=${encodeURIComponent('https://evil.example/login-bridge?client_id=x&code_challenge=y')}`,
            'http://127.0.0.1:8080',
        ),
        null,
    );

    const bridgeQuery =
        '/login-bridge?client_id=https%3A%2F%2Fclaude.ai%2Fcb&redirect_uri=https%3A%2F%2Fclaude.ai%2Fcb&code_challenge=abc123&state=s1';
    assert.deepEqual(
        parseOAuthBridgeReturnTo(
            `#/login?return_to=${encodeURIComponent(bridgeQuery)}`,
            'http://127.0.0.1:8080',
        ),
        {
            isValid: true,
            error: null,
            clientId: 'https://claude.ai/cb',
            redirectUri: 'https://claude.ai/cb',
            codeChallenge: 'abc123',
            state: 's1',
            resource: null,
            scopes: ['supernote:all'],
            redirectTarget: {
                scheme: 'https',
                isCustomScheme: false,
                hostLabel: 'claude.ai',
                fullUri: 'https://claude.ai/cb',
            },
            bridgePathWithQuery: bridgeQuery,
        },
    );
});
