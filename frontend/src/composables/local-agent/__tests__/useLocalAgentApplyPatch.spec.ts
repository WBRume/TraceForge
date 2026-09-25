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
    preparePatchWorktree: vi.fn().mockResolvedValue({ path: 'C:/patch-worktree' }),
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
    expect(desktop.git.preparePatchWorktree).toHaveBeenCalledWith(expect.objectContaining({ repoPath: 'C:/repo', baseSha: proposal.base_commit_sha }))
    expect(desktop.git.fetchOrigin).not.toHaveBeenCalled()
    expect(desktop.git.checkoutBranch).not.toHaveBeenCalled()
    expect(desktop.git.applyPatchWithThreeWay).toHaveBeenCalledWith('C:/patch-worktree', 'diff --git a/a b/a')
  })

  it('uses a separate worktree even when the mapped fork has uncommitted edits', async () => {
    const desktop = createDesktop({
      getStatus: vi.fn().mockResolvedValue({ isClean: false, raw: ' M x', entries: [{ code: 'M', path: 'x' }], unmergedFiles: [] }),
    })
    await applyProposalPatch({ desktop, task, proposal, repoPath: 'C:/repo', patchText: 'patch' })
    expect(desktop.git.applyPatchWithThreeWay).toHaveBeenCalledWith('C:/patch-worktree', 'patch')
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

it('does not apply or fall back to branch checkout when the base commit is missing', async () => {
  const desktop = createDesktop({ preparePatchWorktree: vi.fn().mockRejectedValue(new Error('缺少补丁基准 commit')) })
  await expect(applyProposalPatch({ desktop, task, proposal, repoPath: 'C:/fork', patchText: 'patch' })).rejects.toThrow('基准 commit')
  expect(desktop.git.applyPatchWithThreeWay).not.toHaveBeenCalled()
  expect(desktop.git.checkoutBranch).not.toHaveBeenCalled()
})
