<!-- Multi-repository local mapping onboarding dialog. -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { GitBranch } from 'lucide-vue-next'
import { useLocalAgentStore } from '@/stores/localAgent'
import LocalServiceForm from '@/components/local-resource/LocalServiceForm.vue'
import RepoMappingRow from './RepoMappingRow.vue'

type WorkspaceLike = {
  id?: string
  name?: string | null
  git_repo_url?: string | null
  repositories?: { id?: string; repo_url?: string; repo_name?: string }[]
}

const props = defineProps<{
  show: boolean
  workspace: WorkspaceLike | null
}>()

const emit = defineEmits<{
  close: []
  skip: []
  saved: []
}>()

const localAgent = useLocalAgentStore()
const step = ref(0)

const repoRows = computed(() => {
  const repos = Array.isArray(props.workspace?.repositories) ? props.workspace.repositories : []
  if (repos.length > 0) {
    return repos
      .filter((item) => Boolean(item.repo_url))
      .map((item) => ({
        remoteUrl: String(item.repo_url),
        repoName: String(item.repo_name || item.repo_url),
      }))
  }
  const legacy = String(props.workspace?.git_repo_url || '').trim()
  if (!legacy) return []
  return [{ remoteUrl: legacy, repoName: props.workspace?.name || legacy }]
})

const boundCount = computed(() => (
  repoRows.value.filter((row) => Boolean(localAgent.mappingFor(row.remoteUrl)?.localPath)).length
))

const hydrate = async () => {
  if (!props.show) return
  step.value = 0
  await localAgent.loadLocalConfig()
  await localAgent.setWorkspaceContext(props.workspace)
}

watch(
  () => [props.show, props.workspace?.id, props.workspace?.git_repo_url],
  (shown) => {
    if (shown[0]) void hydrate()
  },
  { immediate: true },
)
</script>

<template>
  <div
    v-if="show"
    class="repo-setup-overlay animate-fade-in"
    @pointerdown.self="emit('close')"
  >
    <section class="repo-setup-dialog glass-panel animate-pop-in" role="dialog" aria-modal="true">
      <header class="dialog-header">
        <div class="icon-wrapper">
          <GitBranch class="w-6 h-6" />
        </div>
        <div>
          <h2 class="title-gradient-small">{{ ['本地开发配置', '本地仓库映射', '本地服务地址'][step] }}</h2>
          <p class="subtitle">
            {{ workspace?.name || '当前工作区' }} 包含 {{ repoRows.length }} 个仓库，为每个仓库绑定本机路径以启用本地开发与代码应用能力。
          </p>
        </div>
      </header>

      <div v-if="step === 0" class="rows-area mt-6">
        <p>本地仓库映射用于检查个人 fork 仓库并应用变更；本地服务配置用于让任务在你的开发机器上运行。</p>
        <p>Web 与 Electron 均可创建本地任务，需要可访问的 Agent 与同机资源服务。当前只支持内网部署，不支持公网部署。</p>
        <p>跳过后不再自动提示，可以随时在设置的个人设置中配置。</p>
      </div>
      <div v-else-if="step === 1" class="rows-area mt-6">
        <p v-if="!repoRows.length">当前工作区没有仓库，无需配置映射。</p>
        <template v-else>
          <RepoMappingRow v-for="row in repoRows" :key="row.remoteUrl" :remote-url="row.remoteUrl" :repo-name="row.repoName" />
          <p>已绑定 {{ boundCount }} / {{ repoRows.length }} 个仓库</p>
        </template>
      </div>
      <LocalServiceForm v-else :workspace-id="String(workspace?.id || '')" />

      <footer class="dialog-actions mt-8">
        <button class="btn-ghost" type="button" @click="emit('skip')">暂不配置</button>
        <button class="btn-primary action-button" type="button" @click="step < 2 ? step++ : emit('saved')">
          {{ step < 2 ? '下一步' : '完成' }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.repo-setup-overlay {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  background: rgba(15, 23, 42, 0.42);
  backdrop-filter: blur(8px);
}

.repo-setup-dialog {
  width: min(720px, 100%);
  max-height: 88vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 16px;
  padding: 2rem;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 24px 80px rgba(15, 23, 42, 0.15);
}

.title-gradient-small {
  margin: 0;
  font-size: 1.4rem;
  font-weight: 800;
  background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  color: #64748b;
  font-size: 0.88rem;
  margin-top: 0.4rem;
  line-height: 1.5;
}

.dialog-header {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
}

.icon-wrapper {
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.1), rgba(59, 130, 246, 0.1));
  padding: 0.75rem;
  border-radius: 12px;
  color: #0ea5e9;
  border: 1px solid rgba(14, 165, 233, 0.2);
  flex-shrink: 0;
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

.dialog-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 1.25rem;
  border-top: 1px solid rgba(0, 0, 0, 0.05);
}

.action-button {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.mt-4 { margin-top: 1rem; }
.mt-6 { margin-top: 1.5rem; }
.mt-8 { margin-top: 2rem; }
.flex-shrink-0 { flex-shrink: 0; }

@keyframes popIn {
  from { opacity: 0; transform: scale(0.95) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.animate-pop-in {
  animation: popIn 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.animate-fade-in {
  animation: fadeIn 0.3s ease both;
}
</style>
