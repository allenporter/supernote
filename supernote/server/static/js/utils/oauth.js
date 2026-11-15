/**
 * OAuth 2.1 /login-bridge URL validation, redirect safety, and scope display helpers.
 */

const BLOCKED_REDIRECT_PROTOCOLS = new Set([
    'javascript:',
    'data:',
    'vbscript:',
    'file:',
    'blob:',
    'about:',
    'ws:',
    'wss:',
    'ftp:',
    'ftps:',
    'mailto:',
    'tel:',
    'sms:',
    'view-source:',
    'chrome:',
    'chrome-extension:',
    'moz-extension:',
    'edge:'
]);

const SCOPE_DESCRIPTIONS = {
    'supernote:all': 'Full access to notebooks, OCR transcripts, semantic search, and cloud data',
    'notebooks:read': 'Read access to notebooks and OCR transcripts',
    'notebooks:sync': 'Sync notebooks and files with this companion application',
    'tasks:read': 'Read access to tasks and schedule items',
    'tasks:write': 'Create and update tasks and schedule items'
};

export function parseSafeUrl(rawUrl) {
    if (typeof rawUrl !== 'string') return null;
    const trimmed = rawUrl.trim();
    if (!trimmed || /[\u0000-\u001f\u007f]/.test(trimmed)) return null;
    try {
        const parsed = new URL(trimmed);
        const protocol = parsed.protocol.toLowerCase();
        if (!/^[a-z][a-z0-9+.-]*:$/.test(protocol) || BLOCKED_REDIRECT_PROTOCOLS.has(protocol)) {
            return null;
        }
        if (parsed.username || parsed.password) {
            return null;
        }
        const decodedSegments = decodeURIComponent(parsed.pathname || '').split(/[\\/]/);
        if (decodedSegments.includes('..')) {
            return null;
        }
        return parsed;
    } catch {
        return null;
    }
}

function matchesOriginAndPathPrefix(registeredUrl, candidateUrl) {
    if (
        registeredUrl.protocol.toLowerCase() !== candidateUrl.protocol.toLowerCase() ||
        registeredUrl.host.toLowerCase() !== candidateUrl.host.toLowerCase()
    ) {
        return false;
    }
    const regPath = (registeredUrl.pathname || '').replace(/\/+$/, '');
    const candidatePath = candidateUrl.pathname || '';
    return !regPath || candidatePath === regPath || candidatePath.startsWith(`${regPath}/`);
}

export function isAllowedOAuthRedirectUri(clientId, redirectUri) {
    if (typeof clientId !== 'string' || !clientId.trim()) return false;
    const redirectParsed = parseSafeUrl(redirectUri);
    if (!redirectParsed) return false;

    const redirectProto = redirectParsed.protocol.toLowerCase();
    const isHttpRedirect = redirectProto === 'http:' || redirectProto === 'https:';

    if (isHttpRedirect) {
        if (!redirectParsed.host) return false;
        const clientParsed = parseSafeUrl(clientId);
        if (!clientParsed || !clientParsed.host) return false;
        return matchesOriginAndPathPrefix(clientParsed, redirectParsed);
    }

    if (!redirectParsed.host && !(redirectParsed.pathname || '').replace(/\//g, '')) {
        return false;
    }

    const trimmedClient = clientId.trim();
    if (/^[a-z][a-z0-9+.-]*:/i.test(trimmedClient)) {
        const clientParsed = parseSafeUrl(trimmedClient);
        if (!clientParsed) return false;
        return matchesOriginAndPathPrefix(clientParsed, redirectParsed);
    }

    return true;
}

export function describeRedirectTarget(redirectUri) {
    const parsed = parseSafeUrl(redirectUri);
    if (!parsed) {
        const fallback = typeof redirectUri === 'string' && redirectUri.trim() ? redirectUri.trim() : 'Unknown';
        return {
            scheme: '',
            isCustomScheme: false,
            hostLabel: fallback,
            fullUri: fallback
        };
    }

    const scheme = parsed.protocol.replace(/:$/, '').toLowerCase();
    const isCustomScheme = scheme !== 'http' && scheme !== 'https';
    if (!isCustomScheme) {
        return {
            scheme,
            isCustomScheme: false,
            hostLabel: parsed.host,
            fullUri: parsed.href
        };
    }

    let hostLabel = `${scheme}://`;
    if (parsed.host) {
        hostLabel = `${scheme}://${parsed.host}`;
    } else {
        const firstSeg = (parsed.pathname || '').split('/').filter(Boolean)[0] || '';
        hostLabel = firstSeg ? `${scheme}:${firstSeg}` : `${scheme}:`;
    }
    return {
        scheme,
        isCustomScheme: true,
        hostLabel,
        fullUri: parsed.href
    };
}

export function describeScope(scope) {
    return SCOPE_DESCRIPTIONS[scope] || 'Application-requested access scope';
}

function parseRequestedScopes(searchParams) {
    const rawScope = searchParams.get('scope');
    let tokens = [];
    if (rawScope && rawScope.trim() && rawScope !== 'None') {
        tokens = rawScope.trim().split(/\s+/).filter(Boolean);
    } else {
        const legacyScopes = searchParams.get('scopes');
        if (legacyScopes && legacyScopes.trim() && legacyScopes !== 'None') {
            tokens = legacyScopes
                .replace(/^\[|\]$/g, '')
                .split(/[\s,]+/)
                .map(s => s.replace(/^['"]|['"]$/g, '').trim())
                .filter(Boolean);
        }
    }
    return tokens.length > 0 ? [...new Set(tokens)] : ['supernote:all'];
}

export function parseOAuthBridgeReturnTo(hashString, currentOrigin) {
    if (typeof hashString !== 'string' || !hashString.trim() || !currentOrigin) {
        return null;
    }
    const clean = hashString.replace(/^#\/?/, '').trim();
    const qIdx = clean.indexOf('?');
    if (qIdx === -1) return null;

    const pathPart = clean.slice(0, qIdx).toLowerCase();
    if (pathPart !== 'login') return null;

    const outerParams = new URLSearchParams(clean.slice(qIdx + 1));
    const rawReturnTo = outerParams.get('return_to');
    if (!rawReturnTo || !rawReturnTo.trim()) return null;

    let bridgeUrl;
    try {
        bridgeUrl = new URL(rawReturnTo.trim(), currentOrigin);
    } catch {
        return null;
    }

    if (bridgeUrl.origin !== currentOrigin || bridgeUrl.pathname !== '/login-bridge') {
        return null;
    }

    const bp = bridgeUrl.searchParams;
    const clientId = (bp.get('client_id') || '').trim();
    const redirectUri = (bp.get('redirect_uri') || '').trim();
    const codeChallenge = (bp.get('code_challenge') || '').trim();
    const rawState = bp.get('state');
    const state = rawState && rawState !== 'None' ? rawState : null;
    const rawResource = bp.get('resource');
    const resource = rawResource && rawResource !== 'None' ? rawResource.trim() : null;
    const scopes = parseRequestedScopes(bp);
    const redirectTarget = describeRedirectTarget(redirectUri);

    if (!clientId || !redirectUri || !codeChallenge) {
        return {
            isValid: false,
            error: 'Missing required OAuth 2.1 parameters (client_id, redirect_uri, or PKCE code_challenge).',
            clientId,
            redirectUri,
            codeChallenge,
            state,
            resource,
            scopes,
            redirectTarget,
            bridgePathWithQuery: null
        };
    }

    if (!isAllowedOAuthRedirectUri(clientId, redirectUri)) {
        return {
            isValid: false,
            error: 'The callback redirect_uri does not match the requesting client_id or uses a disallowed URI scheme.',
            clientId,
            redirectUri,
            codeChallenge,
            state,
            resource,
            scopes,
            redirectTarget,
            bridgePathWithQuery: null
        };
    }

    return {
        isValid: true,
        error: null,
        clientId,
        redirectUri,
        codeChallenge,
        state,
        resource,
        scopes,
        redirectTarget,
        bridgePathWithQuery: `${bridgeUrl.pathname}${bridgeUrl.search}`
    };
}

export function buildOAuthDeniedRedirectUrl(redirectUri, state = null) {
    const parsed = parseSafeUrl(redirectUri);
    if (!parsed) return null;
    parsed.searchParams.set('error', 'access_denied');
    if (typeof state === 'string' && state.length > 0) {
        parsed.searchParams.set('state', state);
    }
    return parsed.toString();
}
