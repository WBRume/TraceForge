import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import RepoMappingRow from '../RepoMappingRow.vue'
import LocalGitRemoteSelect from '../LocalGitRemoteSelect.vue'
import { useLocalAgentStore } from '@/stores/localAgent'
import { normalizeRemoteUrl } from '@/composables/local-agent/localAgentUtils'

const { mockEnv, desktopMock } = vi.hoisted(() => {
  const mockEnv = { isElectron: true }
  const desktopMock = {
    platform: 'win32',
    git: {
      selectDirectory: vi.fn(),
      validateGitRepo: vi.fn(() => Promise.resolve({ ok: true, stdout: '', stderr: '' })),
      getRemoteUrl: vi.fn(() => Promise.resolve({ remoteUrl: 'git@github.com:owner/repo.git' })),
      getStatus: vi.fn(() => Promise.resolve({ isClean: true })),
    },
    config: {
      getConfig: vi.fn(() => Promise.resolve({ serverUrl: 'http://localhost:8000', token: null })),
      getRepoMapping: vi.fn(() => Promise.resolve(null)),
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

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

describe('RepoMappingRow Component', () => {
  beforeEach(() => {
    mockEnv.isElectron = true
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('does NOT display or allow editing Git remote select when no repository path is chosen', async () => {
    const wrapper = mount(RepoMappingRow, {
      props: {
        remoteUrl: 'git@github.com:owner/repo.git',
        repoName: 'repo',
      },
      global: {
        mocks: {
          $t: (key: string) => key,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).not.toContain('映射使用的 Git 远端')
    expect(wrapper.find('.repo-row-remote-select-label').exists()).toBe(false)
    expect(wrapper.findComponent(LocalGitRemoteSelect).exists()).toBe(false)

    wrapper.unmount()
  })

  it('displays Git remote select when repository path is bound in store', async () => {
    const store = useLocalAgentStore()
    const remoteUrl = 'git@github.com:owner/repo.git'
    store.repoMappings[normalizeRemoteUrl(remoteUrl)] = {
      workspaceId: 'ws-1',
      remoteUrl,
      localPath: 'G:/projects/repo',
      gitRemoteUrl: 'git@github.com:owner/repo.git',
      updatedAt: new Date().toISOString(),
    }

    const wrapper = mount(RepoMappingRow, {
      props: {
        remoteUrl,
        repoName: 'repo',
      },
      global: {
        mocks: {
          $t: (key: string) => key,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('映射使用的 Git 远端')
    expect(wrapper.find('.repo-row-remote-select-label').exists()).toBe(true)
    expect(wrapper.findComponent(LocalGitRemoteSelect).exists()).toBe(true)

    wrapper.unmount()
  })

  it('reveals Git remote select after choosing a directory and hides it on unlink', async () => {
    desktopMock.git.selectDirectory.mockResolvedValueOnce({
      canceled: false,
      path: 'G:/new-repo-path',
    })

    const remoteUrl = 'git@github.com:owner/repo.git'
    const wrapper = mount(RepoMappingRow, {
      props: {
        remoteUrl,
        repoName: 'repo',
      },
      global: {
        mocks: {
          $t: (key: string) => key,
        },
      },
    })
    await flushPromises()

    // Initially hidden
    expect(wrapper.findComponent(LocalGitRemoteSelect).exists()).toBe(false)
    expect(wrapper.find('.repo-row-remote-select-label').exists()).toBe(false)

    // User clicks choose folder button
    const chooseBtn = wrapper.find('.btn-icon')
    await chooseBtn.trigger('click')
    await flushPromises()

    // After picking directory, Git remote select is displayed
    expect(wrapper.find('.repo-row-remote-select-label').exists()).toBe(true)
    expect(wrapper.findComponent(LocalGitRemoteSelect).exists()).toBe(true)

    // User clicks remove mapping (unlink button) if bound, or simulated
    const store = useLocalAgentStore()
    store.repoMappings[normalizeRemoteUrl(remoteUrl)] = {
      workspaceId: 'ws-1',
      remoteUrl,
      localPath: 'G:/new-repo-path',
      gitRemoteUrl: 'git@github.com:owner/repo.git',
      updatedAt: new Date().toISOString(),
    }
    await flushPromises()

    const removeBtn = wrapper.find('.btn-secondary.danger')
    expect(removeBtn.exists()).toBe(true)
    await removeBtn.trigger('click')
    await flushPromises()

    // After unlinking, localPath is cleared and remote select is hidden again
    expect(wrapper.find('.repo-row-remote-select-label').exists()).toBe(false)
    expect(wrapper.findComponent(LocalGitRemoteSelect).exists()).toBe(false)
    expect(wrapper.emitted('changed')).toBeTruthy()

    wrapper.unmount()
  })

  it('supports typing path and saving mapping in web environment without electron', async () => {
    mockEnv.isElectron = false
    const store = useLocalAgentStore()
    await store.setWorkspaceContext({ id: 'ws-web', git_repo_url: 'git@github.com:owner/web-repo.git' })

    const remoteUrl = 'git@github.com:owner/web-repo.git'
    const wrapper = mount(RepoMappingRow, {
      props: {
        remoteUrl,
        repoName: 'web-repo',
      },
      global: {
        mocks: {
          $t: (key: string) => key,
        },
      },
    })
    await flushPromises()

    const input = wrapper.find('input.mgmt-input')
    expect(input.attributes('readonly')).toBeUndefined()

    // Type path directly
    await input.setValue('G:/web-repo-path')
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.find('.repo-row-remote-select-label').exists()).toBe(true)
    expect(wrapper.findComponent(LocalGitRemoteSelect).exists()).toBe(true)

    // Save mapping button should be enabled and clickable in web mode
    const saveBtn = wrapper.findAll('.btn-primary.action-button').at(0)
    expect(saveBtn?.attributes('disabled')).toBeUndefined()
    await saveBtn?.trigger('click')
    await flushPromises()

    expect(store.mappingFor(remoteUrl)?.localPath).toBe('G:/web-repo-path')
    expect(wrapper.emitted('changed')).toBeTruthy()

    wrapper.unmount()
  })
})
