import { onMounted, ref, watch } from 'vue';
import { renderMermaidSvg } from '../../utils/mermaid.js';

export default {
    name: 'MermaidBlock',
    props: {
        code: { type: String, required: true },
    },
    /**
     * @param {{ code: string }} props
     */
    setup(props) {
        /** @type {import('vue').Ref<string>} */
        const svgHtml = ref('');
        /** @type {import('vue').Ref<boolean>} */
        const renderFailed = ref(false);
        /** @type {import('vue').Ref<boolean>} */
        const showSource = ref(false);
        /** @type {import('vue').Ref<boolean>} */
        const isRendering = ref(false);
        let renderSeq = 0;

        async function renderDiagram() {
            const currentSeq = ++renderSeq;
            isRendering.value = true;
            renderFailed.value = false;
            const result = await renderMermaidSvg(props.code);
            if (currentSeq !== renderSeq) return;
            isRendering.value = false;
            if (result.ok) {
                svgHtml.value = result.svg;
                renderFailed.value = false;
            } else {
                svgHtml.value = '';
                renderFailed.value = true;
            }
        }

        onMounted(() => {
            renderDiagram();
        });

        watch(
            () => props.code,
            () => {
                showSource.value = false;
                renderDiagram();
            },
        );

        return {
            svgHtml,
            renderFailed,
            showSource,
            isRendering,
        };
    },
    template: `
        <div class="my-2 rounded-lg border border-stone-200/90 bg-white overflow-hidden" data-mermaid-block>
            <div class="px-2.5 py-1 bg-stone-50 border-b border-stone-200/70 flex items-center justify-between gap-2">
                <div class="flex items-center gap-1.5 min-w-0">
                    <span class="text-[10px] font-mono font-semibold uppercase tracking-wider text-stone-500">Mermaid</span>
                    <span v-if="renderFailed" class="text-[10px] font-sans text-amber-700 truncate">Source fallback</span>
                </div>
                <button v-if="svgHtml && !renderFailed"
                    type="button"
                    @click="showSource = !showSource"
                    class="text-[10px] font-sans font-medium text-stone-500 hover:text-slate-900 px-1.5 py-0.5 rounded hover:bg-stone-200/60 transition-colors cursor-pointer">
                    {{ showSource ? 'Diagram' : 'Code' }}
                </button>
            </div>
            <div v-if="svgHtml && !showSource"
                class="mermaid-svg-container p-2.5 overflow-x-auto bg-white"
                data-mermaid-svg
                v-html="svgHtml">
            </div>
            <pre v-else
                class="p-2.5 font-mono text-[11px] text-slate-700 whitespace-pre-wrap overflow-x-auto leading-relaxed select-text bg-stone-50/40"
                data-mermaid-source>{{ code }}</pre>
        </div>
    `,
};
