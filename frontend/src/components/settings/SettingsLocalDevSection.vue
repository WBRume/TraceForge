<!-- Multi-repository local dev settings: per-repo local path bindings. -->
<script setup lang="ts">
import { computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { GitBranch, Info } from 'lucide-vue-next'
import { useWorkspaceStore } from '@/stores/workspace'
import { useLocalAgentStore } from '@/stores/localAgent'
import RepoMappingRow from '@/components/local-agent/RepoMappingRow.vue'

const wsStore = useWorkspaceStore()
const localAgent = useLocalAgentStore()
const { t } = useI18n()
const { electronAvailable, expectedRemoteUrls } = storeToRefs(localAgent)

const modeLabel = computed(() => (
  electronAvailable.value
    ? t('settings.local_dev.mode_electron')
    : t('settings.local_dev.mode_web')
))

type RepoRow = { remoteUrl: string; repoName: string }

const repoRows = computed<RepoRow[]>(() => {
  const repos: { repo_url?: string; repo_name?: string }[] = Array.isArray(wsStore.currentWorkspace?.repositories)
    ? wsStore.currentWorkspace.repositories
    : []
  if (repos.length > 0) {
    return repos
      .filter((item) => Boolean(item.repo_url))
      .map((item) => ({
        remoteUrl: String(item.repo_url),
        repoName: String(item.repo_name || item.repo_url),
      }))
  }
  const legacy = String(wsStore.currentWorkspace?.git_repo_url || '').trim()
  if (!legacy) return []
  return [{ remoteUrl: legacy, repoName: wsStore.currentWorkspace?.name || legacy }]
})

const hydrate = async () => {
  await localAgent.loadLocalConfig()
  await localAgent.syncCurrentAuthToConfig()
  await localAgent.setWorkspaceContext(wsStore.currentWorkspace)
}

const handleChanged = () => {
  void hydrate()
}

watch(
  () => [wsStore.currentWorkspace?.id, wsStore.currentWorkspace?.git_repo_url],
  () => {
    void hydrate()
  },
  { immediate: true },
)
</script>

<template>
  <div class="local-dev-settings">
    <section class="settings-card glass-panel animate-pop-in">
      <div class="section-title-row">
        <div class="flex items-start gap-4">
          <div class="icon-wrapper">
            <GitBranch class="w-6 h-6" />
          </div>
          <div>
            <h2 class="title-gradient-small">{{ t('settings.local_dev.repo_mapping_title') }}</h2>
            <p class="subtitle">{{ t('settings.local_dev.repo_mapping_desc') }}</p>
          </div>
        </div>
        <span class="mode-pill" :class="{ active: electronAvailable }">{{ modeLabel }}</span>
      </div>

      <div v-if="!expectedRemoteUrls.length" class="warning-box mt-4">
        <Info class="w-4 h-4 flex-shrink-0" />
        <span>{{ t('settings.local_dev.no_workspace_remote') }}</span>
      </div>

      <div v-else class="rows-area mt-6">
        <div class="rows-title">
          {{ t('settings.local_dev.multi_repo_title', { count: repoRows.length }) }} · {{ t('settings.local_dev.repo_row_hint') }}
        </div>
        <div class="rows-list">
          <RepoMappingRow
            v-for="row in repoRows"
            :key="row.remoteUrl"
            :remote-url="row.remoteUrl"
            :repo-name="row.repoName"
            @changed="handleChanged"
          />
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.local-dev-settings {
  display: flex;
  flex-direction: column;
  padding-bottom: 2rem;
}

.settings-card {
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 16px;
  padding: 1.75rem;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(12px);
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.05);
}

.section-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.title-gradient-small {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 800;
  background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  color: #64748b;
  font-size: 0.9rem;
  margin-top: 0.4rem;
  line-height: 1.5;
}

.icon-wrapper {
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.1), rgba(59, 130, 246, 0.1));
  padding: 0.65rem;
  border-radius: 12px;
  color: #0ea5e9;
  border: 1px solid rgba(14, 165, 233, 0.2);
  flex-shrink: 0;
}

.mode-pill {
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  padding: 0.35rem 0.75rem;
  color: #64748b;
  font-size: 0.8rem;
  font-weight: 700;
  white-space: nowrap;
  background: #f8fafc;
}

.mode-pill.active {
  border-color: rgba(16, 185, 129, 0.4);
  color: #047857;
  background: #ecfdf5;
}

.warning-box {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  background: #fff7ed;
  color: #9a3412;
  font-size: 0.875rem;
  font-weight: 500;
  line-height: 1.5;
}

.rows-area {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.rows-title {
  font-size: 0.82rem;
  font-weight: 700;
  color: #334155;
}

.rows-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.flex { display: flex; }
.items-start { align-items: flex-start; }
.items-center { align-items: center; }
.gap-4 { gap: 1rem; }
.mt-4 { margin-top: 1rem; }
.mt-6 { margin-top: 1.5rem; }
.flex-shrink-0 { flex-shrink: 0; }

@keyframes popIn {
  from { opacity: 0; transform: scale(0.95) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.animate-pop-in {
  animation: popIn 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}
</style>
