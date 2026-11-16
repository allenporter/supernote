import { nextTick, onMounted, ref, watch } from 'vue';
import { describeScope } from '../utils/oauth.js';

export default {
    name: 'OAuthConsentCard',
    props: {
        request: {
            type: Object,
            required: true,
        },
        isSubmitting: {
            type: Boolean,
            default: false,
        },
        completedOutcome: {
            type: String,
            default: null,
        },
    },
    emits: ['approve', 'deny', 'dismiss'],
    /**
     * @param {Record<string, any>} props
     */
    setup(props) {
        /** @type {import('vue').Ref<HTMLButtonElement | null>} */
        const primaryButtonRef = ref(null);

        onMounted(() => {
            nextTick(() => {
                primaryButtonRef.value?.focus({ preventScroll: true });
            });
        });

        watch(
            () => [props.completedOutcome, props.request?.isValid],
            () => {
                primaryButtonRef.value?.focus({ preventScroll: true });
            },
            { flush: 'post' },
        );

        return {
            primaryButtonRef,
            describeScope,
        };
    },
    template: `
    <div role="region" aria-labelledby="oauth-consent-heading"
        class="max-w-lg mx-auto bg-white rounded-2xl border border-stone-200/90 shadow-lg overflow-hidden mt-1 sm:mt-10 animate-fade-in">
        <div class="p-4 sm:p-8">
            <div class="text-center mb-4 sm:mb-6">
                <div :class="request.isValid ? 'bg-slate-900 text-white' : 'bg-rose-100 text-rose-700'"
                    class="w-10 h-10 sm:w-12 sm:h-12 rounded-xl flex items-center justify-center shadow-sm mx-auto mb-2.5 sm:mb-4">
                    <svg v-if="request.isValid" class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z">
                        </path>
                    </svg>
                    <svg v-else class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z">
                        </path>
                    </svg>
                </div>
                <h2 id="oauth-consent-heading" class="text-xl font-bold text-slate-900 tracking-tight">
                    <template v-if="!request.isValid">Invalid Authorization Request</template>
                    <template v-else-if="completedOutcome === 'approved'">Application Authorized</template>
                    <template v-else-if="completedOutcome === 'denied'">Authorization Denied</template>
                    <template v-else>Authorize Application</template>
                </h2>
                <p class="text-xs text-stone-500 mt-1.5 leading-relaxed">
                    <template v-if="!request.isValid">
                        This OAuth request could not be verified and automatic redirection was blocked.
                    </template>
                    <template v-else>
                        An external client is requesting permission to access your Open Private Cloud account.
                    </template>
                </p>
            </div>

            <!-- Requesting Client & Redirect Target Summary -->
            <div class="bg-stone-50/90 border border-stone-200/90 rounded-xl p-3.5 sm:p-4 space-y-2.5 sm:space-y-3.5 mb-4 sm:mb-5">
                <div>
                    <div class="text-[11px] font-bold uppercase tracking-wider text-stone-500 mb-0.5 sm:mb-1">Requesting Client</div>
                    <div class="font-mono text-xs sm:text-[13px] font-semibold text-slate-900 [overflow-wrap:anywhere]" data-testid="oauth-client-id">
                        {{ request.clientId || 'Unspecified' }}
                    </div>
                </div>

                <div class="border-t border-stone-200/80 pt-2.5 sm:pt-3">
                    <div class="flex flex-wrap items-center justify-between gap-2 mb-1">
                        <span class="text-[11px] font-bold uppercase tracking-wider text-stone-500">Redirect Target</span>
                        <span v-if="request.redirectTarget?.isCustomScheme"
                            class="px-2 py-0.5 rounded-md bg-amber-100 text-amber-900 border border-amber-200 text-[10px] font-mono font-semibold"
                            data-testid="oauth-scheme-badge">
                            Custom URI ({{ request.redirectTarget.scheme }}://)
                        </span>
                        <span v-else-if="request.redirectTarget?.scheme === 'https'"
                            class="px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-800 border border-emerald-200 text-[10px] font-mono font-semibold"
                            data-testid="oauth-scheme-badge">
                            HTTPS
                        </span>
                        <span v-else-if="request.redirectTarget?.scheme === 'http'"
                            class="px-2 py-0.5 rounded-md bg-stone-200/80 text-stone-700 border border-stone-300/80 text-[10px] font-mono font-semibold"
                            data-testid="oauth-scheme-badge">
                            HTTP
                        </span>
                    </div>
                    <div class="font-mono text-xs sm:text-[13px] font-semibold text-slate-900 [overflow-wrap:anywhere]" data-testid="oauth-redirect-host">
                        {{ request.redirectTarget?.hostLabel || request.redirectUri || 'Unspecified' }}
                    </div>
                    <div v-if="request.redirectTarget?.fullUri && request.redirectTarget.fullUri !== request.redirectTarget.hostLabel"
                        class="font-mono text-[11px] text-stone-500 [overflow-wrap:anywhere] mt-0.5" data-testid="oauth-redirect-uri">
                        {{ request.redirectTarget.fullUri }}
                    </div>
                </div>

                <div v-if="request.resource" class="border-t border-stone-200/80 pt-2.5 sm:pt-3">
                    <div class="text-[11px] font-bold uppercase tracking-wider text-stone-500 mb-0.5 sm:mb-1">Target Audience</div>
                    <div class="font-mono text-xs text-slate-800 [overflow-wrap:anywhere]" data-testid="oauth-resource">
                        {{ request.resource }}
                    </div>
                </div>
            </div>

            <!-- Requested Scopes -->
            <div v-if="request.isValid" class="mb-4 sm:mb-6">
                <div class="text-[11px] font-bold uppercase tracking-wider text-stone-500 mb-1.5 sm:mb-2">Requested Scopes</div>
                <ul class="space-y-1.5 sm:space-y-2" data-testid="oauth-scopes-list">
                    <li v-for="scope in request.scopes" :key="scope"
                        class="flex items-start gap-2.5 bg-white border border-stone-200/90 rounded-xl p-2.5 sm:p-3">
                        <svg class="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                        </svg>
                        <div class="min-w-0">
                            <code class="inline-block px-1.5 py-0.5 bg-stone-100 border border-stone-200/90 rounded text-[11px] font-mono font-semibold text-slate-900 break-all">{{ scope }}</code>
                            <p class="text-xs text-stone-600 mt-1 leading-snug">{{ describeScope(scope) }}</p>
                        </div>
                    </li>
                </ul>
            </div>

            <!-- Validation Error State -->
            <template v-if="!request.isValid">
                <div class="bg-rose-50 border border-rose-200 text-rose-800 rounded-xl p-3.5 text-xs leading-relaxed mb-5" role="alert">
                    {{ request.error }}
                </div>
                <button ref="primaryButtonRef" @click="$emit('dismiss')" type="button"
                    class="w-full bg-slate-900 hover:bg-slate-800 text-white font-semibold text-sm py-2.5 px-4 rounded-xl shadow-sm transition-all">
                    Return to Cloud
                </button>
            </template>

            <!-- Custom URI Scheme Post-Action State -->
            <template v-else-if="completedOutcome">
                <div class="bg-stone-100 border border-stone-200 text-slate-800 rounded-xl p-3.5 text-xs leading-relaxed mb-5">
                    <template v-if="completedOutcome === 'approved'">
                        Your browser launched <code class="font-mono font-semibold">{{ request.redirectTarget.hostLabel }}</code> with a single-use authorization code. You may switch back to the application now.
                    </template>
                    <template v-else>
                        Access was denied and <code class="font-mono font-semibold">{{ request.redirectTarget.hostLabel }}</code> was notified with <code class="font-mono">error=access_denied</code>.
                    </template>
                </div>
                <button ref="primaryButtonRef" @click="$emit('dismiss')" type="button"
                    class="w-full bg-slate-900 hover:bg-slate-800 text-white font-semibold text-sm py-2.5 px-4 rounded-xl shadow-sm transition-all">
                    Continue to Cloud
                </button>
            </template>

            <!-- Active Consent Actions -->
            <template v-else>
                <p class="text-[11px] text-stone-500 mb-3 sm:mb-4 leading-relaxed">
                    Approving issues a single-use PKCE authorization code to <span class="font-mono text-slate-700">{{ request.redirectTarget.hostLabel }}</span>.
                </p>
                <div class="flex flex-col-reverse sm:flex-row gap-2 sm:gap-2.5">
                    <button @click="$emit('deny')" type="button" :disabled="isSubmitting"
                        class="w-full sm:w-1/2 px-4 py-2 sm:py-2.5 bg-white hover:bg-stone-50 text-slate-700 hover:text-slate-900 border border-stone-300 font-semibold text-sm rounded-xl shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed">
                        Deny
                    </button>
                    <button ref="primaryButtonRef" @click="$emit('approve')" type="button" :disabled="isSubmitting"
                        class="w-full sm:w-1/2 px-4 py-2 sm:py-2.5 bg-slate-900 hover:bg-slate-800 text-white font-semibold text-sm rounded-xl shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2">
                        <span v-if="isSubmitting" class="animate-spin rounded-full h-4 w-4 border-2 border-white/30 border-t-white"></span>
                        <span>{{ isSubmitting ? 'Authorizing...' : 'Approve' }}</span>
                    </button>
                </div>
            </template>
        </div>
        <div class="bg-[#F7F6F2] px-4 sm:px-6 py-2.5 sm:py-3 text-center text-[10px] sm:text-[11px] font-mono text-stone-500 border-t border-stone-200/80">
            OAuth 2.1 · PKCE S256 · Authorize only applications you trust
        </div>
    </div>
    `,
};
