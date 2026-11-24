/**
 * Unified Settings & System modal (`#/settings` and `#/system`):
 * - Access & API Keys tab (`#/settings`): connected MCP OAuth clients and static `sn_...` API keys.
 * - System & Queue tab (`#/system`): storage quota, AI processing pipeline status, and worker queue.
 */

import { nextTick, onMounted, ref } from 'vue';
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
import SystemPanel from './SystemPanel.js';

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
    components: {
        'system-panel': SystemPanel,
    },
    props: {
        activeSection: {
            type: String,
            default: 'access',
        },
    },
    emits: ['close', 'open-file', 'switch-section'],
    /**
     * @param {{ activeSection?: string }} _props
     * @param {{ emit: (event: string, ...args: any[]) => void }} context
     */
    setup(_props, { emit }) {
        /** @type {import('vue').Ref<HTMLElement | null>} */
        const dialogRef = ref(null);
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

        // LIFO Escape stack: outer modal registers first, inner Confirm Revoke registers second.
        useModalEscape(() => emit('close'));
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

        onMounted(() => {
            loadAll();
            nextTick(() => dialogRef.value?.focus());
        });

        return {
            dialogRef,
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
        <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-[2px] flex items-center justify-center p-4 z-[120] animate-fade-in" @click.self="$emit('close')">
            <div ref="dialogRef" tabindex="-1" role="dialog" aria-modal="true" aria-label="Settings & System"
                class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-4xl max-h-[88vh] flex flex-col overflow-hidden outline-none">
                <!-- Header -->
                <div class="flex items-center justify-between px-6 py-4 border-b border-stone-200/80 bg-[#F7F6F2]/60">
                    <div>
                        <h2 class="text-base font-bold text-slate-900">Settings &amp; System</h2>
                        <p class="text-xs text-stone-500">Manage connected MCP clients, personal API keys, AI pipeline configuration, and background tasks</p>
                    </div>
                    <button @click="$emit('close')" type="button"
                        class="p-1.5 rounded-lg text-stone-500 hover:text-slate-900 hover:bg-stone-200/60 transition-colors"
                        aria-label="Close settings">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <!-- Section Navigation Tabs -->
                <div class="flex items-center gap-1 px-4 sm:px-6 pt-2.5 border-b border-stone-200/80 bg-white overflow-x-auto">
                    <button @click="$emit('switch-section', 'access')" type="button"
                        :class="activeSection !== 'system' ? 'border-slate-900 text-slate-900 font-semibold' : 'border-transparent text-stone-500 hover:text-slate-900 font-medium'"
                        class="px-3 py-2.5 text-xs sm:text-sm border-b-2 flex items-center gap-1.5 whitespace-nowrap shrink-0">
                        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"></path>
                        </svg>
                        <span>Access &amp; API Keys</span>
                    </button>
                    <button @click="$emit('switch-section', 'system')" type="button"
                        :class="activeSection === 'system' ? 'border-slate-900 text-slate-900 font-semibold' : 'border-transparent text-stone-500 hover:text-slate-900 font-medium'"
                        class="px-3 py-2.5 text-xs sm:text-sm border-b-2 flex items-center gap-1.5 whitespace-nowrap shrink-0">
                        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z">
                            </path>
                        </svg>
                        <span>System &amp; Queue</span>
                    </button>
                </div>

                <!-- Content Body -->
                <div class="flex-1 overflow-y-auto p-6">
                    <!-- TAB 1: ACCESS & API KEYS -->
                    <div v-if="activeSection !== 'system'" class="space-y-6">
                        <section aria-labelledby="api-keys-heading" class="bg-stone-50/70 border border-stone-200/80 rounded-xl p-5 space-y-3.5">
                            <div>
                                <h3 id="api-keys-heading" class="text-sm font-bold text-slate-900">API keys</h3>
                                <p class="text-xs text-stone-600 mt-0.5">Static <code class="font-mono text-slate-700">sn_</code> Bearer keys for scripts, the CLI, and MCP clients without a browser sign-in. A key cannot manage keys or change your account.</p>
                            </div>
                            <form @submit.prevent="handleCreateKey" class="flex flex-col sm:flex-row gap-2">
                                <input v-model="newKeyName" type="text" maxlength="100" aria-label="API key name" placeholder="Key name (e.g. Antigravity, Laptop CLI)"
                                    :disabled="isCreatingKey"
                                    class="flex-1 min-w-0 px-3.5 py-2 bg-white border border-stone-200 rounded-xl outline-none focus:ring-2 focus:ring-slate-900 text-xs sm:text-sm disabled:opacity-60">
                                <select v-model="newKeyExpiryDays" aria-label="API key expiry" :disabled="isCreatingKey"
                                    class="px-3 py-2 bg-white border border-stone-200 rounded-xl text-xs sm:text-sm text-slate-700">
                                    <option v-for="opt in EXPIRY_OPTIONS" :key="opt.label" :value="opt.days">{{ opt.label }}</option>
                                </select>
                                <button type="submit" :disabled="isCreatingKey || !newKeyName.trim()"
                                    class="px-5 py-2 bg-slate-900 hover:bg-slate-800 disabled:opacity-40 text-white rounded-xl text-xs font-semibold whitespace-nowrap transition-colors">
                                    {{ isCreatingKey ? 'Creating...' : 'Create key' }}
                                </button>
                            </form>
                            <div v-if="createdKey" role="status" class="rounded-xl border border-emerald-200 bg-emerald-50 p-3.5 space-y-2">
                                <p class="text-xs text-emerald-900">Copy the key for <strong>{{ createdKey.name }}</strong> now. It will not be shown again.</p>
                                <div class="flex items-center gap-2">
                                    <code class="flex-1 min-w-0 break-all rounded-lg bg-white border border-emerald-200 px-3 py-2 text-xs font-mono text-slate-900 select-all">{{ createdKey.key }}</code>
                                    <button @click="copyCreatedKey" type="button" class="shrink-0 px-3 py-2 rounded-xl border border-stone-200 bg-white hover:bg-stone-50 text-xs font-semibold text-slate-900">Copy</button>
                                    <button @click="createdKey = null" type="button" class="shrink-0 px-3 py-2 text-xs font-semibold text-stone-600 hover:text-slate-900">Done</button>
                                </div>
                            </div>
                            <div class="bg-white border border-stone-200/90 rounded-xl overflow-hidden shadow-sm">
                                <p v-if="!isLoading && !apiKeys.length" class="px-4 py-5 text-center text-xs text-stone-500">No API keys.</p>
                                <ul v-else-if="apiKeys.length" class="divide-y divide-stone-100">
                                    <li v-for="apiKey in apiKeys" :key="apiKey.id" class="flex items-center justify-between gap-3 px-4 py-3 hover:bg-stone-50/70 transition-colors">
                                        <div class="min-w-0">
                                            <p class="text-xs sm:text-sm font-semibold text-slate-900 truncate">{{ apiKey.name }}</p>
                                            <p class="text-xs text-stone-500 mt-0.5">
                                                <span class="font-mono text-stone-600">{{ apiKey.keyPrefix }}</span>
                                                · Created {{ formatWhen(apiKey.createdAt) }} · Last used {{ formatWhen(apiKey.lastUsedAt) }} · {{ apiKey.expiresAt ? 'Expires ' + formatWhen(apiKey.expiresAt) : 'No expiry' }}
                                            </p>
                                        </div>
                                        <button @click="pendingRevoke = { kind: 'key', id: apiKey.id, label: apiKey.name }" type="button"
                                            class="shrink-0 px-3 py-1.5 rounded-xl border border-rose-200 text-rose-600 hover:bg-rose-50 text-xs font-semibold transition-colors">Revoke</button>
                                    </li>
                                </ul>
                            </div>
                        </section>

                        <section aria-labelledby="connected-clients-heading" class="bg-stone-50/70 border border-stone-200/80 rounded-xl p-5 space-y-3.5">
                            <div>
                                <h3 id="connected-clients-heading" class="text-sm font-bold text-slate-900">Connected clients</h3>
                                <p class="text-xs text-stone-600 mt-0.5">MCP clients you approved to read your notebooks. Disconnecting one ends its access immediately.</p>
                            </div>
                            <div class="bg-white border border-stone-200/90 rounded-xl overflow-hidden shadow-sm">
                                <p v-if="isLoading" class="px-4 py-5 text-center text-xs text-stone-500">Loading...</p>
                                <p v-else-if="!grants.length" class="px-4 py-5 text-center text-xs text-stone-500">No clients connected.</p>
                                <ul v-else class="divide-y divide-stone-100">
                                    <li v-for="grant in grants" :key="grant.id" class="flex items-center justify-between gap-3 px-4 py-3 hover:bg-stone-50/70 transition-colors">
                                        <div class="min-w-0">
                                            <p class="text-xs sm:text-sm font-semibold text-slate-900 truncate" :title="grant.clientId">{{ clientHost(grant.clientId) }}</p>
                                            <p class="text-xs text-stone-500 mt-0.5">
                                                <span v-for="scope in grant.scopes" :key="scope" :title="describeScope(scope)"
                                                    class="inline-block rounded-md bg-stone-100 border border-stone-200/80 text-slate-700 px-1.5 py-0.5 mr-1.5 font-mono text-[11px]">{{ scope }}</span>
                                                Connected {{ formatWhen(grant.createdAt) }} · Last used {{ formatWhen(grant.lastUsedAt) }} · Expires {{ formatWhen(grant.expiresAt) }}
                                            </p>
                                        </div>
                                        <button @click="pendingRevoke = { kind: 'grant', id: grant.id, label: clientHost(grant.clientId) }" type="button"
                                            class="shrink-0 px-3 py-1.5 rounded-xl border border-rose-200 text-rose-600 hover:bg-rose-50 text-xs font-semibold transition-colors">Disconnect</button>
                                    </li>
                                </ul>
                            </div>
                        </section>
                    </div>

                    <!-- TAB 2: SYSTEM & PROCESSING QUEUE -->
                    <system-panel v-else @open-file="$emit('open-file', $event)"></system-panel>
                </div>

                <!-- Footer -->
                <div class="px-6 py-3.5 border-t border-stone-200/80 bg-[#F7F6F2]/60 flex justify-end">
                    <button @click="$emit('close')" type="button"
                        class="px-5 py-1.5 bg-slate-900 hover:bg-slate-800 rounded-lg text-xs font-semibold text-white shadow-sm transition-colors">
                        Close
                    </button>
                </div>
            </div>

            <!-- Stacked Destructive Confirmation Dialog (z-[130]) -->
            <div v-if="pendingRevoke" role="dialog" aria-modal="true" aria-label="Confirm Revoke"
                class="fixed inset-0 z-[130] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px]" @click.self="!isRevoking && (pendingRevoke = null)">
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
