import { createApp, ref, onMounted, computed } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.js';
import { useFileSystem } from './composables/useFileSystem.js';
import { setToken, getToken, login, logout } from './api/client.js';
import FileCard from './components/FileCard.js';
import LoginCard from './components/LoginCard.js';
import FileViewer from './components/FileViewer.js';
import SystemPanel from './components/SystemPanel.js';

createApp({
    components: {
        FileCard,
        LoginCard,
        FileViewer,
        SystemPanel
    },
    setup() {
        // Auth State
        const isLoggedIn = ref(false);
        const loginError = ref(null);
        const showSystemPanel = ref(false);

        // Dev helper: Set token from URL
        const urlParams = new URLSearchParams(window.location.search);
        const token = urlParams.get('token');
        if (token) {
            setToken(token);
            // Clean URL
            window.history.replaceState({}, document.title, "/");
        }

        const { files, currentDirectoryId, isLoading, error, loadDirectory } = useFileSystem();

        const view = ref('grid');
        const selectedFile = ref(null);
        const breadcrumbs = ref([{ id: "0", name: "Cloud" }]);

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

        async function handleLogin({ email, password }) {
            loginError.value = null;
            try {
                await login(email, password);
                isLoggedIn.value = true;
                await loadDirectory();
            } catch (e) {
                loginError.value = e.message;
                alert(e.message); // Simple feedback for now
            }
        }

        function handleLogout() {
            logout();
        }

        onMounted(() => {
            if (getToken()) {
                isLoggedIn.value = true;
                loadDirectory();
            }
        });

        return {
            isLoggedIn,
            handleLogin,
            handleLogout,
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
            selectedFile,
            showSystemPanel
        };
    }
}).mount('#app');
