import { ref, computed, onMounted } from 'vue';
import {
    fetchVocabulary, addVocabulary, moveVocabulary, deleteVocabulary, restoreVocabulary, fetchFiles
} from '../api/client.js';

const EVERYWHERE = { id: '0', path: '' };
const LAST_SEEN_KEY = 'vocabulary.lastSeen';

const FILTERS = [
    { id: 'all', label: 'All' },
    { id: 'new', label: 'New' },
    { id: 'harvest', label: 'From keywords' },
    { id: 'manual', label: 'Added by you' },
    { id: 'removed', label: 'Removed' },
];

const scopeLabel = (path) => path || 'All notebooks';

function readLastSeen() {
    try {
        return Number(localStorage.getItem(LAST_SEEN_KEY)) || 0;
    } catch {
        return 0;
    }
}

function writeLastSeen(time) {
    try {
        localStorage.setItem(LAST_SEEN_KEY, String(time));
    } catch {
        // Private windows may refuse storage; "new" then means "this visit".
    }
}

// Folders a term can be applied to without browsing: those under Note/.
async function fetchNoteFolders() {
    const root = await fetchFiles('0');
    const note = root.find(f => f.isDirectory && f.name === 'Note');
    if (!note) return [];
    const children = await fetchFiles(String(note.id));
    return children
        .filter(f => f.isDirectory)
        .map(f => ({ id: String(f.id), path: `Note/${f.name}` }));
}

export default {
    name: 'VocabularySection',
    setup() {
        const terms = ref([]);
        const folders = ref([]);
        const error = ref(null);
        const busy = ref(false);
        const filter = ref('all');
        const query = ref('');
        const selected = ref([]);
        const bulkScope = ref('');
        const isAddOpen = ref(false);
        const addText = ref('');
        const addScope = ref('0');
        const lastSeen = readLastSeen();

        const load = async () => {
            try {
                terms.value = (await fetchVocabulary()).terms;
            } catch (e) {
                error.value = e.message;
            }
        };

        const isNew = (t) => !t.isSuppressed && t.createTime > lastSeen;

        const counts = computed(() => ({
            all: terms.value.filter(t => !t.isSuppressed).length,
            new: terms.value.filter(isNew).length,
            harvest: terms.value.filter(t => !t.isSuppressed && t.source === 'harvest').length,
            manual: terms.value.filter(t => !t.isSuppressed && t.source === 'manual').length,
            removed: terms.value.filter(t => t.isSuppressed).length,
        }));

        const visible = computed(() => {
            const q = query.value.trim().toLowerCase();
            return terms.value.filter(t => {
                if (q && !t.term.toLowerCase().includes(q)) return false;
                switch (filter.value) {
                    case 'removed': return t.isSuppressed;
                    case 'new': return isNew(t);
                    case 'harvest': return !t.isSuppressed && t.source === 'harvest';
                    case 'manual': return !t.isSuppressed && t.source === 'manual';
                    default: return !t.isSuppressed;
                }
            });
        });

        const groups = computed(() => {
            const byScope = new Map();
            for (const t of visible.value) {
                if (!byScope.has(t.scopeId)) byScope.set(t.scopeId, { scopeId: t.scopeId, path: t.scopePath, terms: [] });
                byScope.get(t.scopeId).terms.push(t);
            }
            return [...byScope.values()].sort((a, b) => a.path.localeCompare(b.path));
        });

        // Every place a term can go: everywhere, the folders under Note/, and
        // any narrower scope a term already uses.
        const scopes = computed(() => {
            const all = new Map([[EVERYWHERE.id, EVERYWHERE]]);
            for (const f of folders.value) all.set(f.id, f);
            for (const t of terms.value) {
                if (!all.has(t.scopeId)) all.set(t.scopeId, { id: t.scopeId, path: t.scopePath });
            }
            return [...all.values()].sort((a, b) => a.path.localeCompare(b.path));
        });

        const run = async (action) => {
            busy.value = true;
            error.value = null;
            try {
                await action();
                selected.value = [];
                await load();
            } catch (e) {
                error.value = e.message;
            } finally {
                busy.value = false;
            }
        };

        const add = () => run(async () => {
            const words = addText.value.split(/[\n,]/).map(w => w.trim()).filter(Boolean);
            if (!words.length) return;
            await addVocabulary(words, addScope.value);
            addText.value = '';
            isAddOpen.value = false;
        });

        const move = (term, scopeId) => run(() => moveVocabulary(term.id, scopeId));
        const remove = (term) => run(() => deleteVocabulary(term.id));
        const restore = (term) => run(() => restoreVocabulary(term.id));

        const removeSelected = () => {
            if (!confirm(`Remove ${selected.value.length} term(s)? Terms from keywords will not be added again.`)) return;
            return run(async () => {
                for (const id of selected.value) await deleteVocabulary(id);
            });
        };

        const moveSelected = () => {
            if (!bulkScope.value) return;
            return run(async () => {
                for (const id of selected.value) await moveVocabulary(id, bulkScope.value);
                bulkScope.value = '';
            });
        };

        const toggle = (term) => {
            selected.value = selected.value.includes(term.id)
                ? selected.value.filter(id => id !== term.id)
                : [...selected.value, term.id];
        };

        const setFilter = (id) => {
            filter.value = id;
            selected.value = [];
        };

        onMounted(async () => {
            writeLastSeen(Date.now());
            await load();
            try {
                folders.value = await fetchNoteFolders();
            } catch {
                // Moving is still possible to scopes already in use.
            }
        });

        return {
            FILTERS, terms, error, busy, filter, query, selected, bulkScope, isAddOpen, addText, addScope,
            counts, groups, scopes, isNew, scopeLabel,
            add, move, remove, restore, removeSelected, moveSelected, toggle, setFilter
        };
    },
    template: `
    <section class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 space-y-4">
        <div class="flex items-start justify-between gap-3">
            <div>
                <h3 class="text-base font-bold text-slate-800 dark:text-slate-100">Vocabulary</h3>
                <p class="text-sm text-slate-500">Names and terms that transcription should spell your way. Keywords you add on the device are collected here automatically; remove any that are not spellings.</p>
            </div>
            <button @click="isAddOpen = !isAddOpen" class="flex-none rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1.5 text-sm font-medium">Add terms</button>
        </div>

        <form v-if="isAddOpen" @submit.prevent="add" class="rounded-xl bg-slate-50 dark:bg-slate-800/60 p-3 space-y-2">
            <textarea v-model="addText" rows="2" placeholder="One per line, or separated by commas"
                class="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm"></textarea>
            <div class="flex flex-wrap items-center gap-2">
                <label class="text-sm text-slate-500">Use in</label>
                <select v-model="addScope" class="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-sm">
                    <option v-for="s in scopes" :key="s.id" :value="s.id">{{ scopeLabel(s.path) }}</option>
                </select>
                <button type="submit" :disabled="busy || !addText.trim()" class="ml-auto rounded-lg bg-indigo-600 disabled:opacity-50 text-white px-3 py-1.5 text-sm font-medium">Add</button>
            </div>
        </form>

        <div class="flex flex-wrap items-center gap-2">
            <button v-for="f in FILTERS" :key="f.id" @click="setFilter(f.id)"
                :class="filter === f.id ? 'bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800' : 'text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700'"
                class="rounded-full border px-3 py-1 text-xs font-medium">
                {{ f.label }} <span class="text-slate-400">{{ counts[f.id] }}</span>
            </button>
            <input v-model="query" type="search" placeholder="Filter"
                class="w-full sm:w-36 sm:ml-auto rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1 text-sm">
        </div>

        <div v-if="error" class="text-sm text-amber-700">{{ error }}</div>

        <div v-if="selected.length" class="flex flex-wrap items-center gap-2 rounded-xl bg-indigo-50 dark:bg-indigo-950/60 px-3 py-2 text-sm">
            <span class="font-medium text-indigo-800 dark:text-indigo-200">{{ selected.length }} selected</span>
            <select v-model="bulkScope" class="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1 text-sm">
                <option value="" disabled>Use in…</option>
                <option v-for="s in scopes" :key="s.id" :value="s.id">{{ scopeLabel(s.path) }}</option>
            </select>
            <button @click="moveSelected" :disabled="busy || !bulkScope" class="rounded-lg border border-slate-200 dark:border-slate-700 px-2.5 py-1 font-medium disabled:opacity-50">Move</button>
            <button @click="removeSelected" :disabled="busy" class="ml-auto rounded-lg border border-red-200 text-red-600 hover:bg-red-50 px-2.5 py-1 font-medium">Remove</button>
        </div>

        <p v-if="!groups.length" class="text-sm text-slate-400">
            {{ terms.length ? 'Nothing matches.' : 'No terms yet. Add keywords to notebooks on your device, or add terms here.' }}
        </p>

        <div v-for="group in groups" :key="group.scopeId" class="space-y-1">
            <h4 class="text-xs font-semibold uppercase tracking-wide text-slate-400">
                {{ scopeLabel(group.path) }} <span class="font-normal normal-case">· {{ group.terms.length }}</span>
            </h4>
            <ul class="divide-y divide-slate-100 dark:divide-slate-800">
                <li v-for="t in group.terms" :key="t.id" class="flex flex-wrap sm:flex-nowrap items-center gap-x-3 gap-y-1.5 py-2">
                    <input v-if="!t.isSuppressed" type="checkbox" :checked="selected.includes(t.id)" @change="toggle(t)"
                        class="rounded border-slate-300 text-indigo-600">
                    <div class="min-w-0 flex-1">
                        <p class="flex items-center gap-1.5 text-sm font-medium text-slate-800 dark:text-slate-100">
                            <span class="truncate">{{ t.term }}</span>
                            <span v-if="isNew(t)" class="flex-none rounded bg-emerald-100 dark:bg-emerald-900 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-emerald-700 dark:text-emerald-300">New</span>
                        </p>
                        <p class="text-xs text-slate-500 truncate">
                            <template v-if="t.source === 'harvest'">From a keyword in {{ t.originName || 'a deleted notebook' }}</template>
                            <template v-else>Added by you</template>
                        </p>
                    </div>
                    <div class="flex w-full sm:w-auto items-center justify-end gap-2" :class="t.isSuppressed ? '' : 'pl-7 sm:pl-0'">
                        <template v-if="t.isSuppressed">
                            <button @click="restore(t)" :disabled="busy" class="rounded-lg border border-slate-200 dark:border-slate-700 px-2.5 py-1 text-xs font-medium">Restore</button>
                        </template>
                        <template v-else>
                            <select :value="t.scopeId" @change="move(t, $event.target.value)" :disabled="busy" title="Where this term is used"
                                class="min-w-0 flex-1 sm:flex-none sm:max-w-[10rem] rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1 text-xs">
                                <option v-for="s in scopes" :key="s.id" :value="s.id">{{ scopeLabel(s.path) }}</option>
                            </select>
                            <button @click="remove(t)" :disabled="busy" class="flex-none rounded-lg border border-red-200 text-red-600 hover:bg-red-50 px-2.5 py-1 text-xs font-medium">Remove</button>
                        </template>
                    </div>
                </li>
            </ul>
        </div>
    </section>
    `
};
