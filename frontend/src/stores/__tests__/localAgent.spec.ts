import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useLocalAgentStore } from '@/stores/localAgent'

const desktopMock = vi.hoisted(() => ({
  platform: 'win32',
  git: {
    selectDirectory: vi.fn(),
    validateGitRepo: vi.fn(),
    getRemoteUrl: vi.fn(),
    getStatus: vi.fn(),
    fetchOrigin: vi.fn(),
    checkoutBranch: vi.fn(),
    pullFfOnly: vi.fn(),
    createLocalBranch: vi.fn(),
    applyPatchWithThreeWay: vi.fn(),
    getHeadSha: vi.fn(),
  },
  process: {},
  config: {
    getConfig: vi.fn(),
    setConfig: vi.fn(),
    getRepoMapping: vi.fn(),
    setRepoMapping: vi.fn(),
    removeRepoMapping: vi.fn(),
  },
  system: {},
}))

vi.mock('@/utils/runtime', () => ({
  getSddDesktop: () => desktopMock,
  isElectron: () => true,
}))

vi.mock('@/utils/api', () => ({
  DEFAULT_SERVER_URL: 'http://localhost:8000',
  setApiServerUrl: vi.fn(),
}))

vi.mock('@/router', () => ({
  default: { push: vi.fn() },
}))

vi.mock('@/services/agentApi', () => ({
  createTaskChangeProposal: vi.fn().mockResolvedValue(null),
  getLatestChangeProposal: vi.fn().mockResolvedValue(null),
  listChangeProposalFiles: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  downloadChangeProposalPatch: vi.fn().mockResolvedValue(''),
}))

describe('localAgent store workspace repo mapping', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    desktopMock.config.getConfig.mockResolvedValue({
      serverUrl: 'http://localhost:8000',
      token: null,
      onboardingCompleted: false,
      repoMappings: {},
    })
    desktopMock.config.getRepoMapping.mockImplementation(async ({ workspaceId }: { workspaceId: string }) => {
      if (workspaceId === 'ws-1') {
        return {
          workspaceId: 'ws-1',
          remoteUrl: 'https://github.com/acme/one.git',
          localPath: 'C:/repos/one',
          updatedAt: '2026-01-01T00:00:00Z',
        }
      }
      if (workspaceId === 'ws-2') {
        return {
          workspaceId: 'ws-2',
          remoteUrl: 'https://github.com/acme/two.git',
          localPath: 'C:/repos/two',
          updatedAt: '2026-01-01T00:00:00Z',
        }
      }
      return null
    })
    desktopMock.git.validateGitRepo.mockResolvedValue({ ok: true, stdout: '', stderr: '' })
    desktopMock.git.getRemoteUrl.mockImplementation(async (repoPath: string) => ({
      remoteUrl: repoPath.endsWith('/one')
        ? 'https://github.com/acme/one.git'
        : 'https://github.com/acme/two.git',
    }))
    desktopMock.git.getStatus.mockResolvedValue({ isClean: true, raw: '', entries: [], unmergedFiles: [] })
    desktopMock.config.removeRepoMapping.mockResolvedValue({ removed: true })
  })

  it('clears task context before loading workspace-level repo mappings', async () => {
    const store = useLocalAgentStore()

    await store.setTaskContext(
      {
        id: 'task-1',
        workspace_id: 'ws-1',
        git_repo_url: 'https://github.com/acme/one.git',
      },
      { id: 'ws-1', git_repo_url: 'https://github.com/acme/one.git' },
    )

    expect(store.workspaceId).toBe('ws-1')
    expect(store.repoPath).toBe('C:/repos/one')

    await store.setWorkspaceContext({ id: 'ws-2', git_repo_url: 'https://github.com/acme/two.git' })

    expect(store.task).toBeNull()
    expect(store.workspaceId).toBe('ws-2')
    expect(store.expectedRemoteUrl).toBe('https://github.com/acme/two.git')
    expect(store.repoPath).toBe('C:/repos/two')
    expect(desktopMock.config.getRepoMapping).toHaveBeenLastCalledWith({
      workspaceId: 'ws-2',
      remoteUrl: 'https://github.com/acme/two.git',
    })
  })

  it('resets repo state when workspace has no GitHub repository URL', async () => {
    const store = useLocalAgentStore()

    await store.setWorkspaceContext({ id: 'ws-1', git_repo_url: 'https://github.com/acme/one.git' })
    expect(store.repoPath).toBe('C:/repos/one')

    await store.setWorkspaceContext({ id: 'ws-empty', git_repo_url: '' })

    expect(store.expectedRemoteUrl).toBe('')
    expect(store.repoPath).toBe('')
    expect(store.repoMapping).toBeNull()
  })

  it('binds a personal fork to the server repository even when remote URLs differ and the tree is dirty', async () => {
    const server = 'https://github.com/LiZheng0613/sdd-tdd-workflow.git'
    desktopMock.config.getRepoMapping.mockResolvedValue(null)
    desktopMock.config.setRepoMapping.mockImplementation(async (payload) => ({ ...payload, updatedAt: 'now' }))
    desktopMock.git.getRemoteUrl.mockResolvedValue({ remoteUrl: 'https://github.com/WBRume/sdd-tdd-workflow.git' })
    desktopMock.git.getStatus.mockResolvedValue({ isClean: false, raw: ' M code.ts', entries: [], unmergedFiles: [] })
    const store = useLocalAgentStore()
    await store.setWorkspaceContext({ id: 'ws-fork', git_repo_url: server })
    expect(await store.saveMappingFor(server, 'G:/proj/sdd-tdd-workflow')).toBe(true)
    expect(desktopMock.config.setRepoMapping).toHaveBeenCalledWith(expect.objectContaining({ remoteUrl: server, localPath: 'G:/proj/sdd-tdd-workflow' }))
    expect(store.repoReadyFor(server)).toBe(true)
    expect(store.statusFor(server)).toContain('WBRume')
  })

  it('still rejects a non-Git directory before saving a mapping', async () => {
    const store = useLocalAgentStore()
    await store.setWorkspaceContext({ id: 'ws-1', git_repo_url: 'https://github.com/acme/one.git' })
    desktopMock.git.validateGitRepo.mockResolvedValue({ ok: false, stdout: '', stderr: 'not a repository' })
    expect(await store.saveMappingFor('https://github.com/acme/one.git', 'C:/not-git')).toBe(false)
    expect(desktopMock.config.setRepoMapping).not.toHaveBeenCalled()
  })

  it('removes the current workspace repo mapping only', async () => {
    const store = useLocalAgentStore()

    await store.setWorkspaceContext({ id: 'ws-1', git_repo_url: 'https://github.com/acme/one.git' })
    expect(store.repoPath).toBe('C:/repos/one')

    await store.removeRepoMapping()

    expect(desktopMock.config.removeRepoMapping).toHaveBeenCalledWith({
      workspaceId: 'ws-1',
      remoteUrl: 'https://github.com/acme/one.git',
    })
    expect(store.repoPath).toBe('')
    expect(store.repoMapping).toBeNull()
  })
})
