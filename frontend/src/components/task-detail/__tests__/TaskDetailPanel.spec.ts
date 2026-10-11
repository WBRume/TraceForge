import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import api from '@/utils/api'
import zh from '@/locales/zh.json'
import TaskDetailPanel from '../TaskDetailPanel.vue'
import type { TaskInspection } from '@/types/taskInspection'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn() } }))

const detail: TaskInspection = {
  task: { id: 'task-1', name: '检查初始版本', description: '任务描述', status: 'DONE', task_type: 'DEVELOPMENT',
    creator_id: 'user', creator_name: 'Alice', execution_location: 'SERVER', created_at: '2026-10-11T10:00:00' },
  project_path: '/tasks/task-1',
  repositories: [{ id: 'r1', repository_id: 'repo', repo_name: 'Backend', repo_url: 'https://example.com/backend.git',
    branch_name: 'release/1.0', task_branch: 'task/task-1', rel_path: 'backend', worktree_path: '/tasks/task-1/backend',
    state: 'READY', error_message: null, base_commit_sha: 'a'.repeat(40),
    base_commit: { sha: 'a'.repeat(40), author_name: 'Original Author', author_email: 'author@test',
      authored_at: '2026-10-10T10:00:00+08:00', committer_name: 'Committer', committer_email: 'committer@test',
      committed_at: '2026-10-10T11:00:00+08:00', message: '原始版本\n\n完整说明' } }],
}

function mountPanel() {
  return mount(TaskDetailPanel, { props: { workspaceId: 'ws', taskId: 'task-1' }, global: {
    plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })],
  } })
}

describe('TaskDetailPanel', () => {
  it('displays the saved repository, branch, complete SHA and commit information', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: detail })
    const wrapper = mountPanel()
    expect(wrapper.text()).toContain('正在加载')
    await flushPromises()
    for (const text of ['release/1.0', 'https://example.com/backend.git', 'a'.repeat(40), 'Original Author', 'Committer', '完整说明', '/tasks/task-1/backend']) {
      expect(wrapper.text()).toContain(text)
    }
    expect(api.get).toHaveBeenCalledWith('/workspaces/ws/tasks/task-1/details', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    wrapper.unmount()
  })

  it('distinguishes pending checkout, missing history and unavailable commit details', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { ...detail, repositories: [
      { ...detail.repositories[0], id: 'pending', state: 'PENDING', base_commit_sha: null, base_commit: null },
      { ...detail.repositories[0], id: 'legacy', state: 'UNKNOWN', branch_name: null, base_commit_sha: null, base_commit: null },
      { ...detail.repositories[0], id: 'offline', base_commit: null },
    ] } })
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('等待检出')
    expect(wrapper.text()).toContain('无法确认创建时的 HEAD')
    expect(wrapper.text()).toContain('提交详情暂不可用')
    expect(wrapper.text()).not.toContain('Original Author')
    wrapper.unmount()
  })

  it('retries a failed request', async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: detail })
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('加载失败')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('检查初始版本')
    wrapper.unmount()
  })

  it('discards a late response when switching tasks', async () => {
    let resolveOld!: (value: unknown) => void
    vi.mocked(api.get).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
      .mockResolvedValueOnce({ data: { ...detail, task: { ...detail.task, id: 'task-2', name: '第二个任务' } } })
    const wrapper = mountPanel()
    await wrapper.setProps({ taskId: 'task-2' })
    await flushPromises()
    resolveOld({ data: detail })
    await flushPromises()
    expect(wrapper.text()).toContain('第二个任务')
    expect(wrapper.text()).not.toContain('检查初始版本')
    wrapper.unmount()
  })
})
