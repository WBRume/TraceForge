<!-- Workflow-style workspace creation dialog: basic -> project -> products -> repos. -->
<!-- 配置项关闭“项目管理/产品管理选择”时：basic(含项目/产品名称) -> repos(可选仓库+分支)。 -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Briefcase, Check, FolderGit2 } from 'lucide-vue-next'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import { getProject, getProjectRepoSet, getRepoGroupTree, listProjects, listRepositories } from '@/services/managementApi'
import type { Project, ProjectProduct, ProjectRepoSetItem, RepoGroupTreeNode, Repository } from '@/types/management'
import { useSystemConfigStore } from '@/stores/systemConfig'
import {
  WORKSPACE_BASE_SEGMENT,
  isPathWithinBase,
  joinWorkspacePath,
} from '@/utils/workspacePath'
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

// 配置项：工作区根目录。非空时路径默认为 根目录/workspace/工作区名称，且仅允许位于该目录之内。
const workspaceRootDir = computed(() => (systemConfigStore.workspaceRootDir || '').trim())
const workspaceBase = computed(() =>
  workspaceRootDir.value ? joinWorkspacePath(workspaceRootDir.value, WORKSPACE_BASE_SEGMENT) : ''
)

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
// 基本信息步“下一步”触发冲突预检时的进行中标记（防止重复点击/重复弹窗）
const preflighting = ref(false)
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

const pathScopeValid = computed(() => {
  const base = workspaceBase.value
  if (!base) return true
  return isPathWithinBase(basicInfo.value.project_path.trim(), base)
})

const basicValid = computed(() => {
  const base = Boolean(basicInfo.value.name.trim() && basicInfo.value.project_path.trim())
  if (!pathScopeValid.value) return false
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
    // 独立模式允许不选择仓库，创建仅包含根目录的工作区；已选仓库仍必须填写分支。
    return selectedRepoIds.value.every((id) => Boolean((standaloneBranches.value[id] || '').trim()))
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

const enterStepAfterBasic = async () => {
  currentStep.value += 1
  if (standalone.value) {
    await Promise.all([loadAllRepositories(), loadRepoGroupTree()])
  } else {
    await loadProjects()
  }
}

const goNext = async () => {
  if (!canNext.value || preflighting.value) return
  if (currentKey.value === 'basic') {
    // 名称与根目录在基本信息步即已确定：进入下一步前先做冲突预检，
    // 命中时弹窗由用户决策是否继续（确认后进入下一步，结果缓存供提交时复用）。
    preflighting.value = true
    try {
      const conflicts = await getCreateConflicts(
        basicInfo.value.name.trim(),
        basicInfo.value.project_path.trim()
      )
      if (conflicts) {
        conflictDetails.value = conflicts
        conflictAction.value = 'next'
        pendingConflictKey = conflictKeyOf(
          basicInfo.value.name.trim(),
          basicInfo.value.project_path.trim()
        )
        showConflictConfirm.value = true
        return
      }
      await enterStepAfterBasic()
    } finally {
      preflighting.value = false
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

interface WorkspaceConflictBrief {
  id: string
  name: string
  owner_name?: string
  project_path?: string
}

interface WorkspaceConflictDetails {
  nameConflicts: WorkspaceConflictBrief[]
  pathConflicts: WorkspaceConflictBrief[]
}

const showConflictConfirm = ref(false)
const conflictDetails = ref<WorkspaceConflictDetails | null>(null)
// 冲突确认后的下一步动作：'next' = 基本信息步继续进入下一步；'create' = 最终提交创建
const conflictAction = ref<'next' | 'create'>('next')
// 预检缓存（key = name|path）：基本信息“下一步”已预检过的组合，提交时不再重复请求
const preflightCache = new Map<string, WorkspaceConflictDetails | null>()
// 用户已在弹窗中确认继续的冲突组合（key = name|path）：提交时不再二次弹窗
const confirmedConflictKeys = new Set<string>()
// 当前弹窗对应的冲突组合 key
let pendingConflictKey = ''
let pendingCreatePayload: Record<string, unknown> | null = null

const conflictKeyOf = (name: string, path: string) => `${name}\n${path}`

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
  showConflictConfirm.value = false
  conflictDetails.value = null
  conflictAction.value = 'next'
  preflightCache.clear()
  confirmedConflictKeys.clear()
  pendingConflictKey = ''
  pendingCreatePayload = null
}

const buildCreatePayload = (): Record<string, unknown> => {
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
  return payload
}

const doCreate = async (payload: Record<string, unknown>) => {
  const res = await api.post('/workspaces', payload)
  const jobId = String(res.data?.job_id || '').trim()
  if (!jobId) {
    throw new Error(t('provisioning.invalid_job_id'))
  }
  resetState()
  emit('created', jobId)
}

const fetchCreateConflicts = async (
  name: string,
  projectPath: string,
): Promise<WorkspaceConflictDetails | null> => {
  try {
    const res = await api.post('/workspaces/preflight', {
      name,
      project_path: projectPath || undefined,
    })
    const data: any = res.data || {}
    const nameConflicts: WorkspaceConflictBrief[] = Array.isArray(data.name_conflict_workspaces)
      ? data.name_conflict_workspaces
      : []
    const pathConflicts: WorkspaceConflictBrief[] = Array.isArray(data.path_conflict_workspaces)
      ? data.path_conflict_workspaces
      : []
    if (nameConflicts.length === 0 && pathConflicts.length === 0) return null
    return { nameConflicts, pathConflicts }
  } catch (error) {
    // 预检失败不阻塞创建（保持原有行为），仅在控制台记录
    console.warn('workspace create preflight failed', error)
    return null
  }
}

const getCreateConflicts = async (
  name: string,
  projectPath: string,
): Promise<WorkspaceConflictDetails | null> => {
  const key = conflictKeyOf(name, projectPath)
  if (preflightCache.has(key)) {
    return preflightCache.get(key) ?? null
  }
  const result = await fetchCreateConflicts(name, projectPath)
  preflightCache.set(key, result)
  return result
}

const submit = async () => {
  if (creating.value) return
  if (!reposValid.value) {
    ElMessage.warning(t('workspace_create.repos_required'))
    return
  }
  creating.value = true
  try {
    const payload = buildCreatePayload()
    const name = String(payload.name || '')
    const path = String(payload.project_path || '')
    // 基本信息步“下一步”已预检过相同名称/路径时直接复用结果；
    // 用户已确认过该组合的冲突时不再二次弹窗，直接创建
    const conflicts = await getCreateConflicts(name, path)
    if (conflicts && !confirmedConflictKeys.has(conflictKeyOf(name, path))) {
      // 重名 / 目录被引用：弹窗让用户决策是否继续创建
      conflictDetails.value = conflicts
      conflictAction.value = 'create'
      pendingConflictKey = conflictKeyOf(name, path)
      pendingCreatePayload = payload
      showConflictConfirm.value = true
      return
    }
    await doCreate(payload)
  } catch (error) {
    ElMessage.error(formatApiError(error, t('workspaces.errors.create_failed'), t))
  } finally {
    creating.value = false
  }
}

const onConflictConfirm = async () => {
  const action = conflictAction.value
  const payload = pendingCreatePayload
  showConflictConfirm.value = false
  pendingCreatePayload = null
  conflictDetails.value = null
  if (pendingConflictKey) {
    confirmedConflictKeys.add(pendingConflictKey)
    pendingConflictKey = ''
  }
  if (action === 'next') {
    // 基本信息步确认冲突后继续进入下一步（预检结果已缓存，提交时不再重复弹窗）
    try {
      await enterStepAfterBasic()
    } catch (error) {
      ElMessage.error(formatApiError(error, t('management.common.operation_failed'), t))
    }
    return
  }
  if (!payload) return
  creating.value = true
  try {
    await doCreate(payload)
  } catch (error) {
    ElMessage.error(formatApiError(error, t('workspaces.errors.create_failed'), t))
  } finally {
    creating.value = false
  }
}

const onConflictCancel = () => {
  showConflictConfirm.value = false
  pendingCreatePayload = null
  conflictDetails.value = null
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
          :workspace-base="workspaceBase"
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

        <button v-if="!isLastStep" type="button" class="btn-primary" :disabled="!canNext || preflighting" @click="goNext">
          {{ $t('workspace_create.next') }}
        </button>
        <button v-else type="button" class="btn-primary" :disabled="creating || !reposValid" @click="submit">
          <FolderGit2 class="w-4 h-4" />
          {{ creating ? $t('workspace_create.creating') : $t('workspace_create.create') }}
        </button>
      </footer>
    </section>

    <!-- 重名 / 目录被引用冲突确认：由用户决策是否继续创建。
         teleport 关闭：作为创建弹窗 overlay 的子元素渲染，天然叠在弹窗内容之上，
         不受外部层叠上下文（祖先 z-index/transform 等）影响。 -->
    <ConfirmActionModal
      :show="showConflictConfirm"
      :title="t('workspace_create.conflict_title')"
      :message="t('workspace_create.conflict_message')"
      :cancel-text="t('workspace_create.conflict_cancel')"
      :confirm-text="conflictAction === 'next'
        ? t('workspace_create.conflict_continue_next')
        : t('workspace_create.conflict_continue')"
      tone="primary"
      :teleport="false"
      :z-index="400"
      @cancel="onConflictCancel"
      @confirm="onConflictConfirm"
    >
      <template #content>
        <ul class="wf-conflict-list">
          <li
            v-for="item in conflictDetails?.nameConflicts || []"
            :key="`name-${item.id}`"
          >
            {{ t('workspace_create.conflict_name_item', { name: item.name }) }}
          </li>
          <li
            v-for="item in conflictDetails?.pathConflicts || []"
            :key="`path-${item.id}`"
          >
            {{ t('workspace_create.conflict_path_item', { path: item.project_path, name: item.name }) }}
          </li>
        </ul>
      </template>
    </ConfirmActionModal>
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

.wf-conflict-list {
  margin: 0;
  padding-left: 1.1rem;
  font-size: 0.85rem;
  color: #475569;
  line-height: 1.8;
  word-break: break-all;
}
</style>
