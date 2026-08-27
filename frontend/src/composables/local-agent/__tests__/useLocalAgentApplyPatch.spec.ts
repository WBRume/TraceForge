import { describe, expect, it, vi } from 'vitest'
import { applyProposalPatch } from '@/composables/local-agent/useLocalAgentApplyPatch'
import type { AgentTask, ChangeProposal } from '@/types/agent'
import type { SddDesktopApi } from '@/types/sddDesktop'

vi.mock('@/services/agentApi', () => ({
  submitApplyResult: vi.fn().mockResolvedValue({ proposal_id: 'proposal-1', status: 'applied' }),
  createConflictReport: vi.fn().mockResolvedValue({ id: 'conflict-1' }),
}))

const task: AgentTask = {
  id: 'task-1',
  workspace_id: 'ws-1',
  creator_id: 'user-1',
  name: 'Task',
  git_repo_url: 'https://github.com/acme/repo.git',
  status: 'DONE',
  created_at: '2026-01-01T00:00:00Z',
}

const proposal: ChangeProposal = {
  id: 'proposal-1',
  task_id: 'task-1',
  workspace_id: 'ws-1',
  proposal_no: 1,
  patch_set_no: 1,
  status: 'generated',
  base_repo_url: 'https://github.com/acme/repo.git',
  base_branch: 'main',
  base_commit_sha: 'base-sha',
  cloud_task_branch: 'task/task-1',
  changed_files_count: 1,
  insertions: 1,
  deletions: 0,
  created_at: '2026-01-01T00:00:00Z',
}

const createDesktop = (overrides: Partial<SddDesktopApi['git']> = {}): SddDesktopApi => ({
  platform: 'win32',
  git: {
    selectDirectory: vi.fn(),
    validateGitRepo: vi.fn().mockResolvedValue({ ok: true, stdout: '', stderr: '' }),
    getRemoteUrl: vi.fn().mockResolvedValue({ remoteUrl: 'git@github.com:acme/repo.git' }),
    getStatus: vi.fn().mockResolvedValue({ isClean: true, raw: '', entries: [], unmergedFiles: [] }),
    fetchOrigin: vi.fn().mockResolvedValue({ ok: true, stdout: '', stderr: '' }),
    checkoutBranch: vi.fn().mockResolvedValue({ ok: true, stdout: '', stderr: '' }),
    pullFfOnly: vi.fn().mockResolvedValue({ ok: true, stdout: '', stderr: '' }),
    createLocalBranch: vi.fn().mockResolvedValue({ ok: true, stdout: '', stderr: '' }),
    applyPatchWithThreeWay: vi.fn().mockResolvedValue({ ok: true, stdout: '', stderr: '', conflictedFiles: [] }),
    getHeadSha: vi.fn().mockResolvedValue({ headSha: 'base-sha' }),
    ...overrides,
  },
  process: {} as SddDesktopApi['process'],
  config: {} as SddDesktopApi['config'],
  system: {} as SddDesktopApi['system'],
  download: { save: vi.fn() },
})

describe('applyProposalPatch', () => {
  it('applies a clean patch on a local branch', async () => {
    const desktop = createDesktop()
    await applyProposalPatch({ desktop, task, proposal, repoPath: 'C:/repo', patchText: 'diff --git a/a b/a' })
    expect(desktop.git.fetchOrigin).toHaveBeenCalledWith('C:/repo')
    expect(desktop.git.createLocalBranch).toHaveBeenCalledWith('C:/repo', 'sdd/task-1/v1')
    expect(desktop.git.applyPatchWithThreeWay).toHaveBeenCalled()
  })

  it('stops before fetch when local worktree is dirty', async () => {
    const desktop = createDesktop({
      getStatus: vi.fn().mockResolvedValue({ isClean: false, raw: ' M x', entries: [{ code: 'M', path: 'x' }], unmergedFiles: [] }),
    })
    await expect(applyProposalPatch({ desktop, task, proposal, repoPath: 'C:/repo', patchText: 'patch' })).rejects.toThrow('未提交修改')
    expect(desktop.git.fetchOrigin).not.toHaveBeenCalled()
  })

  it('reports conflicts when git apply fails', async () => {
    const desktop = createDesktop({
      applyPatchWithThreeWay: vi.fn().mockResolvedValue({ ok: false, stdout: '', stderr: 'conflict', conflictedFiles: ['src/a.ts'] }),
    })
    const result = await applyProposalPatch({ desktop, task, proposal, repoPath: 'C:/repo', patchText: 'patch' })
    expect(result.status).toBe('conflict')
  })
})
