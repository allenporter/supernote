/**
 * Account settings view (`#/settings`): authorized MCP OAuth clients and static API keys.
 */

import { onMounted, ref } from 'vue';
import {
    createApiKey,
    fetchApiKeys,
    fetchOAuthGrants,
    revokeApiKey,
    revokeOAuthGrant,
} from '../api/client.js';
import { useModalEscape } from '../composables/useModalEscape.js';
import { showToast } from '../composables/useToast.js';
import { copyTextToClipboard } from '../utils/clipboard.js';
import { formatShortDate, getErrorMessage } from '../utils/format.js';
import { describeRedirectTarget, describeScope } from '../utils/oauth.js';

const EXPIRY_OPTIONS = [
    { label: 'Never expires', days: null },
    { label: '30 days', days: 30 },
    { label: '90 days', days: 90 },
    { label: '1 year', days: 365 },
];

/**
 * @typedef {{ kind: 'grant' | 'key', id: string, label: string }} PendingRevoke
 */

export default {
    name: 'SettingsPanel',
    setup() {
        /** @type {import('vue').Ref<OAuthGrant[]>} */
        const grants = ref([]);
        /** @type {import('vue').Ref<ApiKeyInfo[]>} */
        const apiKeys = ref([]);
        const isLoading = ref(true);

        const newKeyName = ref('');
        /** @type {import('vue').Ref<number | null>} */
        const newKeyExpiryDays = ref(null);
        const isCreatingKey = ref(false);
        /** @type {import('vue').Ref<CreatedApiKey | null>} */
        const createdKey = ref(null);

        /** @type {import('vue').Ref<PendingRevoke | null>} */
        const pendingRevoke = ref(null);
        const isRevoking = ref(false);

        async function loadAll() {
            try {
                [grants.value, apiKeys.value] = await Promise.all([
                    fetchOAuthGrants(),
                    fetchApiKeys(),
                ]);
            } catch (e) {
                showToast(getErrorMessage(e));
            } finally {
                isLoading.value = false;
            }
        }

        async function handleCreateKey() {
            const name = newKeyName.value.trim();
            if (!name || isCreatingKey.value) return;
            isCreatingKey.value = true;
            try {
                createdKey.value = await createApiKey(name, newKeyExpiryDays.value);
                newKeyName.value = '';
                newKeyExpiryDays.value = null;
                apiKeys.value = await fetchApiKeys();
            } catch (e) {
                showToast(getErrorMessage(e));
            } finally {
                isCreatingKey.value = false;
            }
        }

        async function copyCreatedKey() {
            const copied = await copyTextToClipboard(createdKey.value?.key);
            showToast(
                copied ? 'API key copied' : 'Copy failed; select the key and copy it',
                copied ? 'success' : 'error',
            );
        }

        async function confirmRevoke() {
            const target = pendingRevoke.value;
            if (!target || isRevoking.value) return;
            isRevoking.value = true;
            try {
                if (target.kind === 'grant') {
                    await revokeOAuthGrant(target.id);
                    grants.value = grants.value.filter((g) => g.id !== target.id);
                    showToast('Client disconnected', 'success');
                } else {
                    await revokeApiKey(target.id);
                    apiKeys.value = apiKeys.value.filter((k) => k.id !== target.id);
                    if (createdKey.value?.id === target.id) createdKey.value = null;
                    showToast('API key revoked', 'success');
                }
                pendingRevoke.value = null;
            } catch (e) {
                showToast(getErrorMessage(e));
            } finally {
                isRevoking.value = false;
            }
        }

        useModalEscape(
            () => {
                if (!isRevoking.value) pendingRevoke.value = null;
            },
            () => Boolean(pendingRevoke.value),
        );

        /**
         * @param {number | null | undefined} timestamp
         */
        const formatWhen = (timestamp) => formatShortDate(timestamp) || 'Never';
        /**
         * @param {string} clientId
         */
        const clientHost = (clientId) => describeRedirectTarget(clientId).hostLabel;

        onMounted(loadAll);

        return {
            EXPIRY_OPTIONS,
            grants,
            apiKeys,
            isLoading,
            newKeyName,
            newKeyExpiryDays,
            isCreatingKey,
            createdKey,
            pendingRevoke,
            isRevoking,
            handleCreateKey,
            copyCreatedKey,
            confirmRevoke,
            formatWhen,
            clientHost,
            describeScope,
        };
    },
    template: `
    <div class="max-w-3xl mx-auto animate-fade-in">
        <div class="space-y-6">
            <h2 class="text-xl font-bold text-slate-900">Settings</h2>

            <section aria-labelledby="connected-clients-heading" class="bg-white border border-stone-200 rounded-2xl p-5 space-y-3">
                <div>
                    <h3 id="connected-clients-heading" class="text-base font-bold text-slate-900">Connected clients</h3>
                    <p class="text-xs text-stone-600">MCP clients you approved to read your notebooks. Disconnecting one ends its access immediately.</p>
                </div>
                <p v-if="isLoading" class="text-xs text-stone-500">Loading...</p>
                <p v-else-if="!grants.length" class="text-xs text-stone-500">No clients connected.</p>
                <ul v-else class="divide-y divide-stone-100">
                    <li v-for="grant in grants" :key="grant.id" class="flex items-center justify-between gap-3 py-3">
                        <div class="min-w-0">
                            <p class="text-sm font-semibold text-slate-900 truncate" :title="grant.clientId">{{ clientHost(grant.clientId) }}</p>
                            <p class="text-xs text-stone-600">
                                <span v-for="scope in grant.scopes" :key="scope" :title="describeScope(scope)"
                                    class="inline-block rounded-full bg-stone-100 px-2 py-0.5 mr-1 font-mono text-[11px]">{{ scope }}</span>
                                Connected {{ formatWhen(grant.createdAt) }} · Last used {{ formatWhen(grant.lastUsedAt) }} · Expires {{ formatWhen(grant.expiresAt) }}
                            </p>
                        </div>
                        <button @click="pendingRevoke = { kind: 'grant', id: grant.id, label: clientHost(grant.clientId) }" type="button"
                            class="shrink-0 px-3 py-1.5 rounded-xl border border-rose-200 text-rose-600 hover:bg-rose-50 text-xs font-semibold">Disconnect</button>
                    </li>
                </ul>
            </section>

            <section aria-labelledby="api-keys-heading" class="bg-white border border-stone-200 rounded-2xl p-5 space-y-3">
                <div>
                    <h3 id="api-keys-heading" class="text-base font-bold text-slate-900">API keys</h3>
                    <p class="text-xs text-stone-600">Static <code>sn_</code> Bearer keys for scripts, the CLI, and MCP clients without a browser sign-in. A key cannot manage keys or change your account.</p>
                </div>
                <form @submit.prevent="handleCreateKey" class="flex flex-col sm:flex-row gap-2">
                    <input v-model="newKeyName" type="text" maxlength="100" aria-label="API key name" placeholder="Key name (e.g. Laptop CLI)"
                        :disabled="isCreatingKey"
                        class="flex-1 min-w-0 px-3.5 py-2 bg-stone-50 border border-stone-200 rounded-xl outline-none focus:ring-2 focus:ring-slate-900 text-sm disabled:opacity-60">
                    <select v-model="newKeyExpiryDays" aria-label="API key expiry" :disabled="isCreatingKey"
                        class="px-3 py-2 bg-stone-50 border border-stone-200 rounded-xl text-sm">
                        <option v-for="opt in EXPIRY_OPTIONS" :key="opt.label" :value="opt.days">{{ opt.label }}</option>
                    </select>
                    <button type="submit" :disabled="isCreatingKey || !newKeyName.trim()"
                        class="px-5 py-2 bg-slate-900 hover:bg-slate-800 disabled:opacity-40 text-white rounded-xl text-xs font-semibold">
                        {{ isCreatingKey ? 'Creating...' : 'Create key' }}
                    </button>
                </form>
                <div v-if="createdKey" role="status" class="rounded-xl border border-emerald-200 bg-emerald-50 p-3 space-y-2">
                    <p class="text-xs text-emerald-800">Copy the key for <strong>{{ createdKey.name }}</strong> now. It will not be shown again.</p>
                    <div class="flex items-center gap-2">
                        <code class="flex-1 min-w-0 break-all rounded-lg bg-white border border-emerald-100 px-3 py-2 text-xs select-all">{{ createdKey.key }}</code>
                        <button @click="copyCreatedKey" type="button" class="shrink-0 px-3 py-2 rounded-xl border border-stone-200 bg-white text-xs font-semibold text-slate-900">Copy</button>
                        <button @click="createdKey = null" type="button" class="shrink-0 px-3 py-2 text-xs font-semibold text-stone-600 hover:text-slate-900">Done</button>
                    </div>
                </div>
                <p v-if="!isLoading && !apiKeys.length" class="text-xs text-stone-500">No API keys.</p>
                <ul v-else-if="apiKeys.length" class="divide-y divide-stone-100">
                    <li v-for="apiKey in apiKeys" :key="apiKey.id" class="flex items-center justify-between gap-3 py-3">
                        <div class="min-w-0">
                            <p class="text-sm font-semibold text-slate-900 truncate">{{ apiKey.name }}</p>
                            <p class="text-xs text-stone-600">
                                <span class="font-mono">{{ apiKey.keyPrefix }}</span>
                                · Created {{ formatWhen(apiKey.createdAt) }} · Last used {{ formatWhen(apiKey.lastUsedAt) }} · {{ apiKey.expiresAt ? 'Expires ' + formatWhen(apiKey.expiresAt) : 'No expiry' }}
                            </p>
                        </div>
                        <button @click="pendingRevoke = { kind: 'key', id: apiKey.id, label: apiKey.name }" type="button"
                            class="shrink-0 px-3 py-1.5 rounded-xl border border-rose-200 text-rose-600 hover:bg-rose-50 text-xs font-semibold">Revoke</button>
                    </li>
                </ul>
            </section>
        </div>

        <div v-if="pendingRevoke" role="dialog" aria-modal="true" aria-label="Confirm Revoke"
            class="fixed inset-0 z-[110] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px]" @click.self="!isRevoking && (pendingRevoke = null)">
            <div class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-sm p-6 animate-fade-in">
                <h3 class="text-base font-bold text-slate-900 mb-1">
                    {{ pendingRevoke.kind === 'grant' ? 'Disconnect' : 'Revoke' }} "{{ pendingRevoke.label }}"?
                </h3>
                <p class="text-xs text-stone-600 mb-5 leading-relaxed">
                    {{ pendingRevoke.kind === 'grant'
                        ? 'This client loses access on its next request and must be approved again to reconnect.'
                        : 'Anything using this key loses access immediately.' }}
                </p>
                <div class="flex justify-end gap-2.5">
                    <button @click="pendingRevoke = null" :disabled="isRevoking" type="button"
                        class="px-4 py-2 text-xs text-stone-600 hover:text-slate-900 font-semibold rounded-xl disabled:opacity-40">Cancel</button>
                    <button @click="confirmRevoke" :disabled="isRevoking" type="button"
                        class="px-5 py-2 bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white rounded-xl text-xs font-semibold">
                        {{ isRevoking ? 'Working...' : (pendingRevoke.kind === 'grant' ? 'Disconnect' : 'Revoke') }}
                    </button>
                </div>
            </div>
        </div>
    </div>
    `,
};
