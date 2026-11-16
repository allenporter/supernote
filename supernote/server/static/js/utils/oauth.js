/**
 * OAuth 2.1 /login-bridge route parsing and display formatting helpers.
 *
 * Redirect URI validation is enforced server-side by `/authorize` and `POST /login-bridge`.
 * The frontend only verifies that `return_to` targets same-origin `/login-bridge` before
 * attaching `x-access-token`.
 */

const DEFAULT_MCP_SCOPE = 'supernote:all';

/** @type {Record<string, string>} */
const SCOPE_DESCRIPTIONS = {
    [DEFAULT_MCP_SCOPE]: 'Full access to notebooks, OCR transcripts, and semantic search',
};

/**
 * @param {string} scope
 * @returns {string}
 */
export function describeScope(scope) {
    return SCOPE_DESCRIPTIONS[scope] || 'Application-requested access scope';
}

/**
 * @param {string | null | undefined} redirectUri
 * @returns {OAuthRedirectTarget}
 */
export function describeRedirectTarget(redirectUri) {
    if (typeof redirectUri !== 'string' || !redirectUri.trim()) {
        return {
            scheme: '',
            isCustomScheme: false,
            hostLabel: 'Unspecified',
            fullUri: '',
        };
    }
    const trimmed = redirectUri.trim();
    try {
        const parsed = new URL(trimmed);
        const scheme = parsed.protocol.replace(/:$/, '').toLowerCase();
        const isCustomScheme = scheme !== 'http' && scheme !== 'https';
        if (!isCustomScheme) {
            return {
                scheme,
                isCustomScheme: false,
                hostLabel: parsed.host,
                fullUri: parsed.href,
            };
        }
        const firstSeg = (parsed.pathname || '').split('/').filter(Boolean)[0] || '';
        const hostLabel = parsed.host
            ? `${scheme}://${parsed.host}`
            : firstSeg
              ? `${scheme}:${firstSeg}`
              : `${scheme}:`;
        return {
            scheme,
            isCustomScheme: true,
            hostLabel,
            fullUri: parsed.href,
        };
    } catch {
        return {
            scheme: '',
            isCustomScheme: false,
            hostLabel: trimmed,
            fullUri: trimmed,
        };
    }
}

/**
 * @param {string} hashString
 * @param {string} currentOrigin
 * @returns {OAuthBridgeRequest | null}
 */
export function parseOAuthBridgeReturnTo(hashString, currentOrigin) {
    if (typeof hashString !== 'string' || !hashString.trim() || !currentOrigin) {
        return null;
    }
    const clean = hashString.replace(/^#\/?/, '').trim();
    const qIdx = clean.indexOf('?');
    if (qIdx === -1 || clean.slice(0, qIdx).toLowerCase() !== 'login') {
        return null;
    }

    const rawReturnTo = new URLSearchParams(clean.slice(qIdx + 1)).get('return_to');
    if (!rawReturnTo?.trim()) {
        return null;
    }

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
    const explicitRedirectUri = (bp.get('redirect_uri') || '').trim();
    const redirectUri = explicitRedirectUri || clientId;
    const codeChallenge = (bp.get('code_challenge') || '').trim();
    const state = bp.get('state') || null;
    const rawResource = (bp.get('resource') || '').trim();
    const resource = rawResource || null;
    const rawScope = (bp.get('scope') || '').trim();
    const scopeTokens = rawScope ? [...new Set(rawScope.split(/\s+/).filter(Boolean))] : [];
    const scopes = scopeTokens.length > 0 ? scopeTokens : [DEFAULT_MCP_SCOPE];
    const redirectTarget = describeRedirectTarget(redirectUri);

    if (!clientId || !codeChallenge || !redirectTarget.scheme) {
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
            bridgePathWithQuery: null,
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
        bridgePathWithQuery: `${bridgeUrl.pathname}${bridgeUrl.search}`,
    };
}
