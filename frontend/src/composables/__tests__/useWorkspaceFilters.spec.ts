import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { EMPTY_WORKSPACE_FILTERS, useWorkspaceFilters } from '../useWorkspaceFilters'

const DAY_MS = 86_400_000
const daysAgo = (days: number) => new Date(Date.now() - days * DAY_MS).toISOString()

const workspaces = [
  {
    id: 'ws-1',
    name: '支付网关重构',
    description: '订单链路的拆分与灰度',
    project: { id: 'p-1', name: '支付平台' },
    products: [{ id: 'prod-1', name: '网关', version_no: 'v2' }],
    repositories: [{ repo_name: 'pay-gateway' }],
    owner_id: 'u-1',
    owner: { id: 'u-1', display_name: '林可', email: 'lin@example.com' },
    created_at: daysAgo(2),
  },
  {
    id: 'ws-2',
    name: 'Search Service',
    description: '检索召回',
    project: null,
    custom_project_name: '搜索中台',
    products: [],
    custom_product_name: '搜索',
    repositories: [{ repo_name: 'search-api' }],
    owner_id: 'u-2',
    owner: { id: 'u-2', display_name: '周言' },
    created_at: daysAgo(40),
  },
  {
    id: 'ws-3',
    name: '旧版控制台',
    description: '',
    project: { id: 'p-2', name: '控制台' },
    products: [{ id: 'prod-2', name: '控制台' }],
    repositories: [],
    owner_id: 'u-1',
    owner: { id: 'u-1', display_name: '林可' },
    created_at: daysAgo(120),
  },
]

const setup = (options: { keyword?: string; currentUserId?: string | null } = {}) => {
  const keyword = ref(options.keyword || '')
  const filters = useWorkspaceFilters(() => workspaces, {
    keyword,
    currentUserId: () => options.currentUserId ?? null,
  })
  const ids = () => filters.filtered.value.map((ws) => ws.id)
  return { keyword, ids, ...filters }
}

describe('workspace keyword search', () => {
  it('keeps matching name, description, project and repository while ignoring case', () => {
    const { keyword, ids } = setup()
    expect(ids()).toEqual(['ws-1', 'ws-2', 'ws-3'])
    keyword.value = 'SEARCH'
    expect(ids()).toEqual(['ws-2'])
    keyword.value = '订单'
    expect(ids()).toEqual(['ws-1'])
    keyword.value = '搜索中台'
    expect(ids()).toEqual(['ws-2'])
    keyword.value = 'pay-gateway'
    expect(ids()).toEqual(['ws-1'])
    keyword.value = '   '
    expect(ids()).toEqual(['ws-1', 'ws-2', 'ws-3'])
  })
})

describe('workspace advanced filters', () => {
  it('narrows by project, product, repository and owner, and combines them', () => {
    const state = setup()

    state.patchFilters({ project: 'p-1' })
    expect(state.ids()).toEqual(['ws-1'])
    expect(state.activeFilters.value).toEqual([{ key: 'project', value: 'p-1' }])

    state.patchFilters({ product: 'prod-1', repositories: ['pay-gateway'], owner: 'u-1' })
    expect(state.ids()).toEqual(['ws-1'])
    expect(state.activeCount.value).toBe(4)

    state.patchFilters({ repositories: ['search-api'] })
    expect(state.ids()).toEqual([])
  })

  it('matches workspaces that contain any of the selected repositories', () => {
    const state = setup()
    state.patchFilters({ repositories: ['search-api', 'pay-gateway'] })
    expect(state.ids()).toEqual(['ws-1', 'ws-2'])
    expect(state.activeFilters.value).toEqual([
      { key: 'repository', value: 'search-api' },
      { key: 'repository', value: 'pay-gateway' },
    ])
    expect(state.activeCount.value).toBe(2)

    state.clearFilter('repository', 'pay-gateway')
    expect(state.filters.repositories).toEqual(['search-api'])
    expect(state.ids()).toEqual(['ws-2'])

    state.clearFilter('repository')
    expect(state.filters.repositories).toEqual([])
    expect(state.ids()).toEqual(['ws-1', 'ws-2', 'ws-3'])
  })

  it('de-duplicates selected repositories and ignores empty values', () => {
    const state = setup()
    state.patchFilters({ repositories: ['search-api', 'search-api', '', 'pay-gateway'] })
    expect(state.filters.repositories).toEqual(['search-api', 'pay-gateway'])
  })

  it('supports custom project and product names of standalone workspaces', () => {
    const state = setup()
    state.patchFilters({ project: 'custom:搜索中台' })
    expect(state.ids()).toEqual(['ws-2'])
    state.patchFilters({ project: '', product: 'custom:搜索' })
    expect(state.ids()).toEqual(['ws-2'])
  })

  it('applies relative creation windows', () => {
    const state = setup()
    state.patchFilters({ createdWithin: '7D' })
    expect(state.ids()).toEqual(['ws-1'])
    state.patchFilters({ createdWithin: '30D' })
    expect(state.ids()).toEqual(['ws-1'])
    state.patchFilters({ createdWithin: '90D' })
    expect(state.ids()).toEqual(['ws-1', 'ws-2'])
    state.patchFilters({ createdWithin: 'ALL' })
    expect(state.ids()).toEqual(['ws-1', 'ws-2', 'ws-3'])
    expect(state.activeCount.value).toBe(0)
  })

  it('restricts to the signed-in owner, and hides everything when no user is known', () => {
    const mine = setup({ currentUserId: 'u-1' })
    mine.patchFilters({ onlyMine: true })
    expect(mine.ids()).toEqual(['ws-1', 'ws-3'])
    expect(mine.activeFilters.value).toEqual([{ key: 'onlyMine', value: 'true' }])

    const anonymous = setup()
    anonymous.patchFilters({ onlyMine: true })
    expect(anonymous.ids()).toEqual([])
  })

  it('combines keyword search with advanced filters', () => {
    const state = setup({ keyword: '网关', currentUserId: 'u-1' })
    state.patchFilters({ owner: 'u-1' })
    expect(state.ids()).toEqual(['ws-1'])
    state.patchFilters({ repositories: ['search-api'] })
    expect(state.ids()).toEqual([])
  })

  it('clears one dimension without touching the others, and resets everything on demand', () => {
    const state = setup()
    state.patchFilters({ project: 'p-1', createdWithin: '7D', onlyMine: true, repositories: ['pay-gateway'] })
    expect(state.activeCount.value).toBe(4)

    state.clearFilter('createdWithin')
    expect(state.filters.createdWithin).toBe('ALL')
    expect(state.activeCount.value).toBe(3)

    state.clearFilter('onlyMine')
    expect(state.filters.onlyMine).toBe(false)
    expect(state.activeFilters.value).toEqual([
      { key: 'project', value: 'p-1' },
      { key: 'repository', value: 'pay-gateway' },
    ])

    state.resetFilters()
    expect({ ...state.filters }).toEqual({ ...EMPTY_WORKSPACE_FILTERS })
    expect(state.filters.repositories).toEqual([])
    expect(state.activeCount.value).toBe(0)
    expect(state.ids()).toEqual(['ws-1', 'ws-2', 'ws-3'])
  })

  it('falls back to ALL for unknown creation windows', () => {
    const state = setup()
    state.patchFilters({ createdWithin: '30D' })
    state.patchFilters({ createdWithin: 'LAST_YEAR' as any })
    expect(state.filters.createdWithin).toBe('ALL')
  })
})

describe('workspace filter options', () => {
  it('derives de-duplicated, label-sorted options from the workspace list', () => {
    const state = setup()

    expect(state.projectOptions.value).toEqual([
      { label: '控制台', value: 'p-2' },
      { label: '搜索中台', value: 'custom:搜索中台' },
      { label: '支付平台', value: 'p-1' },
    ])
    expect(state.productOptions.value).toEqual([
      { label: '控制台', value: 'prod-2' },
      { label: '搜索', value: 'custom:搜索' },
      { label: '网关 (v2)', value: 'prod-1' },
    ])
    expect(state.repositoryOptions.value).toEqual([
      { label: 'pay-gateway', value: 'pay-gateway' },
      { label: 'search-api', value: 'search-api' },
    ])
    expect(state.ownerOptions.value).toEqual([
      { label: '林可', value: 'u-1' },
      { label: '周言', value: 'u-2' },
    ])
  })
})
