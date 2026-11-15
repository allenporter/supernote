import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue';

export default {
    name: 'RenameModal',
    props: ['item'],
    emits: ['close', 'confirm'],
    template: `
        <div class="fixed inset-0 z-[110] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px] animate-fade-in" @click.self="$emit('close')">
            <div role="dialog" aria-modal="true" aria-label="Rename Item"
                class="bg-white border border-stone-200 rounded-2xl shadow-2xl w-full max-w-md p-6">
                <h3 class="text-base font-bold text-slate-900 mb-1">Rename {{ item.isDirectory ? 'Folder' : 'File' }}</h3>
                <p class="text-xs text-stone-500 mb-4">Enter a new name for "{{ item.name }}".</p>
                <input v-model="newName" type="text" placeholder="New name"
                    class="w-full px-3.5 py-2.5 bg-stone-50 border border-stone-200 rounded-xl text-sm focus:ring-2 focus:ring-slate-900 focus:border-slate-900 outline-none transition-all mb-5"
                    @keyup.enter="handleRename" ref="nameInput">
                <div class="flex justify-end gap-2.5">
                    <button @click="$emit('close')" type="button" class="px-4 py-2 text-xs text-stone-600 hover:text-slate-900 font-semibold">Cancel</button>
                    <button @click="handleRename" type="button" :disabled="!trimmedName || trimmedName === item.name"
                        class="px-5 py-2 bg-slate-900 hover:bg-slate-800 disabled:opacity-40 text-white rounded-xl text-xs font-semibold transition-all">
                        Rename
                    </button>
                </div>
            </div>
        </div>
    `,
    setup(props, { emit }) {
        const newName = ref(props.item ? props.item.name : '');
        const nameInput = ref(null);

        const trimmedName = computed(() => (newName.value || '').trim());

        const handleKeydown = (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                emit('close');
            }
        };

        const handleRename = () => {
            if (trimmedName.value && trimmedName.value !== props.item.name) {
                emit('confirm', trimmedName.value);
            }
        };

        onMounted(() => {
            window.addEventListener('keydown', handleKeydown);
            nextTick(() => {
                if (nameInput.value) {
                    nameInput.value.focus();
                    nameInput.value.select();
                }
            });
        });

        onUnmounted(() => {
            window.removeEventListener('keydown', handleKeydown);
        });

        return {
            newName,
            nameInput,
            trimmedName,
            handleRename
        };
    }
};
