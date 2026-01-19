import { createApp, ref, onMounted, computed } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { useFileSystem } from './composables/useFileSystem.js';
import { setToken } from './api/client.js';
import FileCard from './components/FileCard.js';

createApp({
    components: {
        FileCard
    },
    setup() {
        // Dev helper: Set token from URL
        const urlParams = new URLSearchParams(window.location.search);
        const token = urlParams.get('token');
        if (token) {
            setToken(token);
        }

        const { files, currentDirectoryId, isLoading, error, loadDirectory } = useFileSystem();

        const view = ref('grid');
        const selectedFile = ref(null);
        const breadcrumbs = ref([{ id: "0", name: "Cloud" }]);

        // Separate folders and files for display
        const folders = computed(() => files.value.filter(f => f.isDirectory));
        const regularFiles = computed(() => files.value.filter(f => !f.isDirectory));

        async function openItem(item) {
            if (item.isDirectory) {
                currentDirectoryId.value = item.id;
                breadcrumbs.value.push({ id: item.id, name: item.name });
                await loadDirectory(item.id);
            } else {
                selectedFile.value = item;
                view.value = 'viewer';
            }
        }

        async function navigateTo(index) {
            const crumbs = breadcrumbs.value.slice(0, index + 1);
            breadcrumbs.value = crumbs;
            const target = crumbs[crumbs.length - 1];
            view.value = 'grid';
            await loadDirectory(target.id);
        }

        onMounted(() => {
            // Initial load
            loadDirectory();
        });

        return {
            view,
            files,
            folders,
            regularFiles,
            currentDirectoryId,
            isLoading,
            error,
            breadcrumbs,
            openItem,
            navigateTo,
            selectedFile
        };
    }
}).mount('#app');
