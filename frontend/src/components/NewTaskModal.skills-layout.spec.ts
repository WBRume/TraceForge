import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import NewTaskModal from '@/components/NewTaskModal.vue'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string, params?: any) => (params ? `${key}:${JSON.stringify(params)}` : key) }),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

vi.mock('@/utils/api', () => ({
  default: apiMock,
}))

const mockSkillsPage1 = [
  { id: 'skill-1', name: 'Vue Best Practices', description: 'Vue 3 recommendations', dimension: 'WORKSPACE', publish_state: 'PUBLISHED' },
  { id: 'skill-2', name: 'Python Testing', description: 'Pytest guide', dimension: 'WORKSPACE', publish_state: 'DRAFT', has_pending_changes: true },
]

const mockSkillsPage2 = [
  { id: 'skill-3', name: 'Global API Design', description: 'REST APIs', dimension: 'GLOBAL', publish_state: 'PUBLISHED' },
]

const mockRepos = [
  { id: 'repo-1', repo_name: 'frontend', branch_name: 'feature/task-1', repo_url: 'git@github.com:org/fe.git', state: 'READY' },
  { id: 'repo-2', repo_name: 'backend', branch_name: 'feature/task-1', repo_url: 'git@github.com:org/be.git', state: 'READY' },
]

const mountModal = async () => {
  const wrapper = mount(NewTaskModal, {
    props: { show: true, wsId: 'ws-1' },
    global: {
      plugins: [createPinia()],
      mocks: { $t: (key: string, params?: any) => (params ? `${key}:${JSON.stringify(params)}` : key) },
    },
  })
  await flushPromises()
  return wrapper
}

describe('NewTaskModal layout & skills sidebar slide-out interaction', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.get.mockImplementation(async (url: string, config?: any) => {
      if (url.startsWith('/skills')) {
        const params = config?.params || {}
        if (params.page === 2) {
          return { data: { items: mockSkillsPage2, total: 20, page: 2, page_size: 8 } }
        }
        if (params.keyword === 'python') {
          return { data: { items: [mockSkillsPage1[1]], total: 1, page: 1, page_size: 8 } }
        }
        return { data: { items: mockSkillsPage1, total: 20, page: 1, page_size: 8 } }
      }
      if (url.startsWith('/workspaces/')) {
        return { data: { repositories: mockRepos } }
      }
      return { data: {} }
    })
    apiMock.post.mockResolvedValue({
      data: { job_id: 'job-100', task_id: 'task-100' },
    })
  })

  it('renders standard modal initially and slides out skills sidebar when clicking skills entry card', async () => {
    const wrapper = await mountModal()

    // 默认标准弹窗形态，侧边栏不展开
    expect(wrapper.find('.modal.with-sidebar').exists()).toBe(false)
    expect(wrapper.find('.modal-skills-sidebar.open').exists()).toBe(false)

    // 点击整行 Skills 触发卡片（排除仓库入口条）
    const skillsEntry = wrapper.find('.skills-entry-card:not(.repo-entry-card)')
    expect(skillsEntry.exists()).toBe(true)
    await skillsEntry.trigger('click')
    await flushPromises()

    // 右侧侧边栏平滑横向展开
    expect(wrapper.find('.modal.with-sidebar').exists()).toBe(true)
    expect(wrapper.find('.modal-skills-sidebar.open').exists()).toBe(true)
    expect(wrapper.text()).toContain('Vue Best Practices')
  })

  it('performs server-side search when keyword input changes in the sidebar', async () => {
    vi.useFakeTimers()
    const wrapper = await mountModal()

    // 展开侧栏（Skills 入口条，排除仓库入口条）
    await wrapper.find('.skills-entry-card:not(.repo-entry-card)').trigger('click')
    await flushPromises()

    const searchInput = wrapper.find('.skills-search-input')
    expect(searchInput.exists()).toBe(true)

    await searchInput.setValue('python')
    vi.advanceTimersByTime(350)
    await flushPromises()

    expect(apiMock.get).toHaveBeenCalledWith(
      '/skills',
      expect.objectContaining({
        params: expect.objectContaining({
          keyword: 'python',
          page: 1,
        }),
      }),
    )
    vi.useRealTimers()
  })

  it('selects skills, paginates and retains selected skills upon task creation', async () => {
    const wrapper = await mountModal()

    // 展开侧栏（Skills 入口条，排除仓库入口条）
    await wrapper.find('.skills-entry-card:not(.repo-entry-card)').trigger('click')
    await flushPromises()

    // 勾选第一个技能
    const skillCards = wrapper.findAll('.skill-card-item')
    expect(skillCards.length).toBe(2)
    await skillCards[0].trigger('click')
    await flushPromises()

    expect(wrapper.find('.skills-selected-badge').text()).toContain('count":1')

    // 翻到下一页
    const nextBtn = wrapper.findAll('.page-nav-btn')[1]
    await nextBtn.trigger('click')
    await flushPromises()

    expect(apiMock.get).toHaveBeenCalledWith(
      '/skills',
      expect.objectContaining({
        params: expect.objectContaining({
          page: 2,
        }),
      }),
    )

    // 提交任务
    await wrapper.find('input[placeholder="dashboard.task_name_placeholder"]').setValue('研发任务 1')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/tasks',
      expect.objectContaining({
        name: '研发任务 1',
        task_type: 'DEVELOPMENT',
        skill_ids: ['skill-1'],
      }),
    )
  })

  it('opens repo sidebar with tree rows and selects all repos by default', async () => {
    const wrapper = await mountModal()

    // 默认只展示仓库入口条，不展开仓库侧栏
    const repoEntry = wrapper.find('.repo-entry-card')
    expect(repoEntry.exists()).toBe(true)
    expect(wrapper.find('.modal-skills-sidebar.open').exists()).toBe(false)

    // 点击入口条：右侧滑出仓库树侧栏，默认勾选全部仓库
    await repoEntry.trigger('click')
    await flushPromises()

    expect(wrapper.find('.modal.with-sidebar').exists()).toBe(true)
    expect(wrapper.find('.modal-skills-sidebar.open').exists()).toBe(true)
    expect(wrapper.findAll('.wf-tree-repo')).toHaveLength(2)
    expect(wrapper.findAll('.wf-tree-checkbox')).toHaveLength(3)
    expect(
      wrapper
        .findAll('.wf-tree-checkbox')
        .every((c) => (c.element as HTMLInputElement).checked),
    ).toBe(true)
    expect(wrapper.text()).toContain('frontend')
    expect(wrapper.text()).toContain('backend')
  })

  it('submits repository_ids for the selected subset after unchecking a repo', async () => {
    const wrapper = await mountModal()

    // 打开仓库侧栏，取消勾选第一个仓库
    await wrapper.find('.repo-entry-card').trigger('click')
    await flushPromises()
    await wrapper.findAll('.wf-tree-checkbox')[1].trigger('change')

    await wrapper.find('input[placeholder="dashboard.task_name_placeholder"]').setValue('研发任务 2')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/tasks',
      expect.objectContaining({
        repository_ids: ['repo-2'],
      }),
    )
  })

  it('applies batch branch to selected repos and submits overrides', async () => {
    const wrapper = await mountModal()

    // 打开仓库侧栏，批量设置分支
    await wrapper.find('.repo-entry-card').trigger('click')
    await flushPromises()
    await wrapper.find('.repo-batch-input').setValue('hotfix/batch')
    await wrapper.find('.repo-batch-apply-btn').trigger('click')
    await flushPromises()

    await wrapper.find('input[placeholder="dashboard.task_name_placeholder"]').setValue('研发任务 3')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiMock.post).toHaveBeenCalledWith(
      '/workspaces/ws-1/tasks',
      expect.objectContaining({
        repository_branches: [
          { repository_id: 'repo-1', branch_name: 'hotfix/batch' },
          { repository_id: 'repo-2', branch_name: 'hotfix/batch' },
        ],
      }),
    )
  })
})
