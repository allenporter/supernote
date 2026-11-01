import VocabularySection from './VocabularySection.js';

export default {
    name: 'SettingsView',
    components: { VocabularySection },
    template: `
    <div class="max-w-3xl mx-auto space-y-6">
        <h2 class="text-2xl font-bold text-slate-900 dark:text-slate-100">Settings</h2>

        <VocabularySection />
    </div>
    `
};
