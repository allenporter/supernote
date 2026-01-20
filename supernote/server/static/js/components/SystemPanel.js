import { fetchSystemTasks, fetchCapacity } from '../api/client.js';

export default {
    name: 'SystemPanel',
    template: `
        <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" @click.self="$emit('close')">
            <div class="bg-white rounded-lg shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
                <!-- Header -->
                <div class="flex items-center justify-between p-4 border-b">
                    <h2 class="text-xl font-bold text-gray-800">System Status</h2>
                    <button @click="$emit('close')" class="text-gray-500 hover:text-gray-700">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <!-- Content -->
                <div class="flex-1 overflow-y-auto p-4 space-y-6">
                    <!-- Storage Quota -->
                    <div class="bg-gray-50 p-4 rounded-lg">
                        <h3 class="text-lg font-medium text-gray-900 mb-2">Storage Usage</h3>
                        <div v-if="capacity" class="space-y-2">
                            <div class="flex justify-between text-sm text-gray-600">
                                <span>{{ formatSize(capacity.usedCapacity) }} used</span>
                                <span>{{ formatSize(capacity.totalCapacity) }} total</span>
                            </div>
                            <div class="w-full bg-gray-200 rounded-full h-2.5">
                                <div class="bg-primary-600 h-2.5 rounded-full transition-all duration-500" :style="{ width: usagePercent + '%' }"></div>
                            </div>
                        </div>
                        <div v-else class="animate-pulse bg-gray-200 h-10 rounded"></div>
                    </div>

                    <!-- Tasks -->
                    <div>
                        <h3 class="text-lg font-medium text-gray-900 mb-4">Processing Queue</h3>
                        <div v-if="loading" class="flex justify-center p-8">
                            <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
                        </div>

                        <div v-else-if="error" class="p-4 bg-red-50 text-red-700 rounded-lg">
                            {{ error }}
                        </div>

                        <div v-else class="overflow-x-auto border rounded-lg">
                            <table class="min-w-full divide-y divide-gray-200">
                                <thead class="bg-gray-50">
                                    <tr>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">File ID</th>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Type</th>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Key</th>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Retries</th>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Updated</th>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Details</th>
                                    </tr>
                                </thead>
                                <tbody class="bg-white divide-y divide-gray-200">
                                    <tr v-for="task in tasks" :key="task.id">
                                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{{ task.fileId }}</td>
                                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{{ task.taskType }}</td>
                                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ task.key }}</td>
                                        <td class="px-6 py-4 whitespace-nowrap">
                                            <span :class="statusClass(task.status)" class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full">
                                                {{ task.status }}
                                            </span>
                                        </td>
                                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ task.retryCount }}</td>
                                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{{ formatDate(task.updateTime) }}</td>
                                        <td class="px-6 py-4 text-sm text-red-600 max-w-xs truncate" :title="task.lastError">
                                            {{ task.lastError }}
                                        </td>
                                    </tr>
                                    <tr v-if="tasks.length === 0">
                                        <td colspan="7" class="px-6 py-4 text-center text-sm text-gray-500">No active tasks</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- Footer -->
                <div class="p-4 border-t bg-gray-50 flex justify-end">
                    <button @click="loadData" class="mr-2 px-4 py-2 bg-white border border-gray-300 rounded shadow-sm text-sm font-medium text-gray-700 hover:bg-gray-50">
                        Refresh
                    </button>
                    <button @click="$emit('close')" class="px-4 py-2 bg-primary-600 border border-transparent rounded shadow-sm text-sm font-medium text-white hover:bg-primary-700">
                        Close
                    </button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            loading: true,
            error: null,
            tasks: [],
            capacity: null
        }
    },
    computed: {
        usagePercent() {
            if (!this.capacity || this.capacity.totalCapacity === 0) return 0;
            return Math.min(100, (this.capacity.usedCapacity / this.capacity.totalCapacity) * 100);
        }
    },
    async mounted() {
        await this.loadData();
    },
    methods: {
        async loadData() {
            this.loading = true;
            this.error = null;
            try {
                const [tasksResult, capacityResult] = await Promise.all([
                    fetchSystemTasks(),
                    fetchCapacity()
                ]);

                if (tasksResult.success) {
                    this.tasks = tasksResult.tasks;
                } else {
                    this.error = "Failed to load tasks";
                }

                // Capacity result is the VO directly, typically
                this.capacity = capacityResult;
            } catch (e) {
                this.error = e.message;
            } finally {
                this.loading = false;
            }
        },
        statusClass(status) {
            const classes = {
                'PENDING': 'bg-yellow-100 text-yellow-800',
                'PROCESSING': 'bg-blue-100 text-blue-800',
                'COMPLETED': 'bg-green-100 text-green-800',
                'FAILED': 'bg-red-100 text-red-800'
            };
            return classes[status] || 'bg-gray-100 text-gray-800';
        },
        formatDate(timestamp) {
            if (!timestamp) return '-';
            return new Date(timestamp).toLocaleString();
        },
        formatSize(bytes) {
            if (!bytes) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
    }
}
