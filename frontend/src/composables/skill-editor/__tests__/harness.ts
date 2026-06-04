import { defineComponent, h, nextTick, proxyRefs } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { vi } from 'vitest'

vi.mock('@/utils/monaco', () => ({
  ensureMonacoViteSetup: vi.fn(),
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    error: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
  },
}))

vi.mock('@/utils/api', () => {
  const apiMock = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  }
  return {
    default: apiMock,
  }
})

vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  const route = reactive({
    path: '/skills/new',
    name: 'skillsCreate',
    params: {} as Record<string, string>,
    query: {} as Record<string, string>,
  })
  const router = {
    push: vi.fn(),
    replace: vi.fn(),
  }
  return {
    useRoute: () => route,
    useRouter: () => router,
    __route: route,
    __router: router,
  }
})

vi.mock('vue-i18n', async () => {
  const { ref } = await import('vue')
  const locale = ref('zh')
  const t = vi.fn((key: string) => key)
  return {
    useI18n: () => ({
      t,
      locale,
    }),
    __locale: locale,
    __t: t,
  }
})

vi.mock('@/stores/workspace', () => {
  const workspaceStore = {
    currentWorkspace: null as { id: string, name: string } | null,
    workspaces: [] as Array<{ id: string, name: string }>,
    fetchWorkspaces: vi.fn(async () => workspaceStore.workspaces),
    setCurrent: vi.fn(),
    restoreCurrent: vi.fn(),
  }
  return {
    useWorkspaceStore: () => workspaceStore,
    __workspaceStore: workspaceStore,
  }
})

vi.mock('@/stores/auth', () => {
  const authStore = {
    token: 'test-token',
    user: { id: 'user-1', display_name: 'Test User' } as { id: string, display_name: string } | null,
    isAuthenticated: true,
    setToken: vi.fn(),
    logout: vi.fn(),
    setUser: vi.fn(),
    fetchCurrentUser: vi.fn(async () => authStore.user),
  }
  return {
    useAuthStore: () => authStore,
    __authStore: authStore,
  }
})

import api from '@/utils/api'
import * as VueRouter from 'vue-router'
import * as VueI18n from 'vue-i18n'
import * as WorkspaceStoreModule from '@/stores/workspace'
import * as AuthStoreModule from '@/stores/auth'
import { ElMessage } from 'element-plus'
import { useSkillEditorViewModel, type SkillEditorViewModel } from '@/composables/useSkillEditorViewModel'

type ApiMock = {
  get: ReturnType<typeof vi.fn>
  post: ReturnType<typeof vi.fn>
  put: ReturnType<typeof vi.fn>
  patch: ReturnType<typeof vi.fn>
  delete: ReturnType<typeof vi.fn>
}

type RouteState = {
  path: string
  name?: string
  params: Record<string, string>
  query: Record<string, string>
}

type RouterState = {
  push: ReturnType<typeof vi.fn>
  replace: ReturnType<typeof vi.fn>
}

type WorkspaceStoreState = {
  currentWorkspace: { id: string, name: string } | null
  workspaces: Array<{ id: string, name: string }>
  fetchWorkspaces: ReturnType<typeof vi.fn>
}

type AuthStoreState = {
  user: { id: string, display_name: string } | null
  fetchCurrentUser: ReturnType<typeof vi.fn>
}

type I18nState = {
  value: string
}

type TMock = ReturnType<typeof vi.fn>

export type MountMode = 'new' | 'edit'

export type MountVmResult = {
  wrapper: VueWrapper
  rawVm: SkillEditorViewModel
  vm: ReturnType<typeof proxyRefs<SkillEditorViewModel>>
}

type EditApiOptions = {
  skillId?: string
  workspaceId?: string
  detail?: Record<string, unknown>
  versions?: Array<Record<string, unknown>>
  treeNodes?: Array<Record<string, unknown>>
  fileContentByPath?: Record<string, { content: string, is_binary?: boolean }>
  comments?: Array<Record<string, unknown>>
  compareFiles?: Array<Record<string, unknown>>
  fileDiffByPath?: Record<string, { original: string, modified: string, is_binary?: boolean }>
  latestAnalysis?: Record<string, unknown> | null
}

export const apiMock = api as unknown as ApiMock
export const routeState = (VueRouter as unknown as { __route: RouteState }).__route
export const routerState = (VueRouter as unknown as { __router: RouterState }).__router
export const workspaceStore = (WorkspaceStoreModule as unknown as { __workspaceStore: WorkspaceStoreState }).__workspaceStore
export const authStore = (AuthStoreModule as unknown as { __authStore: AuthStoreState }).__authStore
export const localeRef = (VueI18n as unknown as { __locale: I18nState }).__locale
export const tMock = (VueI18n as unknown as { __t: TMock }).__t
export const elMessageErrorMock = (ElMessage as unknown as { error: ReturnType<typeof vi.fn> }).error
export const elMessageSuccessMock = (ElMessage as unknown as { success: ReturnType<typeof vi.fn> }).success

export const flushAll = async (rounds = 6) => {
  for (let i = 0; i < rounds; i += 1) {
    await Promise.resolve()
    await nextTick()
  }
}

export const resetHarnessState = (options: {
  mode?: MountMode
  skillId?: string
  workspaceId?: string
  readonly?: boolean
  analysis?: boolean
  riskKey?: string
} = {}) => {
  const {
    mode = 'new',
    skillId = 'skill-1',
    workspaceId = 'ws-1',
    readonly = false,
    analysis = false,
    riskKey = '',
  } = options

  routeState.path = mode === 'edit'
    ? `/skills/${skillId}/edit${analysis ? `/analysis${riskKey ? `/risks/${riskKey}` : ''}` : ''}`
    : '/skills/new'
  routeState.name = mode === 'edit'
    ? (analysis ? (riskKey ? 'skillsEditAnalysisRisk' : 'skillsEditAnalysis') : 'skillsEdit')
    : 'skillsCreate'
  routeState.params = mode === 'edit' ? { skillId, ...(riskKey ? { riskKey } : {}) } : {}
  routeState.query = {
    wsId: workspaceId,
    ...(readonly ? { readonly: '1' } : {}),
  }

  routerState.push.mockReset()
  routerState.replace.mockReset()

  workspaceStore.workspaces = [{ id: workspaceId, name: 'Workspace 1' }]
  workspaceStore.currentWorkspace = workspaceStore.workspaces[0]
  workspaceStore.fetchWorkspaces.mockReset()
  workspaceStore.fetchWorkspaces.mockResolvedValue(workspaceStore.workspaces)

  authStore.user = { id: 'user-1', display_name: 'Test User' }
  authStore.fetchCurrentUser.mockReset()
  authStore.fetchCurrentUser.mockResolvedValue(authStore.user)

  localeRef.value = 'zh'
  tMock.mockReset()
  tMock.mockImplementation((key: string) => key)

  elMessageErrorMock.mockReset()
  elMessageSuccessMock.mockReset()

  apiMock.get.mockReset()
  apiMock.post.mockReset()
  apiMock.put.mockReset()
  apiMock.patch.mockReset()
  apiMock.delete.mockReset()

  apiMock.get.mockImplementation(async (url: string) => {
    if (url === '/workspaces') {
      return { data: workspaceStore.workspaces }
    }
    return { data: {} }
  })
  apiMock.post.mockResolvedValue({ data: {} })
  apiMock.put.mockResolvedValue({ data: {} })
  apiMock.patch.mockResolvedValue({ data: {} })
  apiMock.delete.mockResolvedValue({ data: {} })
}

export const mockEditModeApi = (options: EditApiOptions = {}) => {
  const workspaceId = options.workspaceId || routeState.query.wsId || 'ws-1'
  const skillId = options.skillId || routeState.params.skillId || 'skill-1'

  const detail = {
    id: skillId,
    name: 'Skill A',
    description: 'Skill desc',
    dimension: 'WORKSPACE',
    workspace_id: workspaceId,
    entry_file_path: 'SKILL.md',
    can_manage: true,
    average_score: null,
    review_count: 0,
    my_score: null,
    my_note: null,
    can_review: true,
    latest_version_no: 2,
    ...(options.detail || {}),
  }

  const versions = options.versions || [
    {
      id: 'ver-2',
      version_no: 2,
      creator_id: 'user-1',
      creator_display_name: 'Test User',
      created_at: '2026-04-16T10:00:00Z',
      change_note: 'v2',
    },
    {
      id: 'ver-1',
      version_no: 1,
      creator_id: 'user-1',
      creator_display_name: 'Test User',
      created_at: '2026-04-15T10:00:00Z',
      change_note: 'v1',
    },
  ]

  const treeNodes = options.treeNodes || [
    {
      path: 'SKILL.md',
      name: 'SKILL.md',
      node_type: 'file',
      children: [],
    },
  ]

  const fileContentByPath = options.fileContentByPath || {
    'SKILL.md': { content: '# Skill', is_binary: false },
  }

  const comments = options.comments || []
  const compareFiles = options.compareFiles || [
    {
      status: 'modified',
      path: 'SKILL.md',
      old_path: null,
      is_binary: false,
      additions: 1,
      deletions: 1,
    },
  ]
  const fileDiffByPath = options.fileDiffByPath || {
    'SKILL.md': {
      original: 'before',
      modified: 'after',
      is_binary: false,
    },
  }

  apiMock.get.mockImplementation(async (url: string, config?: { params?: Record<string, unknown> }) => {
    if (url === '/workspaces') {
      return { data: workspaceStore.workspaces }
    }
    if (url.endsWith(`/skills/${skillId}`)) {
      return { data: detail }
    }
    if (url.endsWith(`/skills/${skillId}/versions/compare/file`)) {
      const path = String(config?.params?.path || '')
      const diff = fileDiffByPath[path] || { original: '', modified: '', is_binary: false }
      return { data: diff }
    }
    if (url.endsWith(`/skills/${skillId}/versions/compare`)) {
      return { data: { files: compareFiles } }
    }
    if (url.endsWith(`/skills/${skillId}/versions/pending`)) {
      return {
        data: {
          has_pending_changes: false,
          changed_files_count: 0,
        },
      }
    }
    if (url.endsWith(`/skills/${skillId}/versions`)) {
      return { data: { items: versions } }
    }
    if (url.endsWith(`/skills/${skillId}/analyses/latest`)) {
      return { data: options.latestAnalysis ?? null }
    }
    if (url.endsWith(`/skills/${skillId}/reviews/overview`)) {
      return {
        data: {
          average_score: null,
          review_count: 0,
          my_score: null,
          my_note: null,
          can_review: true,
          current_version_no: 2,
        },
      }
    }
    if (url.endsWith(`/skills/${skillId}/reviews/ratings`)) {
      return { data: { items: [] } }
    }
    if (url.endsWith(`/skills/${skillId}/reviews/comments`)) {
      return { data: { items: comments } }
    }
    if (url.endsWith(`/skills/${skillId}/files/tree`)) {
      return { data: { nodes: treeNodes } }
    }
    if (url.endsWith(`/skills/${skillId}/files/content`)) {
      const path = String(config?.params?.path || '')
      const content = fileContentByPath[path] || { content: '', is_binary: false }
      return { data: content }
    }
    return { data: {} }
  })
}

export const mountSkillEditorVm = async (): Promise<MountVmResult> => {
  let vmInstance: SkillEditorViewModel | null = null
  const Host = defineComponent({
    name: 'SkillEditorVmHost',
    setup() {
      vmInstance = useSkillEditorViewModel()
      return () => h('div')
    },
  })

  const wrapper = mount(Host)
  await flushAll()

  if (!vmInstance) {
    throw new Error('failed to mount useSkillEditorViewModel')
  }

  return {
    wrapper,
    rawVm: vmInstance,
    vm: proxyRefs(vmInstance),
  }
}
