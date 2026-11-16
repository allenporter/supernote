import { computed, nextTick, onMounted, ref } from 'vue';
import { useModalEscape } from '../composables/useModalEscape.js';

export default {
    name: 'RenameModal',
    props: {
        item: {
            type: Object,
            default: null,
        },
        isSubmitting: {
            type: Boolean,
            default: false,
        },
    },
    emits: ['close', 'confirm'],
    template: `
        <div class="fixed inset-0 z-[110] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px] animate-fade-in" @click.self="!isSubmitting && $emit('close')">
            <form @submit.prevent="handleRename" role="dialog" aria-modal="true" aria-label="Rename Item"
                class="bg-white border border-stone-200 rounded-2xl shadow-2xl w-full max-w-md p-6">
                <h3 class="text-base font-bold text-slate-900 mb-1">Rename {{ item?.isDirectory ? 'Folder' : 'File' }}</h3>
                <p class="text-xs text-stone-500 mb-4">Enter a new name for "{{ item?.name }}".</p>
                <input id="rename-item-input" v-model="newName" type="text" placeholder="New name" aria-label="New name"
                    :disabled="isSubmitting"
                    class="w-full px-3.5 py-2.5 bg-stone-50 border border-stone-200 rounded-xl text-sm focus:ring-2 focus:ring-slate-900 focus:border-slate-900 outline-none transition-all mb-5 disabled:opacity-60"
                    ref="nameInput">
                <div class="flex justify-end gap-2.5">
                    <button @click="$emit('close')" :disabled="isSubmitting" type="button" class="px-4 py-2 text-xs text-stone-600 hover:text-slate-900 font-semibold disabled:opacity-40">Cancel</button>
                    <button type="submit" :disabled="isSubmitting || !trimmedName || trimmedName === item?.name"
                        class="px-5 py-2 bg-slate-900 hover:bg-slate-800 disabled:opacity-40 text-white rounded-xl text-xs font-semibold transition-all">
                        {{ isSubmitting ? 'Renaming...' : 'Rename' }}
                    </button>
                </div>
            </form>
        </div>
    `,
    /**
     * @param {{ item?: FileItem | null, isSubmitting?: boolean }} props
     * @param {{ emit: (event: string, ...args: any[]) => void }} context
     */
    setup(props, { emit }) {
        const newName = ref(props.item ? props.item.name : '');
        /** @type {import('vue').Ref<HTMLInputElement | null>} */
        const nameInput = ref(null);

        const trimmedName = computed(() => (newName.value || '').trim());

        useModalEscape(() => {
            if (!props.isSubmitting) emit('close');
        });

        const handleRename = () => {
            if (props.isSubmitting) return;
            if (trimmedName.value && trimmedName.value !== props.item?.name) {
                emit('confirm', trimmedName.value);
            }
        };

        onMounted(() => {
            nextTick(() => {
                if (nameInput.value) {
                    nameInput.value.focus();
                    nameInput.value.select();
                }
            });
        });

        return {
            newName,
            nameInput,
            trimmedName,
            handleRename,
        };
    },
};
