export default {
    name: 'RenameModal',
    props: ['item'],
    template: `
        <div class="fixed inset-0 z-[110] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm" @click.self="$emit('close')">
            <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6 animate-in zoom-in-95">
                <h3 class="text-lg font-bold text-slate-900 mb-4">Rename {{ item.isDirectory ? 'Folder' : 'File' }}</h3>
                <input v-model="newName" type="text" placeholder="New name"
                    class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all mb-6"
                    @keyup.enter="handleRename" ref="nameInput">
                <div class="flex justify-end gap-3">
                    <button @click="$emit('close')" class="px-4 py-2 text-slate-500 hover:text-slate-700 font-medium">Cancel</button>
                    <button @click="handleRename" :disabled="!newName || newName === item.name"
                        class="px-6 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-xl font-bold shadow-lg shadow-indigo-200 transition-all">
                        Rename
                    </button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            newName: this.item.name
        }
    },
    mounted() {
        this.$nextTick(() => {
            this.$refs.nameInput.focus();
            this.$refs.nameInput.select();
        });
    },
    methods: {
        handleRename() {
            if (this.newName && this.newName !== this.item.name) {
                this.$emit('confirm', this.newName);
            }
        }
    }
}
