import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { defineComponent, ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), patch: vi.fn() } }))
import api from '@/utils/api'
import { useShareSuggestions } from '@/composables/useShareSuggestions'

const i18n = createI18n({
  legacy: false,
  locale: 'zh',
  fallbackLocale: 'en',
  messages: { zh, en },
})

/** 测试挂载点：taskId 可变，模拟 ChatView 中 currentTask 的就绪/切换时序 */
const mountHarness = () => {
  const taskId = ref('')
  const Harness = defineComponent({
    setup() {
      const suggestions = useShareSuggestions({
        getWorkspaceId: () => 'ws-1',
        getTaskId: () => taskId.value,
      })
      // setup 返回的组合式对象里 ref 不会自动解包；单独暴露数组 ref
      return { suggestionList: suggestions.suggestions }
    },
    template: '<div />',
  })
  const wrapper = mount(Harness, { global: { plugins: [i18n] } })
  return { wrapper, taskId }
}

describe('useShareSuggestions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue({ data: { items: [] } })
  })

  it('does not fetch before a task is selected (currentTask not ready yet)', async () => {
    mountHarness()
    await flushPromises()
    expect(api.get).not.toHaveBeenCalled()
  })

  it('loads suggestions immediately once the task becomes ready', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        items: [{
          id: 'sg-1', task_id: 'task-1', session_generation: 1,
          visitor_id: 'v1', sender_user_id: null, display_name: '访客',
          original_content: '内容', edited_content: null, status: 'PENDING',
          version: 1, created_at: '2026-09-18T10:00:00Z', updated_at: null,
          adopted_at: null, effective_content: '内容',
        }],
      },
    })
    const { wrapper, taskId } = mountHarness()
    await flushPromises()
    expect(api.get).not.toHaveBeenCalled()

    // currentTask 就绪 → 立即拉取（不再等下一轮 10s 轮询）
    taskId.value = 'task-1'
    await flushPromises()
    expect(api.get).toHaveBeenCalledWith('/workspaces/ws-1/tasks/task-1/share-suggestions')
    expect(wrapper.vm.suggestionList).toHaveLength(1)
    wrapper.unmount()
  })

  it('clears stale list and refetches when switching sessions', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        items: [{
          id: 'sg-old', task_id: 'task-1', session_generation: 1,
          visitor_id: 'v1', sender_user_id: null, display_name: null,
          original_content: '旧任务建议', edited_content: null, status: 'PENDING',
          version: 1, created_at: '2026-09-18T10:00:00Z', updated_at: null,
          adopted_at: null, effective_content: '旧任务建议',
        }],
      },
    })
    const { wrapper, taskId } = mountHarness()
    taskId.value = 'task-1'
    await flushPromises()
    expect(wrapper.vm.suggestionList).toHaveLength(1)

    // 切换到新任务：watcher（pre-flush）先清空旧列表再按新任务补拉
    vi.mocked(api.get).mockResolvedValue({ data: { items: [] } })
    taskId.value = 'task-2'
    await flushPromises()
    expect(api.get).toHaveBeenLastCalledWith('/workspaces/ws-1/tasks/task-2/share-suggestions')
    expect(wrapper.vm.suggestionList).toHaveLength(0)
    wrapper.unmount()
  })

  it('clears suggestions when the session is deselected', async () => {
    const { wrapper, taskId } = mountHarness()
    taskId.value = 'task-1'
    await flushPromises()
    vi.mocked(api.get).mockClear()

    taskId.value = ''
    await flushPromises()
    // 空 taskId 不发请求
    expect(api.get).not.toHaveBeenCalled()
    expect(wrapper.vm.suggestionList).toHaveLength(0)
    wrapper.unmount()
  })
})
