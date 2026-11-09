import { ref } from 'vue';
import { getServerPlugins, fetchWithAuth } from '../api/client.js';
import { showToast as defaultShowToast } from './useToast.js';

export function usePlugins() {
    const pluginNavTabs = ref([]);
    const pluginFileToolbarActions = ref([]);
    const pluginFileViewerActions = ref([]);
    const pluginTabProps = ref({});

    let currentHostCallbacks = null;

    function registerNavTab(tabDef) {
        if (!tabDef || !tabDef.id) return;
        const idx = pluginNavTabs.value.findIndex(t => t.id === tabDef.id);
        if (idx >= 0) {
            pluginNavTabs.value[idx] = tabDef;
        } else {
            pluginNavTabs.value.push(tabDef);
        }
    }

    function registerFileToolbarAction(actionDef) {
        if (!actionDef || !actionDef.id) return;
        const idx = pluginFileToolbarActions.value.findIndex(a => a.id === actionDef.id);
        if (idx >= 0) {
            pluginFileToolbarActions.value[idx] = actionDef;
        } else {
            pluginFileToolbarActions.value.push(actionDef);
        }
    }

    function registerFileViewerAction(actionDef) {
        if (!actionDef || !actionDef.id) return;
        const idx = pluginFileViewerActions.value.findIndex(a => a.id === actionDef.id);
        if (idx >= 0) {
            pluginFileViewerActions.value[idx] = actionDef;
        } else {
            pluginFileViewerActions.value.push(actionDef);
        }
    }

    const hostApi = {
        async fetchJson(url, options = {}) {
            const resp = await fetchWithAuth(url, options);
            if (!resp.ok) {
                let errorMsg = `HTTP ${resp.status}`;
                try {
                    const data = await resp.json();
                    errorMsg = data.message || data.error || errorMsg;
                } catch {
                    // Ignore JSON parse error on non-JSON payloads
                }
                throw new Error(errorMsg);
            }
            return await resp.json();
        },

        showToast(msg, type = 'error') {
            if (currentHostCallbacks && typeof currentHostCallbacks.showToast === 'function') {
                return currentHostCallbacks.showToast(msg, type);
            }
            return defaultShowToast(msg, type);
        },

        openTab(tabId, props = {}) {
            pluginTabProps.value[tabId] = props || {};
            if (currentHostCallbacks && typeof currentHostCallbacks.switchTab === 'function') {
                currentHostCallbacks.switchTab(tabId);
            }
        },

        async openFileByPath(storagePath) {
            if (currentHostCallbacks && typeof currentHostCallbacks.openFileByPath === 'function') {
                return await currentHostCallbacks.openFileByPath(storagePath);
            }
        },

        async refreshFiles() {
            if (currentHostCallbacks && typeof currentHostCallbacks.refreshFiles === 'function') {
                return await currentHostCallbacks.refreshFiles();
            }
        },

        getCurrentFolderPath() {
            if (currentHostCallbacks && typeof currentHostCallbacks.getCurrentFolderPath === 'function') {
                return currentHostCallbacks.getCurrentFolderPath();
            }
            return '/';
        },

        registerNavTab,
        registerFileToolbarAction,
        registerFileViewerAction
    };

    async function loadPlugins(hostCallbacks = {}) {
        currentHostCallbacks = hostCallbacks;
        const plugins = await getServerPlugins();

        for (const plugin of plugins) {
            if (plugin.uiModuleUrl) {
                try {
                    const mod = await import(plugin.uiModuleUrl);
                    if (mod && typeof mod.register === 'function') {
                        await mod.register(hostApi);
                    }
                } catch (err) {
                    console.error(`Failed to load UI plugin ${plugin.id}:`, err);
                }
            }
        }
    }

    return {
        pluginNavTabs,
        pluginFileToolbarActions,
        pluginFileViewerActions,
        pluginTabProps,
        pluginHostApi: hostApi,
        loadPlugins
    };
}
