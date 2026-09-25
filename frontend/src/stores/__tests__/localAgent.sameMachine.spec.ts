import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useLocalAgentStore } from '@/stores/localAgent'
import { saveRepoPreferences, readRepoPreferences } from '@/composables/localRepoPreferences'

const { mockEnv, desktopMock } = vi.hoisted(() => {
  const mockEnv = { isElectron: false }
  const desktopMock = {
    platform: 'win32',
    git: {
      selectDirectory: vi.fn(),
      validateGitRepo: vi.fn(() => Promise.resolve({ ok: true, stdout: '', stderr: '' })),
      getRemoteUrl: vi.fn(),
      getStatus: vi.fn(() => Promise.resolve({ isClean: true })),
    },
    config: {
      getConfig: vi.fn(() => Promise.resolve({ serverUrl: 'http://localhost:8000', token: null })),
      getRepoMapping: vi.fn((_payload?: any) => Promise.resolve<any>(null)),
      setRepoMapping: vi.fn(() => Promise.resolve(true)),
      removeRepoMapping: vi.fn(() => Promise.resolve(true)),
    },
  }
  return { mockEnv, desktopMock }
})

vi.mock('@/utils/runtime', () => ({
  isElectron: () => mockEnv.isElectron,
  getSddDesktop: () => (mockEnv.isElectron ? desktopMock : null),
}))

vi.mock('@/utils/api', () => ({
  DEFAULT_SERVER_URL: 'http://localhost:8000',
  setApiServerUrl: vi.fn(),
}))

describe('localAgent store same machine environment auto-reuse', () => {
  beforeEach(() => {
    mockEnv.isElectron = false
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('automatically binds repository from local preferences on same machine without reconfiguration', async () => {
    const store = useLocalAgentStore()
    const workspaceId = 'ws-same-machine-1'
    const remoteUrl = 'https://github.com/org/repo-b.git'

    // Simulate preferences previously saved on this machine (e.g. from previous session)
    saveRepoPreferences(workspaceId, '', [
      {
        repository_id: 'repo-b',
        local_path: 'D:/workspace/repo-b',
        configured_git_url: 'https://github.com/org/repo-b.git',
      },
    ])

    await store.setWorkspaceContext({
      id: workspaceId,
      repositories: [
        {
          id: 'repo-b',
          repo_url: remoteUrl,
          repo_name: 'repo-b',
        },
      ],
    })

    const mapping = store.mappingFor(remoteUrl)
    expect(mapping).not.toBeNull()
    expect(mapping?.localPath).toBe('D:/workspace/repo-b')
    expect(store.repoReadyFor(remoteUrl)).toBe(true)
  })

  it('supports saving mapping in web mode and persists to local preferences for subsequent reloads', async () => {
    const store = useLocalAgentStore()
    const workspaceId = 'ws-same-machine-2'
    const remoteUrl = 'https://github.com/org/repo-c.git'

    await store.setWorkspaceContext({
      id: workspaceId,
      repositories: [
        {
          id: 'repo-c',
          repo_url: remoteUrl,
          repo_name: 'repo-c',
        },
      ],
    })

    expect(store.mappingFor(remoteUrl)).toBeNull()

    // User saves mapping in Web mode
    const success = await store.saveMappingFor(
      remoteUrl,
      'E:/local/repo-c',
      null,
      'https://github.com/my-fork/repo-c.git'
    )
    expect(success).toBe(true)

    // Verification: saved to preferences
    expect(readRepoPreferences(workspaceId, '')[0].local_path).toBe('E:/local/repo-c')

    // Re-initialize/reload store on same machine
    const newStore = useLocalAgentStore()
    await newStore.setWorkspaceContext({
      id: workspaceId,
      repositories: [
        {
          id: 'repo-c',
          repo_url: remoteUrl,
          repo_name: 'repo-c',
        },
      ],
    })

    const reloaded = newStore.mappingFor(remoteUrl)
    expect(reloaded).not.toBeNull()
    expect(reloaded?.localPath).toBe('E:/local/repo-c')
    expect(reloaded?.gitRemoteUrl).toBe('https://github.com/my-fork/repo-c.git')
  })

  it('syncs mapping from desktop config into local preferences when running on electron', async () => {
    mockEnv.isElectron = true
    const store = useLocalAgentStore()
    const workspaceId = 'ws-same-machine-3'
    const remoteUrl = 'https://github.com/org/repo-d.git'

    desktopMock.config.getRepoMapping.mockResolvedValueOnce({
      workspaceId,
      remoteUrl,
      localPath: 'F:/desktop-repo',
      gitRemoteUrl: 'https://github.com/org/repo-d.git',
      updatedAt: new Date().toISOString(),
    })

    await store.setWorkspaceContext({
      id: workspaceId,
      repositories: [
        {
          id: 'repo-d',
          repo_url: remoteUrl,
          repo_name: 'repo-d',
        },
      ],
    })

    // Mapping loaded in store
    expect(store.mappingFor(remoteUrl)?.localPath).toBe('F:/desktop-repo')
    // Synced to local preferences for same machine web access
    expect(readRepoPreferences(workspaceId, '')[0].local_path).toBe('F:/desktop-repo')
  })
})
