import { computed, reactive, toValue, type MaybeRefOrGetter } from 'vue'

/** 工作区「创建时间」档位，基于当前时间的相对天数。 */
export type WorkspaceCreatedWithin = 'ALL' | '7D' | '30D' | '90D'

export type WorkspaceFilterKey = 'project' | 'product' | 'repository' | 'owner' | 'createdWithin' | 'onlyMine'

/** 高级过滤条件：空字符串 / 空数组 / ALL / false 表示该维度未启用。 */
export interface WorkspaceFilterState {
  project: string
  product: string
  /** 一个工作区可关联多个仓库，因此按仓库名多选，命中任一即匹配。 */
  repositories: string[]
  owner: string
  createdWithin: WorkspaceCreatedWithin
  onlyMine: boolean
}

export interface WorkspaceFilterOption {
  label: string
  value: string
}

export interface ActiveWorkspaceFilter {
  key: WorkspaceFilterKey
  /** 过滤器展示值；多选维度（仓库）每个选中值各占一条。 */
  value: string
}

/** 工作区列表接口里本模块用到的字段，避免与后端 schema 强耦合。 */
export interface WorkspaceFilterItem {
  name?: string | null
  description?: string | null
  project_id?: string | null
  custom_project_name?: string | null
  custom_product_name?: string | null
  project?: { id?: string | null; name?: string | null } | null
  products?: Array<{ id?: string | null; name?: string | null; version_no?: string | null }> | null
  repositories?: Array<{ repo_name?: string | null }> | null
  owner_id?: string | null
  owner?: { id?: string | null; display_name?: string | null; email?: string | null } | null
  created_at?: string | Date | null
}

export interface UseWorkspaceFiltersOptions {
  keyword?: MaybeRefOrGetter<string | null | undefined>
  currentUserId?: MaybeRefOrGetter<string | null | undefined>
}

export const EMPTY_WORKSPACE_FILTERS: Readonly<WorkspaceFilterState> = Object.freeze({
  project: '',
  product: '',
  repositories: [] as string[],
  owner: '',
  createdWithin: 'ALL',
  onlyMine: false,
})

const CUSTOM_PREFIX = 'custom:'
const DAY_MS = 86_400_000
const CREATED_WITHIN_DAYS: Record<WorkspaceCreatedWithin, number> = { ALL: 0, '7D': 7, '30D': 30, '90D': 90 }

type OptionPair = [value: string, label: string]

const labelCollator = new Intl.Collator('zh-Hans-CN', { numeric: true, sensitivity: 'base' })

function buildOptions(pairs: OptionPair[]): WorkspaceFilterOption[] {
  const seen = new Map<string, string>()
  for (const [value, label] of pairs) {
    if (!value || seen.has(value)) continue
    seen.set(value, label || value)
  }
  return [...seen]
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => labelCollator.compare(a.label, b.label))
}

function projectValue(workspace: WorkspaceFilterItem): string {
  const projectId = workspace.project?.id || workspace.project_id || ''
  if (projectId) return projectId
  return workspace.custom_project_name ? `${CUSTOM_PREFIX}${workspace.custom_project_name}` : ''
}

function projectLabel(workspace: WorkspaceFilterItem): string {
  return workspace.project?.name || workspace.custom_project_name || ''
}

function productPairs(workspace: WorkspaceFilterItem): OptionPair[] {
  const products = workspace.products || []
  if (products.length === 0) {
    const custom = workspace.custom_product_name
    return custom ? [[`${CUSTOM_PREFIX}${custom}`, custom]] : []
  }
  return products.map((product) => {
    const name = product.name || ''
    const value = product.id || (name ? `${CUSTOM_PREFIX}${name}` : '')
    const label = name && product.version_no ? `${name} (${product.version_no})` : name
    return [value, label]
  })
}

function productValues(workspace: WorkspaceFilterItem): string[] {
  return productPairs(workspace).map(([value]) => value).filter(Boolean)
}

function repositoryNames(workspace: WorkspaceFilterItem): string[] {
  return (workspace.repositories || []).map((repo) => repo.repo_name || '').filter(Boolean)
}

function ownerValue(workspace: WorkspaceFilterItem): string {
  return workspace.owner?.id || workspace.owner_id || ''
}

function ownerLabel(workspace: WorkspaceFilterItem): string {
  return workspace.owner?.display_name || workspace.owner?.email || ''
}

function createdTimestamp(workspace: WorkspaceFilterItem): number {
  const raw = workspace.created_at
  if (!raw) return Number.NaN
  return raw instanceof Date ? raw.getTime() : Date.parse(raw)
}

function matchesKeyword(workspace: WorkspaceFilterItem, keyword: string): boolean {
  if (!keyword) return true
  const name = (workspace.name || '').toLowerCase()
  const description = (workspace.description || '').toLowerCase()
  const project = projectLabel(workspace).toLowerCase()
  const repositories = repositoryNames(workspace).join(' ').toLowerCase()
  return name.includes(keyword) || description.includes(keyword) || project.includes(keyword) || repositories.includes(keyword)
}

function matchesFilters(workspace: WorkspaceFilterItem, filters: WorkspaceFilterState, currentUserId: string): boolean {
  if (filters.project && projectValue(workspace) !== filters.project) return false
  if (filters.product && !productValues(workspace).includes(filters.product)) return false
  if (filters.repositories.length > 0) {
    const names = repositoryNames(workspace)
    if (!filters.repositories.some((repo) => names.includes(repo))) return false
  }
  if (filters.owner && ownerValue(workspace) !== filters.owner) return false
  if (filters.onlyMine && (!currentUserId || ownerValue(workspace) !== currentUserId)) return false
  const days = CREATED_WITHIN_DAYS[filters.createdWithin]
  if (days > 0) {
    const createdAt = createdTimestamp(workspace)
    if (Number.isNaN(createdAt) || createdAt < Date.now() - days * DAY_MS) return false
  }
  return true
}

/**
 * 工作区列表的关键字 + 高级过滤：条件保存在本地 reactive 状态，
 * 过滤结果与可选值均由工作区数据派生，不产生额外请求。
 */
export function useWorkspaceFilters<T extends WorkspaceFilterItem = WorkspaceFilterItem>(
  workspaces: MaybeRefOrGetter<T[] | null | undefined>,
  options: UseWorkspaceFiltersOptions = {},
) {
  const filters = reactive<WorkspaceFilterState>({ ...EMPTY_WORKSPACE_FILTERS })
  const items = computed(() => toValue(workspaces) || [])
  const keyword = computed(() => (toValue(options.keyword) || '').trim().toLowerCase())
  const currentUserId = computed(() => toValue(options.currentUserId) || '')

  const projectOptions = computed(() => buildOptions(items.value.map((ws) => [projectValue(ws), projectLabel(ws)])))
  const productOptions = computed(() => buildOptions(items.value.flatMap(productPairs)))
  const repositoryOptions = computed(() => buildOptions(
    items.value.flatMap((ws) => repositoryNames(ws).map((name) => [name, name] as OptionPair)),
  ))
  const ownerOptions = computed(() => buildOptions(items.value.map((ws) => [ownerValue(ws), ownerLabel(ws)])))

  const filtered = computed(() => items.value.filter(
    (ws) => matchesKeyword(ws, keyword.value) && matchesFilters(ws, filters, currentUserId.value),
  ))

  const activeFilters = computed<ActiveWorkspaceFilter[]>(() => {
    const active: ActiveWorkspaceFilter[] = []
    if (filters.project) active.push({ key: 'project', value: filters.project })
    if (filters.product) active.push({ key: 'product', value: filters.product })
    for (const repo of filters.repositories) active.push({ key: 'repository', value: repo })
    if (filters.owner) active.push({ key: 'owner', value: filters.owner })
    if (filters.createdWithin !== 'ALL') active.push({ key: 'createdWithin', value: filters.createdWithin })
    if (filters.onlyMine) active.push({ key: 'onlyMine', value: 'true' })
    return active
  })
  const activeCount = computed(() => activeFilters.value.length)

  function patchFilters(patch: Partial<WorkspaceFilterState>) {
    const next: Partial<WorkspaceFilterState> = { ...patch }
    if (next.createdWithin !== undefined && !(next.createdWithin in CREATED_WITHIN_DAYS)) next.createdWithin = 'ALL'
    if (next.repositories !== undefined) next.repositories = [...new Set(next.repositories.filter(Boolean))]
    Object.assign(filters, next)
  }

  /** 清除单个维度的条件；多选维度（仓库）传 value 时只移除该值。 */
  function clearFilter(key: WorkspaceFilterKey, value?: string) {
    if (key === 'repository') {
      filters.repositories = value ? filters.repositories.filter((repo) => repo !== value) : []
      return
    }
    if (key === 'createdWithin') filters.createdWithin = 'ALL'
    else if (key === 'onlyMine') filters.onlyMine = false
    else filters[key] = ''
  }

  function resetFilters() {
    Object.assign(filters, { ...EMPTY_WORKSPACE_FILTERS, repositories: [] })
  }

  return {
    filters,
    filtered,
    projectOptions,
    productOptions,
    repositoryOptions,
    ownerOptions,
    activeFilters,
    activeCount,
    patchFilters,
    clearFilter,
    resetFilters,
  }
}
