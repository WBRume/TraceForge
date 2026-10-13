import { expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import CollaborationBackups from '@/components/collaboration/CollaborationBackups.vue'
import type { LocalCollaboration } from '../useLocalCollaboration'
import type { CollaborationBackup } from '@/types/collaboration'

const backup = (round: number, repo: string, operation = `restore-${round}`): CollaborationBackup => ({
  operation_id: operation, task_repository_id: repo, path: 'shared.txt', sha256: `${round}-${repo}`, state: 'SUCCEEDED', backup_path: null,
  created_at: `2026-10-13T0${round}:00:00Z`, context: { task_id: 'task', snapshot_id: `result-${round}`, workspace_revision: round * 2,
    session_generation: 1, session_revision: round + 5, session_turn_id: `turn-${round}`, turn_index: round, turn_title: `用户的第 ${round} 次请求`, turn_created_at: `2026-10-13T0${round}:00:00Z`, source: 'AGENT_OUTPUT', kind: 'restore', repo_slug: repo, branch_name: `branch-${round}` },
})
const plugins = () => [createI18n({ legacy: false, locale: 'zh', messages: { zh } })]
it('shows the conversation and time, merges batches and retains each historical file for viewing and export', async () => {
  const entries = [backup(1, 'api'), backup(2, 'api'), backup(1, 'web'), backup(2, 'web', 'restore-again'), { ...backup(1, 'legacy'), operation_id: 'old', context: undefined, created_at: undefined }, { ...backup(2, 'api', 'restore-later'), sha256: 'later', created_at: '2026-10-13T02:30:00Z' }]
  const exportBackup = vi.fn()
  const controller = { listBackups: vi.fn().mockResolvedValue({ backups: entries }), exportBackup,
    state: ref({ binding_id: 'binding', repositories: [] }), local: ref({ task_id: 'task' }),
  } as unknown as LocalCollaboration
  const wrapper = mount(CollaborationBackups, { props: { controller }, global: { plugins: plugins() } })
  await flushPromises()
  const rounds = wrapper.findAll('.backup-round')
  expect(rounds.map(round => round.get('h3').text())).toEqual(['用户的第 2 次请求', '用户的第 1 次请求', '历史备份（未记录会话）'])
  expect(rounds[0]!.findAll('.backup-repository')).toHaveLength(2)
  expect(rounds[0]!.get('.round-header time').attributes('datetime')).toBe('2026-10-13T02:00:00Z')
  expect(rounds[0]!.findAll('.file-time')).toHaveLength(2)
  expect(rounds[1]!.findAll('h4').map(repo => repo.text())).toEqual(['api', 'web'])
  expect(wrapper.text()).not.toMatch(/批次|版本|快照|SHA|restore-|result-|会话 1|branch-/)
  expect(rounds[2]!.text()).toContain('未记录时间')
  const card = rounds[1]!.findAll('.backup-card')[1]!
  await card.findAll('button')[0]!.trigger('click')
  expect(wrapper.emitted('select')?.[0]).toEqual([entries[2]])
  await card.findAll('button')[1]!.trigger('click')
  expect(exportBackup).toHaveBeenCalledWith(entries[2])
  await rounds[0]!.get('.backup-card button').trigger('click')
  expect(wrapper.emitted('select')?.[1]).toEqual([entries[5]])
  wrapper.unmount()
})
it('falls back to the recorded turn or an unknown conversation without showing technical identifiers', async () => {
  const entry = backup(2, 'api'); delete entry.context!.session_turn_id; delete entry.context!.turn_index; delete entry.context!.turn_title
  const known = backup(1, 'api'); delete known.context!.turn_title
  const controller = { listBackups: vi.fn().mockResolvedValue({ backups: [entry, known] }), state: ref(null), local: ref(null) } as unknown as LocalCollaboration
  const wrapper = mount(CollaborationBackups, { props: { controller }, global: { plugins: plugins() } })
  await flushPromises()
  expect(wrapper.findAll('h3').map(heading => heading.text())).toEqual(['历史备份（未记录会话）', '第 1 轮对话'])
  expect(wrapper.text()).not.toContain('第 7 轮')
  wrapper.unmount()
})
