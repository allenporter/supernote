import { ref } from 'vue';

export default {
    emits: ['login'],
    setup(props, { emit }) {
        const email = ref('');
        const password = ref('');
        const isLoading = ref(false);

        const handleSubmit = async () => {
            if (!email.value || !password.value) return;
            isLoading.value = true;
            try {
                await emit('login', { email: email.value, password: password.value });
            } finally {
                isLoading.value = false;
            }
        };

        return {
            email,
            password,
            isLoading,
            handleSubmit
        };
    },
    template: `
    <div class="max-w-md mx-auto bg-white rounded-3xl border border-slate-200 shadow-xl overflow-hidden mt-20">
        <div class="p-8 sm:p-12">
            <div class="text-center mb-8">
                <div class="w-16 h-16 bg-indigo-600 rounded-2xl flex items-center justify-center text-white text-2xl font-bold shadow-lg shadow-indigo-200 mx-auto mb-4">S</div>
                <h2 class="text-2xl font-bold text-slate-900">Welcome Back</h2>
                <p class="text-slate-500 mt-2">Sign in to access your Supernote cloud</p>
            </div>

            <form @submit.prevent="handleSubmit" class="space-y-6">
                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-2">Email Address</label>
                    <input type="email" v-model="email" required
                        class="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 outline-none transition-all"
                        placeholder="you@example.com">
                </div>

                <div>
                    <label class="block text-sm font-medium text-slate-700 mb-2">Password</label>
                    <input type="password" v-model="password" required
                        class="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 outline-none transition-all"
                        placeholder="••••••••">
                </div>

                <button type="submit"
                    :disabled="isLoading"
                    class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-3 px-4 rounded-xl shadow-lg shadow-indigo-200 transition-all transform hover:-translate-y-0.5 disabled:opacity-50 disabled:cursor-not-allowed flex justify-center items-center">
                    <span v-if="isLoading" class="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></span>
                    {{ isLoading ? 'Signing in...' : 'Sign In' }}
                </button>
            </form>
        </div>
        <div class="bg-slate-50 p-4 text-center text-xs text-slate-400 border-t border-slate-100">
            Supernote Private Cloud Server
        </div>
    </div>
    `
}
