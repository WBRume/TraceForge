import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'
import type { DashboardDioramaResponse } from '@/types/dashboardDiorama'
import DioramaWorkbench from '../DioramaWorkbench.vue'

const { apiGetMock, pushMock, engineConstructMock, engineDestroyMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  pushMock: vi.fn(),
  engineConstructMock: vi.fn(),
  engineDestroyMock: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock }),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ token: 'test-token' }),
}))

vi.mock('@/utils/api', () => ({
  default: { get: apiGetMock },
  getApiServerUrl: () => 'http://localhost:8000',
}))

vi.mock('@/utils/dioramaEngine', () => ({
  ArchitecturalDioramaEngine: class {
    constructor(...args: unknown[]) {
      engineConstructMock(...args)
    }

    setData = vi.fn()
    setEnabledRepos = vi.fn()
    setMetric = vi.fn()
    setIsoMode = vi.fn()
    setLayers = vi.fn()
    setTimeline = vi.fn()
    setHighlight = vi.fn()
    setPendingRepoLabel = vi.fn()
    setSearchMatches = vi.fn()
    focusEntity = vi.fn()
    resetView = vi.fn()
    rotateView = vi.fn()
    zoomBy = vi.fn()
    destroy = engineDestroyMock
  },
}))

function createTestI18n() {
  return createI18n({
    legacy: false,
    locale: 'zh',
    fallbackLocale: 'en',
    messages: { zh, en },
  })
}

function makeTasks() {
  return [
    {
      id: 'task-newest',
      name: 'OpenCode-资产同步验证',
      description: '等待人类确认资产同步策略',
      status: 'AWAITING_INPUT',
      interrupt_kind: null,
      task_type: 'DIAGNOSIS',
      creator_id: 'u-yk',
      creator_name: 'yk',
      requirement_ids: [],
      requirement_titles: [],
      repos: [],
      modules: [],
      primary_modules: [],
      files: [],
      added: 0,
      deleted: 0,
      created_at: '2026-11-26T08:00:00Z',
      updated_at: '2026-11-26T12:00:00Z',
    },
    {
      id: 'task-mid',
      name: '自检验收-健康回执',
      description: '健康回执执行中',
      status: 'RUNNING',
      interrupt_kind: null,
      task_type: 'DEVELOPMENT',
      creator_id: 'u-yk',
      creator_name: 'yk',
      requirement_ids: ['req-1'],
      requirement_titles: ['健康规范'],
      repos: [],
      modules: [],
      primary_modules: [],
      files: [],
      added: 0,
      deleted: 0,
      created_at: '2026-11-24T09:00:00Z',
      updated_at: '2026-11-25T10:00:00Z',
    },
    {
      id: 'task-old',
      name: '实战路径查看',
      description: '较早任务',
      status: 'COMPLETED',
      interrupt_kind: null,
      task_type: 'DEVELOPMENT',
      creator_id: 'u-collab',
      creator_name: '白板兜底协作者',
      requirement_ids: [],
      requirement_titles: [],
      repos: [],
      modules: [],
      primary_modules: [],
      files: [],
      added: 0,
      deleted: 0,
      created_at: '2026-11-23T09:00:00Z',
      updated_at: '2026-11-23T11:00:00Z',
    },
  ]
}

function makeResponse(hasRepos: boolean): DashboardDioramaResponse {
  const repos = hasRepos
    ? [
        {
          id: 'repo-1',
          name: 'traceforge-web',
          slug: 'traceforge-web',
          branch: 'main',
          state: 'READY',
          color: '#0284c7',
          loc: 1200,
          file_count: 14,
          module_count: 3,
          available: true,
          modules: [
            {
              id: 'repo-1::src/views',
              repo_id: 'repo-1',
              name: 'src/views',
              loc: 1200,
              file_count: 14,
              commits: 4,
              added: 120,
              deleted: 20,
              recent_commits: [],
              files: [],
            },
          ],
        },
      ]
    : []

  const tasks = makeTasks().map(task => ({
    ...task,
    repos: hasRepos ? ['repo-1'] : [],
  }))

  return {
    workspace_id: hasRepos ? 'ws-repo' : 'ws-repoless',
    workspace_name: 'workspace',
    days: 30,
    date_range: hasRepos ? ['2026-11-24', '2026-11-26'] : [],
    has_repositories: hasRepos,
    total_loc: hasRepos ? 1200 : 0,
    total_files: hasRepos ? 14 : 0,
    total_modules: hasRepos ? 3 : 0,
    total_commits: hasRepos ? 4 : 0,
    repos,
    members: [
      { id: 'u-yk', display_name: 'yk', role: 'OWNER', color: '#0284c7' },
      { id: 'u-collab', display_name: '白板兜底协作者', role: 'DEVELOPER', color: '#059669' },
    ],
    tasks,
    timeline: hasRepos
      ? [
          {
            date: '2026-11-26',
            commit_count: 2,
            total_churn: 40,
            commits: [],
            module_heat: {},
            repo_heat: {},
          },
        ]
      : [],
    generated_at: '2026-11-26T12:00:00Z',
    windows: {},
  }
}

function mountWorkbench(workspaceId: string) {
  return mount(DioramaWorkbench, {
    props: { workspaceId },
    global: {
      plugins: [createTestI18n()],
      directives: { loading: () => {} },
      stubs: {
        'el-button': { template: '<button><slot /></button>' },
        'el-input': { props: ['modelValue', 'size', 'clearable', 'placeholder'], template: '<input />' },
        'el-empty': { props: ['description'], template: '<div>{{ description }}<slot /></div>' },
        UserAvatar: { props: ['displayName'], template: '<span class="avatar-stub">{{ displayName }}</span>' },
      },
    },
  })
}

describe('DioramaWorkbench 3D spatial glass theater', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    apiGetMock.mockReset()
    pushMock.mockReset()
    engineConstructMock.mockReset()
    engineDestroyMock.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('无仓工作区不渲染白膜与进度条，默认进入近期任务 3D 轮播剧场并支持双向联动', async () => {
    apiGetMock.mockResolvedValue({ data: makeResponse(false) })
    const wrapper = mountWorkbench('ws-repoless')
    await flushPromises()
    await nextTick()

    expect(engineConstructMock).not.toHaveBeenCalled()
    expect(wrapper.find('canvas.diorama-canvas').exists()).toBe(false)
    expect(wrapper.find('.diorama-timeline').exists()).toBe(false)
    expect(wrapper.find('.search-box').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('绑定仓库')
    expect(wrapper.text()).not.toContain('0 仓')
    expect(wrapper.text()).not.toContain('建筑详情')

    const cards = wrapper.findAll('.spatial-card')
    expect(cards).toHaveLength(3)
    expect(cards[0].text()).toContain('OpenCode-资产同步验证')
    expect(cards[0].classes()).toContain('is-front')

    // 自动轮播切换至下一条最近任务
    vi.advanceTimersByTime(4600)
    await nextTick()
    expect(wrapper.findAll('.spatial-card')[1].classes()).toContain('is-front')

    // 右栏悬停任务预览会同步拉到前景并暂停轮播
    const inspectorCards = wrapper.findAll('.task-card')
    await inspectorCards[2].trigger('mouseenter')
    await nextTick()
    expect(wrapper.findAll('.spatial-card')[2].classes()).toContain('is-front')
    expect(wrapper.find('.hud-pause-pill').text()).toContain('交互预览中')

    wrapper.unmount()
  })

  it('有仓工作区可在 2.5D、俯视 与 剧场 视图之间切换', async () => {
    apiGetMock.mockResolvedValue({ data: makeResponse(true) })
    const wrapper = mountWorkbench('ws-repo')
    await flushPromises()
    await nextTick()

    expect(engineConstructMock).toHaveBeenCalledTimes(1)
    expect(wrapper.find('canvas.diorama-canvas').exists()).toBe(true)
    expect(wrapper.find('.diorama-timeline').exists()).toBe(true)
    expect(wrapper.find('.search-box').exists()).toBe(true)

    const theaterBtn = wrapper.findAll('.seg-btn').find(btn => btn.text().includes('剧场'))
    expect(theaterBtn).toBeDefined()
    await theaterBtn!.trigger('click')
    await nextTick()

    expect(engineDestroyMock).toHaveBeenCalledTimes(1)
    expect(wrapper.find('canvas.diorama-canvas').exists()).toBe(false)
    expect(wrapper.find('.diorama-timeline').exists()).toBe(false)
    expect(wrapper.find('.search-box').exists()).toBe(false)
    expect(wrapper.find('.spatial-stage').exists()).toBe(true)

    const view3dBtn = wrapper.findAll('.seg-btn').find(btn => btn.text().includes('2.5D'))
    await view3dBtn!.trigger('click')
    await nextTick()

    expect(engineConstructMock).toHaveBeenCalledTimes(2)
    expect(wrapper.find('canvas.diorama-canvas').exists()).toBe(true)
    expect(wrapper.find('.diorama-timeline').exists()).toBe(true)

    wrapper.unmount()
  })
})
