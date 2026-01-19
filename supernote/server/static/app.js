const { createApp, ref, onMounted } = Vue;

createApp({
    setup() {
        const view = ref('grid');
        const selectedFile = ref(null);
        const folders = ref([]);
        const files = ref([]);
        const isLoading = ref(false);
        const error = ref(null);

        // Current navigation state
        const currentDirectoryId = ref("0");
        const breadcrumbs = ref([{ id: "0", name: "Cloud" }]);

        async function fetchFileList(directoryId = "0") {
            isLoading.value = true;
            error.value = null;
            try {
                // This will be wired to /api/file/list/query
                // For now, we use mock data to ensure UI stability
                setTimeout(() => {
                    folders.value = [
                        { id: "1", name: 'Archive 2024', count: 42 },
                        { id: "2", name: 'System Logs', count: 5 },
                    ];
                    files.value = [
                        { id: "101", name: 'Q1 Strategy Brainstorm.note', size: '2.4 MB', date: '2h ago', type: 'note' },
                        { id: "102", name: 'Design Specs V2.pdf', size: '12.1 MB', date: 'Yesterday', type: 'pdf' },
                    ];
                    isLoading.value = false;
                }, 500);
            } catch (e) {
                error.value = "Failed to load files";
                isLoading.value = false;
            }
        }

        function openFile(file) {
            selectedFile.value = file;
            view.value = 'viewer';
        }

        function openFolder(folder) {
            currentDirectoryId.value = folder.id;
            breadcrumbs.value.push({ id: folder.id, name: folder.name });
            fetchFileList(folder.id);
        }

        function navigateTo(index) {
            const crumbs = breadcrumbs.value.slice(0, index + 1);
            breadcrumbs.value = crumbs;
            const target = crumbs[crumbs.length - 1];
            currentDirectoryId.value = target.id;
            view.value = 'grid';
            fetchFileList(target.id);
        }

        onMounted(() => {
            fetchFileList();
        });

        return {
            view,
            selectedFile,
            folders,
            files,
            isLoading,
            error,
            breadcrumbs,
            openFile,
            openFolder,
            navigateTo
        };
    }
}).mount('#app');
