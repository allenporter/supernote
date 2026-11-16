import { ref, onMounted, onUnmounted } from 'vue';
import { fetchIcsFeed, downloadIcsFeed } from '../../api/schedule.js';
import { showToast } from '../../composables/useToast.js';
import { copyTextToClipboard } from '../../utils/clipboard.js';
import { getErrorMessage } from '../../utils/format.js';

export default {
    name: 'TaskIcsModal',
    props: {
        taskGroups: {
            type: Array,
            default: () => []
        },
        initialGroupId: {
            type: [String, Number],
            default: null
        }
    },
    emits: ['close'],
    /**
     * @param {{ taskGroups: ScheduleTaskGroup[], initialGroupId: string | number | null }} props
     * @param {{ emit: (event: string, ...args: any[]) => void }} context
     */
    setup(props, { emit }) {
        const icsFilterGroupId = ref(props.initialGroupId ? String(props.initialGroupId) : 'all');
        const icsPreviewContent = ref('');
        const isIcsLoading = ref(false);
        const copySuccess = ref(false);
        /** @type {ReturnType<typeof setTimeout> | null} */
        let copyResetTimer = null;

        async function refreshIcsPreview() {
            isIcsLoading.value = true;
            try {
                const targetGroupId = icsFilterGroupId.value === 'all' ? null : icsFilterGroupId.value;
                icsPreviewContent.value = await fetchIcsFeed(targetGroupId);
            } catch (e) {
                icsPreviewContent.value = `Error loading ICS feed: ${getErrorMessage(e)}`;
            } finally {
                isIcsLoading.value = false;
            }
        }

        async function handleDownloadIcs() {
            try {
                const targetGroupId = icsFilterGroupId.value === 'all' ? null : icsFilterGroupId.value;
                const groupObj = props.taskGroups.find(g => String(g.id) === String(targetGroupId));
                const nameSlug = groupObj ? groupObj.title.toLowerCase().replace(/[^a-z0-9]/g, '_') : 'supernote_tasks';
                await downloadIcsFeed(targetGroupId, `${nameSlug}.ics`);
            } catch (e) {
                showToast(`Failed to download ICS feed: ${getErrorMessage(e)}`);
            }
        }

        async function copyIcsContent() {
            if (!icsPreviewContent.value) return;
            const copied = await copyTextToClipboard(icsPreviewContent.value);
            if (!copied) {
                showToast('Failed to copy to clipboard');
                return;
            }
            copySuccess.value = true;
            if (copyResetTimer) clearTimeout(copyResetTimer);
            copyResetTimer = setTimeout(() => { copySuccess.value = false; }, 2500);
        }

        /**
         * @param {KeyboardEvent} e
         */
        function handleKeydown(e) {
            if (e.key === 'Escape' && !e.defaultPrevented) {
                e.preventDefault();
                e.stopPropagation();
                emit('close');
            }
        }

        onMounted(() => {
            window.addEventListener('keydown', handleKeydown);
            refreshIcsPreview();
        });

        onUnmounted(() => {
            window.removeEventListener('keydown', handleKeydown);
            if (copyResetTimer) clearTimeout(copyResetTimer);
        });

        return {
            icsFilterGroupId,
            icsPreviewContent,
            isIcsLoading,
            copySuccess,
            refreshIcsPreview,
            handleDownloadIcs,
            copyIcsContent
        };
    },
    template: `
    <div role="dialog" aria-modal="true" aria-label="Export iCalendar Feed"
        class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[2px]" @click.self="$emit('close')">
        <div class="bg-white rounded-2xl border border-stone-200 shadow-2xl w-full max-w-xl p-6 space-y-5 animate-fade-in">
            <div class="flex items-center justify-between border-b border-stone-100 pb-3">
                <div class="flex items-center gap-3">
                    <div class="w-9 h-9 bg-stone-100 rounded-xl flex items-center justify-center text-slate-800">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
                        </svg>
                    </div>
                    <div>
                        <h3 class="text-base font-bold text-slate-900">Export iCalendar (.ics) Feed</h3>
                        <p class="text-xs text-stone-500">Download or copy RFC 5545 VTODO task feed</p>
                    </div>
                </div>
                <button @click="$emit('close')" type="button" aria-label="Close ICS modal"
                    class="text-stone-500 hover:text-slate-900 p-1.5 rounded-lg hover:bg-stone-100 transition-colors">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>

            <div class="space-y-4">
                <div>
                    <label class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider mb-1.5">Filter Feed by Task List</label>
                    <select v-model="icsFilterGroupId" @change="refreshIcsPreview" class="w-full px-3.5 py-2 bg-stone-50 border border-stone-200 rounded-xl text-xs font-medium outline-none focus:ring-2 focus:ring-slate-900">
                        <option value="all">All Task Lists (Complete Feed)</option>
                        <option v-for="g in taskGroups" :key="g.id" :value="g.id">{{ g.title }}</option>
                    </select>
                </div>

                <div>
                    <div class="flex items-center justify-between mb-1.5">
                        <label class="block text-[11px] font-bold text-stone-500 uppercase tracking-wider">ICS Content Preview</label>
                        <button @click="copyIcsContent" type="button" class="text-xs font-semibold text-slate-900 hover:text-stone-600 flex items-center gap-1">
                            <span v-if="copySuccess" class="text-emerald-600 flex items-center gap-1">
                                Copied!
                            </span>
                            <span v-else class="flex items-center gap-1">
                                Copy Text
                            </span>
                        </button>
                    </div>
                    <div v-if="isIcsLoading" class="flex justify-center items-center py-12 bg-stone-50 rounded-xl border border-stone-200">
                        <div class="animate-spin rounded-full h-6 w-6 border-2 border-stone-300 border-t-slate-900"></div>
                    </div>
                    <textarea v-else readOnly v-model="icsPreviewContent" rows="8"
                        class="w-full p-3 font-mono text-xs bg-slate-900 text-stone-200 border border-slate-800 rounded-xl outline-none resize-none leading-relaxed"></textarea>
                </div>
            </div>

            <div class="flex items-center justify-between pt-3 border-t border-stone-100">
                <button @click="$emit('close')" type="button" class="px-4 py-2 text-stone-600 hover:text-slate-900 text-xs font-semibold">
                    Close
                </button>
                <div class="flex items-center gap-2.5">
                    <button @click="copyIcsContent" type="button" class="px-4 py-2 bg-stone-100 hover:bg-stone-200 text-slate-800 rounded-xl text-xs font-semibold transition-colors">
                        Copy Content
                    </button>
                    <button @click="handleDownloadIcs" type="button"
                        class="px-5 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-xl text-xs font-semibold transition-all">
                        Download .ics
                    </button>
                </div>
            </div>
        </div>
    </div>
    `
};
