/**
 * Copy plain text to the system clipboard with a fallback for non-secure HTTP contexts
 * (e.g., accessing Open Private Cloud via a LAN IP over plain HTTP).
 *
 * @param {string | null | undefined} text
 * @returns {Promise<boolean>} true if copied successfully, false otherwise.
 */
export async function copyTextToClipboard(text) {
    const value = String(text ?? '');
    if (!value) return false;

    if (
        typeof navigator !== 'undefined' &&
        navigator.clipboard &&
        typeof navigator.clipboard.writeText === 'function'
    ) {
        try {
            await navigator.clipboard.writeText(value);
            return true;
        } catch {
            // Fall through to execCommand fallback (e.g., permission denied or insecure context)
        }
    }

    if (typeof document === 'undefined' || !document.body) {
        return false;
    }

    const textarea = document.createElement('textarea');
    textarea.value = value;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '0';
    textarea.style.left = '0';
    textarea.style.width = '1px';
    textarea.style.height = '1px';
    textarea.style.opacity = '0';
    textarea.style.pointerEvents = 'none';

    document.body.appendChild(textarea);
    try {
        textarea.focus({ preventScroll: true });
        textarea.select();
        textarea.setSelectionRange(0, value.length);
        return Boolean(typeof document.execCommand === 'function' && document.execCommand('copy'));
    } catch {
        return false;
    } finally {
        document.body.removeChild(textarea);
    }
}
