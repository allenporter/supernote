import { ref } from 'vue';

export default {
    props: {
        oauthRequest: {
            type: Object,
            default: null,
        },
        isSubmitting: {
            type: Boolean,
            default: false,
        },
    },
    emits: ['login'],
    /**
     * @param {{ oauthRequest?: OAuthBridgeRequest | null, isSubmitting?: boolean }} props
     * @param {{ emit: (event: string, ...args: any[]) => void }} context
     */
    setup(props, { emit }) {
        const email = ref('');
        const password = ref('');

        const handleSubmit = () => {
            if (props.isSubmitting || !email.value || !password.value) return;
            emit('login', { email: email.value, password: password.value });
        };

        return {
            email,
            password,
            handleSubmit,
        };
    },
    template: `
    <div class="max-w-md mx-auto bg-white rounded-2xl border border-stone-200/90 shadow-lg overflow-hidden mt-6 sm:mt-16 animate-fade-in">
        <div class="p-6 sm:p-10">
            <div class="text-center mb-8">
                <div class="w-12 h-12 bg-slate-900 rounded-xl flex items-center justify-center text-white shadow-sm mx-auto mb-4">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z">
                        </path>
                    </svg>
                </div>
                <h2 class="text-xl font-bold text-slate-900 tracking-tight">Sign in to Open Private Cloud</h2>
                <p class="text-xs text-stone-500 mt-1.5">Self-hosted sync, notebooks, and schedule for your Supernote</p>
            </div>

            <div v-if="oauthRequest?.isValid"
                class="mb-5 px-3.5 py-2.5 bg-stone-50 border border-stone-200/90 rounded-xl text-xs text-stone-600 leading-relaxed">
                Sign in to review an authorization request from
                <span class="font-mono font-semibold text-slate-900 [overflow-wrap:anywhere]">{{ oauthRequest.clientId }}</span>.
            </div>

            <form @submit.prevent="handleSubmit" class="space-y-5">
                <div>
                    <label for="login-email" class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1.5">Email Address</label>
                    <input id="login-email" type="email" v-model="email" autocomplete="username" required
                        class="w-full px-3.5 py-2.5 bg-stone-50 rounded-xl border border-stone-200 text-sm focus:border-slate-900 focus:ring-2 focus:ring-slate-900/15 outline-none transition-all"
                        placeholder="you@example.com">
                </div>

                <div>
                    <label for="login-password" class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1.5">Password</label>
                    <input id="login-password" type="password" v-model="password" autocomplete="current-password" required
                        class="w-full px-3.5 py-2.5 bg-stone-50 rounded-xl border border-stone-200 text-sm focus:border-slate-900 focus:ring-2 focus:ring-slate-900/15 outline-none transition-all"
                        placeholder="••••••••">
                </div>

                <button type="submit"
                    :disabled="isSubmitting"
                    class="w-full bg-slate-900 hover:bg-slate-800 text-white font-semibold text-sm py-2.5 px-4 rounded-xl shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex justify-center items-center">
                    <span v-if="isSubmitting" class="animate-spin rounded-full h-4 w-4 border-2 border-white/30 border-t-white mr-2"></span>
                    {{ isSubmitting ? 'Signing in...' : 'Sign In' }}
                </button>
            </form>
        </div>
        <div class="bg-[#F7F6F2] px-6 py-3.5 text-center text-[11px] font-mono text-stone-500 border-t border-stone-200/80">
            Unofficial server for Supernote · Not affiliated with Ratta
        </div>
    </div>
    `,
};
