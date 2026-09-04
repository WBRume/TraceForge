<!-- Workflow-style workspace creation dialog: basic -> project -> products -> repos. -->
<!-- 配置项关闭“项目管理/产品管理选择”时：basic(含项目/产品名称) -> repos(选仓库+分支)。 -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Briefcase, Check, FolderGit2 } from 'lucide-vue-next'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { getProject, getProjectRepoSet, getRepoGroupTree, listProjects, listRepositories } from '@/services/managementApi'
import type { Project, ProjectProduct, ProjectRepoSetItem, RepoGroupTreeNode, Repository } from '@/types/management'
import { useSystemConfigStore } from '@/stores/systemConfig'
import BasicInfoStep, { type WorkspaceBasicInfo } from './BasicInfoStep.vue'
import ProjectSelectStep from './ProjectSelectStep.vue'
import ProductSelectStep from './ProductSelectStep.vue'
import ReposConfirmStep from './ReposConfirmStep.vue'
import StandaloneReposStep from './StandaloneReposStep.vue'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'created', jobId: string): void
}>()

const { t } = useI18n()
const systemConfigStore = useSystemConfigStore()

// 配置项：是否启用“项目管理/产品管理”选择功能
const mgmtSelectionEnabled = computed(() => systemConfigStore.projectProductManagementEnabled)
const standalone = computed(() => !mgmtSelectionEnabled.value)

const ALL_STEPS = [
  { key: 'basic', label: () => t('workspace_create.step_basic') },
  { key: 'project', label: () => t('workspace_create.step_project') },
  { key: 'products', label: () => t('workspace_create.step_products') },
  { key: 'repos', label: () => t('workspace_create.step_repos') },
]

const steps = computed(() =>
  standalone.value
    ? ALL_STEPS.filter((step) => step.key === 'basic' || step.key === 'repos')
    : ALL_STEPS,
)
const stepLabels = computed(() => steps.value.map((step) => step.label()))
const currentStep = ref(0)
const currentKey = computed(() => steps.value[currentStep.value]?.key ?? 'basic')
const isLastStep = computed(() => currentStep.value >= steps.value.length - 1)

const creating = ref(false)
const projectsLoading = ref(false)
const productsLoading = ref(false)
const reposLoading = ref(false)
const projects = ref<Project[]>([])
const projectProducts = ref<ProjectProduct[]>([])
const repos = ref<ProjectRepoSetItem[]>([])
const selectedRepoIds = ref<string[]>([])

// 独立模式：仓库管理中的全部仓库（分页拉全量）+ 每个仓库使用的分支 + 仓库组树
const allRepos = ref<Repository[]>([])
const repoGroups = ref<RepoGroupTreeNode[]>([])
const standaloneBranches = ref<Record<string, string>>({})

const basicInfo = ref<WorkspaceBasicInfo>({
  name: '',
  description: '',
  project_path: '',
})
const selectedProjectId = ref<string | null>(null)
const selectedProductId = ref<string | null>(null)

const basicValid = computed(() => {
  const base = Boolean(basicInfo.value.name.trim() && basicInfo.value.project_path.trim())
  if (!standalone.value) return base
  return (
    base &&
    Boolean((basicInfo.value.project_name || '').trim()) &&
    Boolean((basicInfo.value.product_name || '').trim())
  )
})

const productsValid = computed(() => {
  return projectProducts.value.length === 0 || Boolean(selectedProductId.value)
})

const reposValid = computed(() => {
  if (standalone.value) {
    return (
      selectedRepoIds.value.length > 0 &&
      selectedRepoIds.value.every((id) => Boolean((standaloneBranches.value[id] || '').trim()))
    )
  }
  return repos.value.length === 0 || selectedRepoIds.value.length > 0
})

const canNext = computed(() => {
  if (currentKey.value === 'basic') return basicValid.value
  if (currentKey.value === 'products') return productsValid.value
  if (currentKey.value === 'repos') return reposValid.value
  return true
})

const loadProjects = async () => {
  projectsLoading.value = true
  try {
    const res = await listProjects({ page_size: 100 })
    projects.value = res.items
  } catch (error) {
    ElMessage.error(formatApiError(error, t('management.common.operation_failed'), t))
  } finally {
    projectsLoading.value = false
  }
}

const loadProjectProducts = async () => {
  projectProducts.value = []
  selectedProductId.value = null
  if (!selectedProjectId.value) return
  productsLoading.value = true
  try {
    const detail = await getProject(selectedProjectId.value)
    projectProducts.value = detail.products || []
  } catch (error) {
    ElMessage.error(formatApiError(error, t('management.common.operation_failed'), t))
  } finally {
    productsLoading.value = false
  }
}

const loadRepoSet = async () => {
  repos.value = []
  selectedRepoIds.value = []
  if (!selectedProjectId.value) return
  reposLoading.value = true
  try {
    const res = await getProjectRepoSet(
      selectedProjectId.value,
      selectedProductId.value ? [selectedProductId.value] : [],
    )
    repos.value = res.repositories
    selectedRepoIds.value = res.repositories.map((item) => item.repository_id)
  } catch (error) {
    ElMessage.error(formatApiError(error, t('management.common.operation_failed'), t))
  } finally {
    reposLoading.value = false
  }
}

const loadAllRepositories = async () => {
  allRepos.value = []
  selectedRepoIds.value = []
  standaloneBranches.value = {}
  reposLoading.value = true
  try {
    // 分页拉取全部仓库，避免仓库数超过单页上限时遗漏
    const collected: Repository[] = []
    const pageSize = 100
    let page = 1
    let total = 0
    do {
      const res = await listRepositories({ page, page_size: pageSize })
      total = Number(res.total ?? 0)
      collected.push(...(res.items || []))
      page += 1
    } while (collected.length < total && page <= 50)
    allRepos.value = collected
  } catch (error) {
    ElMessage.error(formatApiError(error, t('management.common.operation_failed'), t))
  } finally {
    reposLoading.value = false
  }
}

const loadRepoGroupTree = async () => {
  try {
    const res = await getRepoGroupTree()
    repoGroups.value = res.items || []
  } catch {
    // 拉取组树失败不阻塞：所有仓库将进入“未分组”节点
    repoGroups.value = []
  }
}

const goNext = async () => {
  if (!canNext.value) return
  if (currentKey.value === 'basic') {
    currentStep.value += 1
    if (standalone.value) {
      await Promise.all([loadAllRepositories(), loadRepoGroupTree()])
    } else {
      await loadProjects()
    }
    return
  }
  if (currentKey.value === 'project') {
    currentStep.value += 1
    await loadProjectProducts()
    return
  }
  if (currentKey.value === 'products') {
    currentStep.value += 1
    await loadRepoSet()
    return
  }
}

const goBack = () => {
  if (currentStep.value > 0) {
    currentStep.value -= 1
  }
}

const resetState = () => {
  currentStep.value = 0
  creating.value = false
  projects.value = []
  projectProducts.value = []
  repos.value = []
  allRepos.value = []
  repoGroups.value = []
  standaloneBranches.value = {}
  selectedRepoIds.value = []
  selectedProductId.value = null
  basicInfo.value = { name: '', description: '', project_path: '' }
  selectedProjectId.value = null
}

const submit = async () => {
  if (creating.value) return
  if (!reposValid.value) {
    ElMessage.warning(t('workspace_create.repos_required'))
    return
  }
  creating.value = true
  try {
    const payload: Record<string, unknown> = {
      name: basicInfo.value.name.trim(),
      description: basicInfo.value.description.trim() || undefined,
      project_path: basicInfo.value.project_path.trim(),
    }
    if (standalone.value) {
      // 独立模式：手动填写项目/产品名称（不与项目管理/产品管理数据绑定），逐仓指定分支
      payload.project_name = (basicInfo.value.project_name || '').trim()
      payload.product_name = (basicInfo.value.product_name || '').trim()
      payload.repositories = selectedRepoIds.value.map((id) => ({
        repository_id: id,
        branch_name: (standaloneBranches.value[id] || '').trim(),
      }))
    } else if (selectedProjectId.value) {
      payload.project_id = selectedProjectId.value
      payload.product_ids = selectedProductId.value ? [selectedProductId.value] : []
      const selectedRepos = repos.value.filter((item) =>
        selectedRepoIds.value.includes(item.repository_id)
      )
      payload.repositories = selectedRepos.map((item) => ({
        repository_id: item.repository_id,
        branch_name: item.ref_name,
      }))
    }
    const res = await api.post('/workspaces', payload)
    const jobId = String(res.data?.job_id || '').trim()
    if (!jobId) {
      throw new Error(t('provisioning.invalid_job_id'))
    }
    resetState()
    emit('created', jobId)
  } catch (error) {
    ElMessage.error(formatApiError(error, t('workspaces.errors.create_failed'), t))
  } finally {
    creating.value = false
  }
}

watch(
  () => props.show,
  async (visible) => {
    if (visible) {
      resetState()
      await systemConfigStore.load()
    }
  },
)
</script>

<template>
  <div
    v-if="show"
    class="mgmt-modal-overlay"
    @pointerdown.self="emit('close')"
  >
    <section class="wf-dialog glass-panel" role="dialog" aria-modal="true">
      <header class="wf-header">
        <div class="wf-header-icon">
          <Briefcase class="w-6 h-6" />
        </div>
        <div>
          <h2 class="title-gradient-small">{{ $t('workspace_create.title') }}</h2>
        </div>
      </header>

      <ol class="wf-stepper">
        <li
          v-for="(label, index) in stepLabels"
          :key="index"
          class="wf-step-item"
          :class="{ active: index === currentStep, done: index < currentStep }"
        >
          <span class="wf-step-dot">
            <Check v-if="index < currentStep" class="w-3.5 h-3.5" />
            <span v-else>{{ index + 1 }}</span>
          </span>
          <span class="wf-step-label">{{ label }}</span>
        </li>
      </ol>

      <div class="wf-body">
        <BasicInfoStep
          v-if="currentKey === 'basic'"
          v-model="basicInfo"
          :standalone="standalone"
        />
        <ProjectSelectStep
          v-else-if="currentKey === 'project'"
          v-model="selectedProjectId"
          :projects="projects"
          :loading="projectsLoading"
          @refresh="loadProjects"
        />
        <ProductSelectStep
          v-else-if="currentKey === 'products'"
          v-model="selectedProductId"
          :products="projectProducts"
          :loading="productsLoading"
        />
        <ReposConfirmStep
          v-else-if="!standalone"
          v-model="selectedRepoIds"
          :repos="repos"
          :loading="reposLoading"
        />
        <StandaloneReposStep
          v-else
          :repos="allRepos"
          :groups="repoGroups"
          :loading="reposLoading"
          :selected="selectedRepoIds"
          :branches="standaloneBranches"
          @update:selected="selectedRepoIds = $event"
          @update:branches="standaloneBranches = $event"
        />
      </div>

      <footer class="mgmt-modal-actions">
        <button v-if="currentStep > 0" type="button" class="btn-secondary" @click="goBack">
          {{ $t('workspace_create.back') }}
        </button>
        <button v-else type="button" class="btn-secondary" @click="emit('close')">
          {{ $t('common.cancel') }}
        </button>

        <button v-if="!isLastStep" type="button" class="btn-primary" :disabled="!canNext" @click="goNext">
          {{ $t('workspace_create.next') }}
        </button>
        <button v-else type="button" class="btn-primary" :disabled="creating || !reposValid" @click="submit">
          <FolderGit2 class="w-4 h-4" />
          {{ creating ? $t('workspace_create.creating') : $t('workspace_create.create') }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.wf-dialog {
  width: min(720px, 94%);
  max-height: 90vh;
  overflow-y: auto;
  border-radius: 18px;
  padding: 1.75rem;
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 24px 80px rgba(15, 23, 42, 0.18);
}

.wf-header {
  display: flex;
  align-items: center;
  gap: 0.9rem;
  margin-bottom: 1.1rem;
}

.wf-header-icon {
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.1), rgba(59, 130, 246, 0.1));
  padding: 0.65rem;
  border-radius: 12px;
  color: #0ea5e9;
  border: 1px solid rgba(14, 165, 233, 0.2);
  display: inline-flex;
}

.wf-stepper {
  list-style: none;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0 0 1.2rem;
  padding: 0.6rem 0.9rem;
  background: rgba(248, 250, 252, 0.8);
  border-radius: 12px;
  flex-wrap: wrap;
}

.wf-step-item {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  color: #94a3b8;
  font-size: 0.82rem;
  font-weight: 600;
}

.wf-step-item + .wf-step-item::before {
  content: '';
  width: 22px;
  height: 1.5px;
  background: #e2e8f0;
  margin-right: 0.45rem;
}

.wf-step-dot {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #64748b;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
}

.wf-step-item.active {
  color: #0ea5e9;
}

.wf-step-item.active .wf-step-dot {
  background: #0ea5e9;
  color: white;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.2);
}

.wf-step-item.done {
  color: #15803d;
}

.wf-step-item.done .wf-step-dot {
  background: #22c55e;
  color: white;
}

.wf-body {
  min-height: 220px;
}
</style>
