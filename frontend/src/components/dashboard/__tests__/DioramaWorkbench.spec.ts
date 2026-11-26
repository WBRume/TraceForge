import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'
import type { DashboardDioramaResponse } from '@/types/dashboardDiorama'
import DioramaTimelineBar from '../DioramaTimelineBar.vue'
import DioramaWorkbench from '../DioramaWorkbench.vue'

const { apiGetMock, pushMock, engineConstructMock, engineDestroyMock, engineEnableReposMock, engineSearchMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  pushMock: vi.fn(),
  engineConstructMock: vi.fn(),
  engineDestroyMock: vi.fn(),
  engineEnableReposMock: vi.fn(),
  engineSearchMock: vi.fn(),
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
    setEnabledRepos = engineEnableReposMock
    setMetric = vi.fn()
    setIsoMode = vi.fn()
    setLayers = vi.fn()
    setTimeline = vi.fn()
    setHighlight = vi.fn()
    setPendingRepoLabel = vi.fn()
    setSearchMatches = engineSearchMock
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
      description: '已确认资产同步策略',
      status: 'COMPLETED',
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
      created_at: '2026-10-01T08:00:00Z',
      updated_at: '2026-10-02T12:00:00Z',
      last_activity_at: '2026-11-26T12:00:00Z',
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
      last_activity_at: '2026-11-25T10:00:00Z',
    },
    {
      id: 'task-interrupted',
      name: '实战路径查看',
      description: '可恢复的中断任务',
      status: 'INTERRUPTED',
      interrupt_kind: 'MANUAL',
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
      updated_at: '2026-11-26T13:00:00Z',
      last_activity_at: '2026-11-05T11:00:00Z',
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

  const period = {
    days: 30,
    date_range: hasRepos ? ['2026-11-24', '2026-11-26'] : [],
    has_repositories: hasRepos,
    total_loc: hasRepos ? 1200 : 0,
    total_files: hasRepos ? 14 : 0,
    total_modules: hasRepos ? 3 : 0,
    total_commits: hasRepos ? 4 : 0,
    repos,
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
  }

  return {
    ...period,
    workspace_id: hasRepos ? 'ws-repo' : 'ws-repoless',
    workspace_name: 'workspace',
    members: [
      { id: 'u-yk', display_name: 'yk', role: 'OWNER', color: '#0284c7' },
      { id: 'u-collab', display_name: '白板兜底协作者', role: 'DEVELOPER', color: '#059669' },
    ],
    generated_at: '2026-11-26T12:00:00Z',
    windows: hasRepos ? {} : { 14: { ...period, days: 14, tasks: tasks.slice(0, 2) } },
  }
}

function mountWorkbench(workspaceId: string, attachTo?: HTMLElement) {
  return mount(DioramaWorkbench, {
    props: { workspaceId },
    attachTo,
    global: {
      plugins: [createTestI18n()],
      directives: { loading: () => {} },
      stubs: {
        'el-button': { template: '<button><slot /></button>' },
        'el-input': {
          props: ['modelValue', 'size', 'clearable', 'placeholder'],
          emits: ['update:modelValue'],
          template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
        },
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

  it('无仓工作区按接口顺序轮播活跃任务并支持侧栏预览', async () => {
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
    expect(cards[0].get('time').attributes('datetime')).toBe('2026-11-26T12:00:00Z')

    // 中断任务更新时间较晚，轮播仍遵循接口给出的活动顺序。
    vi.advanceTimersByTime(4600)
    await nextTick()
    expect(wrapper.findAll('.spatial-card')[1].classes()).toContain('is-front')

    // 右栏悬停任务预览会同步拉到前景并暂停轮播
    const inspectorCards = wrapper.findAll('.task-card')
    await inspectorCards[2].trigger('mouseenter')
    await nextTick()
    expect(wrapper.findAll('.spatial-card')[2].classes()).toContain('is-front')
    expect(wrapper.find('.hud-pause-pill').text()).toContain('交互预览中')

    const shortWindow = wrapper.findAll('.toolbar-row-top .seg-btn').find(btn => btn.text() === '14天')
    await shortWindow!.trigger('click')
    expect(shortWindow!.attributes('aria-pressed')).toBe('true')
    expect(wrapper.findAll('.spatial-card')).toHaveLength(2)
    expect(wrapper.findAll('.task-card')).toHaveLength(2)
    expect(apiGetMock).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })

  it('有仓工作区可在 2.5D、俯视 与 剧场 视图之间切换', async () => {
    const response = makeResponse(true)
    response.timeline.unshift({ ...response.timeline[0], date: '2026-11-25' })
    apiGetMock.mockResolvedValue({ data: response })
    const wrapper = mountWorkbench('ws-repo')
    await flushPromises()
    await nextTick()

    expect(engineConstructMock).toHaveBeenCalledTimes(1)
    expect(wrapper.find('canvas.diorama-canvas').exists()).toBe(true)
    expect(wrapper.find('.diorama-timeline').exists()).toBe(true)
    expect(wrapper.find('.search-box').exists()).toBe(true)

    await wrapper.get('.search-box input').setValue('src/views')
    const matches = new Set(['repo-1::src/views'])
    expect(engineSearchMock).toHaveBeenLastCalledWith(matches)
    engineSearchMock.mockClear()

    await wrapper.get('.diorama-timeline .play-btn').trigger('click')
    expect(wrapper.getComponent(DioramaTimelineBar).props()).toMatchObject({ playing: true, dayIndex: 0 })

    const topBtn = wrapper.findAll('.seg-btn').find(btn => btn.text().includes('俯视'))
    await topBtn!.trigger('click')
    expect(engineEnableReposMock).not.toHaveBeenCalled()

    const theaterBtn = wrapper.findAll('.seg-btn').find(btn => btn.text().includes('剧场'))
    expect(theaterBtn).toBeDefined()
    await theaterBtn!.trigger('click')
    await nextTick()

    expect(engineDestroyMock).toHaveBeenCalledTimes(1)
    expect(wrapper.find('canvas.diorama-canvas').exists()).toBe(false)
    expect(wrapper.find('.diorama-timeline').exists()).toBe(false)
    expect(wrapper.find('.search-box').exists()).toBe(false)
    expect(wrapper.find('.spatial-stage').exists()).toBe(true)

    vi.advanceTimersByTime(1000)
    const view3dBtn = wrapper.findAll('.seg-btn').find(btn => btn.text().includes('2.5D'))
    await view3dBtn!.trigger('click')
    await nextTick()

    expect(engineConstructMock).toHaveBeenCalledTimes(2)
    expect(wrapper.find('canvas.diorama-canvas').exists()).toBe(true)
    expect(wrapper.find('.diorama-timeline').exists()).toBe(true)
    expect(wrapper.getComponent(DioramaTimelineBar).props()).toMatchObject({ playing: false, dayIndex: 0 })
    expect(engineSearchMock).toHaveBeenLastCalledWith(matches)

    wrapper.unmount()
  })

  it('固定超出六张卡片的任务后正确翻页，隐藏仓库后清理不可见的固定任务', async () => {
    const response = makeResponse(true)
    response.workspace_id = 'ws-repo-filter'
    response.repos.push({ ...response.repos[0], id: 'repo-2', name: '第二个仓库', modules: [] })
    response.tasks = Array.from({ length: 8 }, (_, i) => ({
      ...response.tasks[0],
      id: `task-${i + 1}`,
      name: `任务 ${i + 1}`,
      repos: [i === 7 ? 'repo-2' : 'repo-1'],
    }))
    apiGetMock.mockResolvedValue({ data: response })
    const wrapper = mountWorkbench(response.workspace_id)
    await flushPromises()

    await wrapper.findAll('.seg-btn').find(btn => btn.text().includes('剧场'))!.trigger('click')
    const frontTitle = () => wrapper.get('.spatial-card.is-front .card-title').text()
    await wrapper.findAll('.task-card')[7].trigger('click')
    expect(frontTitle()).toBe('任务 8')

    await wrapper.get('.nav-step-btn[title="下一条"]').trigger('click')
    expect(frontTitle()).toBe('任务 1')

    await wrapper.findAll('.task-card')[7].trigger('click')
    await wrapper.findAll('.repo-pill')[1].trigger('click')
    expect(wrapper.findAll('.task-card')).toHaveLength(7)
    expect(wrapper.find('.task-card.is-pinned').exists()).toBe(false)
    expect(frontTitle()).toBe('任务 1')
    expect(wrapper.get('.hud-counter').text()).toBe('1 / 6')

    vi.advanceTimersByTime(4500)
    await nextTick()
    expect(frontTitle()).toBe('任务 2')

    wrapper.unmount()
  })

  it('在按钮上保留空格键的原生操作', async () => {
    const response = { ...makeResponse(false), workspace_id: 'ws-keyboard' }
    apiGetMock.mockResolvedValue({ data: response })
    const wrapper = mountWorkbench(response.workspace_id, document.body)
    await flushPromises()

    const toggle = wrapper.get('button.toggle-chip')
    const buttonSpace = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true })
    toggle.element.dispatchEvent(buttonSpace)
    await nextTick()
    expect(buttonSpace.defaultPrevented).toBe(false)
    expect(toggle.attributes('aria-pressed')).toBe('true')

    const shortcut = new KeyboardEvent('keydown', { key: ' ', cancelable: true })
    window.dispatchEvent(shortcut)
    await nextTick()
    expect(shortcut.defaultPrevented).toBe(true)
    expect(toggle.attributes('aria-pressed')).toBe('false')

    wrapper.unmount()
  })
})
