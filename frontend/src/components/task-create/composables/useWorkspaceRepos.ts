import { computed, reactive, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import type { WorkspaceRepo } from '../types'
import { workspaceRepoBindingId } from '../lib/repoTree'

/**
 * 工作区仓库环境控制器：仓库列表、worktree 勾选、按仓库分支覆盖、
 * 分支 refs 懒加载与批量分支应用。
 *
 * 创建流程（校验 / payload 组装 / 入口条徽标）与仓库侧栏共享读写，
 * 因此返回 reactive 控制器（内部 ref 自动解包），由对话框持有、
 * 经 prop 注入侧栏——类似传递一个局部 store。
 */
export function useWorkspaceRepos(getWsId: () => string) {
  const { t } = useI18n()

  const repos = shallowRef<WorkspaceRepo[]>([])
  const loading = shallowRef(false)
  // 勾选的仓库（默认全部；仅为所选仓库创建 worktree）
  const selectedIds = shallowRef<string[]>([])
  // 会话创建时按仓库选填分支覆盖（留空 = 沿用工作区绑定分支）
  const branchOverrides = shallowRef<Record<string, string>>({})
  // 分支 refs 下拉数据（按仓库懒加载缓存，整对象替换）
  const refsCache = shallowRef<Record<string, string[]>>({})
  const refsLoading = shallowRef<Record<string, boolean>>({})

  const repoById = computed(() => {
    const map = new Map<string, WorkspaceRepo>()
    for (const repo of repos.value) {
      map.set(workspaceRepoBindingId(repo), repo)
    }
    return map
  })

  const selectedCount = computed(() => selectedIds.value.length)
  const allSelected = computed(
    () => repos.value.length > 0 && selectedIds.value.length === repos.value.length,
  )

  const isSelected = (repoId: string): boolean => selectedIds.value.includes(repoId)

  const defaultBranchOf = (repoId: string): string =>
    repoById.value.get(repoId)?.branch_name || 'main'

  /** 拉取工作区绑定的仓库环境；默认勾选全部仓库 */
  const load = async () => {
    loading.value = true
    try {
      const res = await api.get('/workspaces/' + getWsId())
      repos.value = res.data?.repositories || []
      selectedIds.value = repos.value.map(workspaceRepoBindingId).filter(Boolean)
    } catch {
      repos.value = []
      selectedIds.value = []
    } finally {
      loading.value = false
    }
  }

  const setSelectedIds = (ids: string[]): void => {
    selectedIds.value = ids
  }

  const toggleAll = (): void => {
    selectedIds.value = allSelected.value
      ? []
      : repos.value.map(workspaceRepoBindingId).filter(Boolean)
  }

  const setBranchOverride = (repoId: string, value: string): void => {
    branchOverrides.value = { ...branchOverrides.value, [repoId]: value }
  }

  /** 一键把输入的分支应用到所有勾选仓库 */
  const applyBatchBranch = (branch: string): void => {
    const normalized = branch.trim()
    if (!normalized || selectedIds.value.length === 0) return
    const overrides = { ...branchOverrides.value }
    for (const repoId of selectedIds.value) {
      overrides[repoId] = normalized
    }
    branchOverrides.value = overrides
    ElMessage.success(
      t('dashboard.task_repo_batch_applied', { count: selectedIds.value.length, branch: normalized }),
    )
  }

  /** 聚焦分支输入时懒加载该仓库 refs（失败不阻塞：保留默认分支提示 + 手动输入） */
  const loadRefs = async (repoId: string) => {
    if (!repoId || refsCache.value[repoId] || refsLoading.value[repoId]) return
    refsLoading.value = { ...refsLoading.value, [repoId]: true }
    try {
      const res = await api.get(`/management/repositories/${repoId}/refs`)
      refsCache.value = { ...refsCache.value, [repoId]: res.data?.branches || [] }
    } catch {
      refsCache.value = { ...refsCache.value, [repoId]: [] }
    } finally {
      refsLoading.value = { ...refsLoading.value, [repoId]: false }
    }
  }

  return reactive({
    repos,
    loading,
    selectedIds,
    branchOverrides,
    refsCache,
    refsLoading,
    selectedCount,
    allSelected,
    isSelected,
    defaultBranchOf,
    load,
    setSelectedIds,
    toggleAll,
    setBranchOverride,
    applyBatchBranch,
    loadRefs,
  })
}

export type WorkspaceReposController = ReturnType<typeof useWorkspaceRepos>
