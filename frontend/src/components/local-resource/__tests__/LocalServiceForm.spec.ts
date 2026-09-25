import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import LocalServiceForm from '../LocalServiceForm.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import api from '@/utils/api'
import { readRepoPreferences, saveRepoPreferences } from '@/composables/localRepoPreferences'
import { useLocalServiceConnectionsStore } from '@/stores/localServiceConnections'
import { useLocalAgentStore } from '@/stores/localAgent'

const desktopMock = vi.hoisted(() => ({
  platform: 'win32',
  resources: {
    start: vi.fn(() => Promise.resolve({
      service_url: 'http://192.168.1.10:4096',
      resource_service_url: 'http://192.168.1.10:4098',
      host_token: 'auto-host-token',
      agent_token: 'auto-agent-token',
    })),
  },
  git: {
    selectDirectory: vi.fn(() => Promise.resolve({
      canceled: false,
      path: 'G:/auto-picked-workspace',
    })),
    validateGitRepo: vi.fn(() => Promise.resolve({ ok: true, stdout: '', stderr: '' })),
    getRemoteUrl: vi.fn(() => Promise.resolve({ remoteUrl: 'git@github.com:owner/repo.git' })),
    getStatus: vi.fn(() => Promise.resolve({ isClean: true })),
  },
  config: {
    getConfig: vi.fn(() => Promise.resolve({ serverUrl: 'http://localhost:8000', token: null })),
    getRepoMapping: vi.fn(() => Promise.resolve(null)),
  },
}))

vi.mock('@/utils/runtime', () => ({
  isElectron: () => true,
  getSddDesktop: () => desktopMock,
}))

vi.mock('@/utils/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
  DEFAULT_SERVER_URL: 'http://localhost:8000',
  setApiServerUrl: vi.fn(),
}))

describe('LocalServiceForm Component (Scheme 2: Stepper Flow with BaseSelect)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.spyOn(ElMessage, 'success').mockReturnValue({ close: vi.fn() })
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '新建本地服务', action: 'confirm' } as any)
    localStorage.clear()

    desktopMock.resources.start.mockImplementation(() => Promise.resolve({
      service_url: 'http://192.168.1.10:4096',
      resource_service_url: 'http://192.168.1.10:4098',
      host_token: 'auto-host-token',
      agent_token: 'auto-agent-token',
    }))
    desktopMock.git.selectDirectory.mockImplementation(() => Promise.resolve({
      canceled: false,
      path: 'G:/auto-picked-workspace',
    }))
    desktopMock.config.getConfig.mockImplementation(() => Promise.resolve({
      serverUrl: 'http://localhost:8000',
      token: null,
    }))
    desktopMock.config.getRepoMapping.mockImplementation(() => Promise.resolve(null))

    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url.includes('/agent-backends')) {
        return { data: { effective_agent_backend: 'opencode' } } as any
      }
      if (url.includes('/local-resources')) {
        return {
          data: {
            items: [
              {
                id: 'res-1',
                name: '现有主力配置',
                backend: 'opencode',
                service_url: 'http://192.168.1.10:4096',
                resource_service_url: 'http://192.168.1.10:4098',
                workspace_root: 'G:/workspaces',
                repositories_json: [
                  {
                    repository_id: 'repo-1',
                    configured_git_url: 'git@github.com:owner/repo.git',
                    local_path: 'G:/workspaces/repo',
                  },
                ],
                verification: { ready: true },
              },
            ],
            enabled: true,
          },
        } as any
      }
      if (url.includes('/workspaces/')) {
        return {
          data: {
            id: 'ws-123',
            name: '测试工作区',
            repositories: [
              { id: 'repo-1', repo_url: 'git@github.com:owner/repo.git' },
            ],
          },
        } as any
      }
      return { data: {} } as any
    })

    vi.mocked(api.post).mockResolvedValue({
      data: {
        ready: true,
        id: 'new-res-id',
        name: '新建本地服务',
      },
    } as any)
  })

  it('renders section title, BaseSelect dropdown, and initial Step 0', async () => {
    const wrapper = mount(LocalServiceForm, {
      props: { workspaceId: 'ws-123' },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('本地服务地址设置')
    expect(wrapper.text()).toContain('服务地址与网络')
    expect(wrapper.text()).toContain('工作区目录')
    expect(wrapper.text()).toContain('代码仓库映射')

    // BaseSelect should be present for profile switcher
    const select = wrapper.findComponent(BaseSelect)
    expect(select.exists()).toBe(true)

    // Step 0 inputs: profile name is prompted on save rather than rendered here
    expect(wrapper.find('#cfg-name').exists()).toBe(false)
    expect(wrapper.find('.btn-desktop-start').exists()).toBe(true)
    const serviceUrlInput = wrapper.find('#service-url')
    expect(serviceUrlInput.exists()).toBe(true)
  })

  it('switches between steps when clicking stepper buttons and clicking next button', async () => {
    const wrapper = mount(LocalServiceForm, {
      props: { workspaceId: 'ws-123' },
    })
    await flushPromises()

    const stepButtons = wrapper.findAll('.stepper-item')
    expect(stepButtons.length).toBe(3)

    expect(stepButtons[1].attributes('disabled')).toBeDefined()
    await wrapper.findAll('button').find(b => b.text() === '检测')!.trigger('click')
    await flushPromises()
    // Click Step 1: 工作区目录
    await stepButtons[1].trigger('click')
    expect(wrapper.find('#workspace-root').isVisible()).toBe(true)
    expect(wrapper.find('#host-token').isVisible()).toBe(false)

    // Click Step 2: 代码仓库映射
    await stepButtons[2].trigger('click')
    expect(wrapper.text()).toContain('代码仓库')
    expect(wrapper.find('.repo-card').exists()).toBe(true)

    // Click "上一步" to return to Step 1
    const prevBtn = wrapper.findAll('.btn-secondary').find(b => b.text().includes('上一步'))
    expect(prevBtn).toBeDefined()
    await prevBtn?.trigger('click')
    expect(wrapper.find('#workspace-root').isVisible()).toBe(true)
  })

  it('toggles password visibility for host and agent token', async () => {
    const wrapper = mount(LocalServiceForm, {
      props: { workspaceId: 'ws-123' },
    })
    await flushPromises()

    expect(wrapper.find('#host-token').isVisible()).toBe(true)
    expect(wrapper.find('#agent-token').isVisible()).toBe(true)

    const hostTokenInput = wrapper.find('#host-token')
    expect(hostTokenInput.attributes('type')).toBe('password')

    const toggleBtns = wrapper.findAll('.btn-affix-toggle')
    expect(toggleBtns.length).toBeGreaterThanOrEqual(1)
    await toggleBtns[0].trigger('click')

    expect(wrapper.find('#host-token').attributes('type')).toBe('text')
  })

  it('loads existing configuration when BaseSelect selects an item', async () => {
    saveRepoPreferences('ws-123', '', [{ repository_id: 'repo-1', configured_git_url: 'git@github.com:owner/repo.git', local_path: 'G:/workspaces/repo' }])
    const wrapper = mount(LocalServiceForm, {
      props: { workspaceId: 'ws-123' },
    })
    await flushPromises()

    const select = wrapper.findComponent(BaseSelect)
    await select.vm.$emit('update:modelValue', 'res-1')
    await flushPromises()

    // Form should populate with selected item values
    const serviceUrlInput = wrapper.find<HTMLInputElement>('#service-url')
    expect(serviceUrlInput.element.value).toBe('http://192.168.1.10:4096')

    const resourceUrlInput = wrapper.find<HTMLInputElement>('#resource-url')
    expect(resourceUrlInput.element.value).toBe('http://192.168.1.10:4098')

    await wrapper.findAll('button').find(b => b.text() === '检测')!.trigger('click')
    await flushPromises()
    expect(wrapper.get('.title-row .status-badge').text()).toBe('连接检测通过')
    expect(wrapper.text()).not.toContain('自检')
    await wrapper.find('#service-url').setValue('http://10.0.0.99:4096')
    expect(wrapper.get('.title-row .status-badge').text()).toBe('待检测连接')
  })

  it('starts services without a workspace directory or saving incomplete execution configuration', async () => {
    const wrapper = mount(LocalServiceForm, {
      props: { workspaceId: 'ws-123' },
    })
    await flushPromises()

    const startBtn = wrapper.find<HTMLButtonElement>('.btn-desktop-start')
    expect(startBtn.exists()).toBe(true)
    expect(startBtn.attributes('disabled')).toBeUndefined()

    // Click start button
    await startBtn.trigger('click')
    await flushPromises()

    expect(desktopMock.git.selectDirectory).not.toHaveBeenCalled()
    expect(desktopMock.resources.start).toHaveBeenCalledWith({ backend: 'opencode' })
    expect(api.post).toHaveBeenCalledWith('/workspaces/ws-123/local-resources/check-connection', expect.any(Object))
    expect(Object.values(useLocalServiceConnectionsStore().checked)[0]).toMatchObject({ host_token: 'auto-host-token' })
    expect(wrapper.find<HTMLInputElement>('#service-url').element.value).toBe('http://192.168.1.10:4096')
    expect(wrapper.text()).toContain('服务已启动')
  })

  it('submits form and emits saved event on save', async () => {
    const wrapper = mount(LocalServiceForm, {
      props: { workspaceId: 'ws-123' },
    })
    await flushPromises()
    await wrapper.findComponent(BaseSelect).vm.$emit('update:modelValue', '')
    await flushPromises()

    // Fill form
    await wrapper.find('#service-url').setValue('http://192.168.1.50:4096')
    await wrapper.find('#resource-url').setValue('http://192.168.1.50:4098')

    // Submit form
    if (wrapper.findAll('.stepper-item')[2].attributes('disabled') !== undefined) {
      await wrapper.findAll('button').find(b => b.text() === '检测')!.trigger('click')
      await flushPromises()
    }
    await wrapper.findAll('.stepper-item')[2].trigger('click')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(api.post).toHaveBeenCalled()
    expect(wrapper.emitted('saved')).toBeTruthy()
    expect(ElMessage.success).toHaveBeenCalledWith('本地服务配置已保存')
    expect(wrapper.get('[data-testid="save-feedback"]').text()).toBe('本地服务配置已保存')
    expect(wrapper.get('.title-row .status-badge').text()).toBe('连接检测通过')
    await wrapper.find('#service-url').setValue('http://192.168.1.51:4096')
    expect(wrapper.find('[data-testid="save-feedback"]').exists()).toBe(false)
  })
  it('reuses shared mappings without overwriting them when customizing a directory', async () => {
    saveRepoPreferences('ws-123', '', [{ repository_id: 'repo-1', configured_git_url: 'git@github.com:me/repo.git', local_path: 'G:/shared/repo' }])
    const wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    await flushPromises()
    await wrapper.findComponent(BaseSelect).vm.$emit('update:modelValue', '')
    await flushPromises()
    const path = wrapper.find<HTMLInputElement>('[data-testid="repo-path"]')
    expect(path.element.value).toBe('G:/shared/repo')
    expect(path.attributes('readonly')).toBeDefined()
    await wrapper.find('[data-testid="custom-repo"]').trigger('click')
    expect(path.attributes('readonly')).toBeUndefined()
    await path.setValue('G:/independent/repo')
    if (wrapper.findAll('.stepper-item')[2].attributes('disabled') !== undefined) {
      await wrapper.findAll('button').find(b => b.text() === '检测')!.trigger('click')
      await flushPromises()
    }
    await wrapper.findAll('.stepper-item')[2].trigger('click')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(vi.mocked(api.post).mock.calls.find(call => call[0] === '/workspaces/ws-123/local-resources')![1]).toMatchObject({ repositories: [{ local_path: 'G:/independent/repo' }] })
    expect(readRepoPreferences('ws-123', '')[0].local_path).toBe('G:/shared/repo')
    await wrapper.find('[data-testid="reuse-repo"]').trigger('click')
    expect(path.element.value).toBe('G:/shared/repo')
    wrapper.unmount()
  })

  it('synchronizes a missing mapping only when explicitly requested', async () => {
    const wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    await flushPromises()
    await wrapper.findComponent(BaseSelect).vm.$emit('update:modelValue', '')
    await flushPromises()
    expect(wrapper.text()).toContain('尚未设置本地仓库映射')
    await wrapper.find('[data-testid="repo-path"]').setValue('G:/new/repo')
    if (wrapper.findAll('.stepper-item')[2].attributes('disabled') !== undefined) {
      await wrapper.findAll('button').find(b => b.text() === '检测')!.trigger('click')
      await flushPromises()
    }
    await wrapper.findAll('.stepper-item')[2].trigger('click')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(readRepoPreferences('ws-123', '')).toEqual([])
    await wrapper.find('[data-testid="sync-repo"]').trigger('click')
    await flushPromises()
    expect(readRepoPreferences('ws-123', '')[0].local_path).toBe('G:/new/repo')
    expect(wrapper.find('[data-testid="repo-path"]').attributes('readonly')).toBeDefined()
    wrapper.unmount()
  })

  it('keeps a saved service-specific directory when opening a profile', async () => {
    saveRepoPreferences('ws-123', '', [{ repository_id: 'repo-1', configured_git_url: 'git@github.com:owner/repo.git', local_path: 'G:/shared/repo' }])
    const wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    await flushPromises()
    await wrapper.findComponent(BaseSelect).vm.$emit('update:modelValue', 'res-1')
    await flushPromises()
    expect(wrapper.find<HTMLInputElement>('[data-testid="repo-path"]').element.value).toBe('G:/workspaces/repo')
    expect(wrapper.find('[data-testid="repo-path"]').attributes('readonly')).toBeUndefined()
    expect(wrapper.find('[data-testid="reuse-repo"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('prefers Electron mappings over browser preferences', async () => {
    saveRepoPreferences('ws-123', '', [{ repository_id: 'repo-1', configured_git_url: 'git@github.com:owner/repo.git', local_path: 'G:/browser/repo' }])
    const spy = vi.spyOn(useLocalAgentStore(), 'mappingFor').mockReturnValue({ localPath: 'G:/desktop/repo' } as any)
    const wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    await flushPromises()
    await wrapper.findComponent(BaseSelect).vm.$emit('update:modelValue', '')
    await flushPromises()
    expect(wrapper.find<HTMLInputElement>('[data-testid="repo-path"]').element.value).toBe('G:/desktop/repo')
    wrapper.unmount()
    spy.mockRestore()
  })

  it('synchronizes Electron mappings through the validated desktop store', async () => {
    const config = desktopMock.config as typeof desktopMock.config & { setRepoMapping?: ReturnType<typeof vi.fn> }
    config.setRepoMapping = vi.fn()
    const store = useLocalAgentStore()
    let sharedPath = ''
    const mappingSpy = vi.spyOn(store, 'mappingFor').mockImplementation(() => sharedPath ? ({ localPath: sharedPath } as any) : null)
    const saveSpy = vi.spyOn(store, 'saveMappingFor').mockImplementation(async (_remote, path) => { sharedPath = path; return true })
    const wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    try {
      await flushPromises()
    await wrapper.findComponent(BaseSelect).vm.$emit('update:modelValue', '')
    await flushPromises()
      await wrapper.find('[data-testid="repo-path"]').setValue('G:/fork/repo')
      await flushPromises()
      await wrapper.find('[data-testid="sync-repo"]').trigger('click')
      await flushPromises()
      expect(saveSpy).toHaveBeenCalledWith('git@github.com:owner/repo.git', 'G:/fork/repo', null, 'git@github.com:owner/repo.git')
      expect(readRepoPreferences('ws-123', '')).toEqual([])
      expect(wrapper.find('[data-testid="repo-path"]').attributes('readonly')).toBeDefined()
    } finally {
      wrapper.unmount()
      mappingSpy.mockRestore()
      saveSpy.mockRestore()
      delete config.setRepoMapping
    }
  })

  it('only offers detection on the network tab and saving on the last step', async () => {
    const wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    await flushPromises()
    const buttons = () => wrapper.findAll('button').map(button => button.text())
    expect(buttons()).toContain('检测')
    expect(buttons()).toContain('一键启动并配置')
    expect(buttons().indexOf('一键启动并配置')).toBeGreaterThan(buttons().indexOf('检测'))
    expect(buttons()).not.toContain('保存配置')
    await wrapper.find('form').trigger('submit')
    expect(api.put).not.toHaveBeenCalled()
    await wrapper.findAll('button').find(b => b.text() === '检测')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('.stepper-item')[1].trigger('click')
    expect(wrapper.find('.btn-desktop-start').isVisible()).toBe(false)
    expect(buttons()).not.toContain('检测')
    expect(buttons()).not.toContain('保存配置')
    if (wrapper.findAll('.stepper-item')[2].attributes('disabled') !== undefined) {
      await wrapper.findAll('button').find(b => b.text() === '检测')!.trigger('click')
      await flushPromises()
    }
    await wrapper.findAll('.stepper-item')[2].trigger('click')
    expect(buttons()).not.toContain('检测')
    expect(buttons()).toContain('保存配置')
    wrapper.unmount()
  })

  it('checks unsaved addresses without saving or requiring directories', async () => {
    const wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    await flushPromises()
    await wrapper.findComponent(BaseSelect).vm.$emit('update:modelValue', '')
    await wrapper.find('#service-url').setValue('http://10.0.0.2:4096')
    await wrapper.find('#resource-url').setValue('http://10.0.0.2:4098')
    await wrapper.find('#host-token').setValue('draft-token')
    await wrapper.findAll('button').find(button => button.text() === '检测')!.trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.post).toHaveBeenCalledWith('/workspaces/ws-123/local-resources/check-connection', {
      resource_id: undefined, backend: 'opencode', service_url: 'http://10.0.0.2:4096',
      resource_service_url: 'http://10.0.0.2:4098', host_token: 'draft-token',
      agent_token: undefined, agent_username: 'opencode',
    })
    expect(api.put).not.toHaveBeenCalled()
    expect(wrapper.emitted('saved')).toBeUndefined()
    expect(wrapper.text()).toContain('服务地址与网络检测通过')
    expect(wrapper.get('.title-row .status-badge').text()).toBe('连接检测通过')
    await wrapper.find('#service-url').setValue('http://10.0.0.3:4096')
    expect(wrapper.text()).not.toContain('服务地址与网络检测通过')
    expect(wrapper.get('.title-row .status-badge').text()).toBe('待检测连接')
    expect(wrapper.findAll('.stepper-item')[1].attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
  it('does not unlock or cache a failed connection', async () => {
    const wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    await flushPromises()
    vi.mocked(api.post).mockRejectedValueOnce(new Error('unreachable'))
    await wrapper.findAll('button').find(b => b.text() === '检测')!.trigger('click')
    await flushPromises()
    expect(Object.keys(useLocalServiceConnectionsStore().checked)).toHaveLength(0)
    expect(wrapper.get('.title-row .status-badge').text()).toBe('连接检测失败')
    expect(wrapper.findAll('.stepper-item')[1].attributes('disabled')).toBeDefined()
    await wrapper.find('form').trigger('submit.prevent')
    expect(api.put).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('restores a checked connection from Pinia after remount without persisting credentials', async () => {
    let wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    await flushPromises()
    await wrapper.find('#host-token').setValue('only-in-pinia')
    await wrapper.findAll('button').find(b => b.text() === '检测')!.trigger('click')
    await flushPromises()
    wrapper.unmount()
    wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    await flushPromises()
    expect(wrapper.find<HTMLInputElement>('#host-token').element.value).toBe('only-in-pinia')
    expect(wrapper.findAll('.stepper-item')[1].attributes('disabled')).toBeUndefined()
    expect(JSON.stringify(localStorage)).not.toContain('only-in-pinia')
    await wrapper.setProps({ workspaceId: 'another-workspace' })
    await flushPromises()
    expect(wrapper.findAll('.stepper-item')[1].attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('ignores a successful check when the address changed during the request', async () => {
    const wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    await flushPromises()
    let resolveCheck!: (value: any) => void
    vi.mocked(api.post).mockImplementationOnce(() => new Promise(resolve => { resolveCheck = resolve }))
    await wrapper.findAll('button').find(b => b.text() === '检测')!.trigger('click')
    expect(wrapper.get('.title-row .status-badge').text()).toBe('连接检测中')
    await wrapper.find('#service-url').setValue('http://10.0.0.99:4096')
    resolveCheck({ data: { ready: true } })
    await flushPromises()
    expect(Object.keys(useLocalServiceConnectionsStore().checked)).toHaveLength(0)
    expect(wrapper.findAll('.stepper-item')[1].attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('shows save failure without reporting successful save or failed connection', async () => {
    const wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    await flushPromises()
    await wrapper.find('#host-token').setValue('replacement-token')
    await wrapper.findAll('button').find(b => b.text() === '检测')!.trigger('click')
    await flushPromises()
    await wrapper.findAll('.stepper-item')[2].trigger('click')
    vi.mocked(api.put).mockRejectedValueOnce(new Error('保存失败'))
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="save-feedback"]').exists()).toBe(false)
    expect(ElMessage.success).not.toHaveBeenCalled()
    expect(wrapper.emitted('saved')).toBeUndefined()
    expect(wrapper.get('.title-row .status-badge').text()).toBe('连接检测通过')
    wrapper.unmount()
  })

  it('prompts user for configuration profile name when saving and persists with the chosen name', async () => {
    const promptSpy = vi.spyOn(ElMessageBox, 'prompt').mockResolvedValueOnce({
      value: '定制开发工作站方案',
      action: 'confirm',
    } as any)

    const wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    await flushPromises()
    await wrapper.findComponent(BaseSelect).vm.$emit('update:modelValue', '')
    await flushPromises()

    await wrapper.find('#service-url').setValue('http://192.168.1.80:4096')
    await wrapper.find('#resource-url').setValue('http://192.168.1.80:4098')

    if (wrapper.findAll('.stepper-item')[2].attributes('disabled') !== undefined) {
      await wrapper.findAll('button').find(b => b.text() === '检测')!.trigger('click')
      await flushPromises()
    }
    await wrapper.findAll('.stepper-item')[2].trigger('click')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(promptSpy).toHaveBeenCalledWith(
      '请为当前本地服务配置方案命名：',
      '保存配置方案',
      expect.objectContaining({
        confirmButtonText: '保存配置',
        cancelButtonText: '取消',
        inputValue: '我的本地服务',
      }),
    )

    expect(api.post).toHaveBeenCalledWith(
      '/workspaces/ws-123/local-resources',
      expect.objectContaining({ name: '定制开发工作站方案' }),
    )
    expect(wrapper.emitted('saved')).toBeTruthy()
    wrapper.unmount()
  })

  it('aborts saving if user cancels the profile name prompt', async () => {
    vi.spyOn(ElMessageBox, 'prompt').mockRejectedValueOnce('cancel')

    const wrapper = mount(LocalServiceForm, { props: { workspaceId: 'ws-123' } })
    await flushPromises()
    await wrapper.findComponent(BaseSelect).vm.$emit('update:modelValue', '')
    await flushPromises()

    await wrapper.find('#service-url').setValue('http://192.168.1.80:4096')
    await wrapper.find('#resource-url').setValue('http://192.168.1.80:4098')

    if (wrapper.findAll('.stepper-item')[2].attributes('disabled') !== undefined) {
      await wrapper.findAll('button').find(b => b.text() === '检测')!.trigger('click')
      await flushPromises()
    }
    await wrapper.findAll('.stepper-item')[2].trigger('click')
    vi.mocked(api.post).mockClear()

    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    // api.post should NOT be called for resource saving
    const saveCalls = vi.mocked(api.post).mock.calls.filter(c => c[0] === '/workspaces/ws-123/local-resources')
    expect(saveCalls).toHaveLength(0)
    expect(wrapper.emitted('saved')).toBeUndefined()
    wrapper.unmount()
  })
})
