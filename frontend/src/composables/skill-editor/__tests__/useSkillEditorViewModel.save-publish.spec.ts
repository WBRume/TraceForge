import { beforeEach, describe, expect, it } from 'vitest'
import { apiMock, elMessageErrorMock, elMessageSuccessMock, flushAll, mockEditModeApi, mountSkillEditorVm, resetHarnessState, routeState, routerState, workspaceStore } from './harness'

describe('useSkillEditorViewModel save/publish/restore', () => {
  beforeEach(() => {
    resetHarnessState({ mode: 'new' })
  })

  it('saves new skill with entry_file_path and initial_entries payload', async () => {
    resetHarnessState({ mode: 'new', workspaceId: 'ws-1' })
    const { vm, wrapper } = await mountSkillEditorVm()

    vm.createNode('directory')
    vm.createNodeParentPath = ''
    vm.createNodeName = 'docs'
    await vm.confirmCreateNode()
    await flushAll()

    vm.createNode('file')
    vm.createNodeParentPath = 'docs'
    vm.createNodeName = 'main.md'
    await vm.confirmCreateNode()
    await flushAll()

    vm.activeFileContent = '# Entry'
    vm.form.name = 'new-skill'
    vm.form.dimension = 'WORKSPACE'
    vm.form.workspaceId = 'ws-1'
    vm.form.entryFilePath = 'docs/main.md'

    apiMock.post.mockImplementation(async (url: string) => {
      if (String(url).endsWith('/skills')) {
        return { data: { id: 'skill-created' } }
      }
      return { data: {} }
    })

    await vm.saveSkill()
    await flushAll()

    const createCall = apiMock.post.mock.calls.find(([url]) => String(url).endsWith('/skills'))
    expect(createCall).toBeTruthy()
    const payload = createCall?.[1] as {
      entry_file_path: string
      initial_entries: Array<{ path: string, node_type: string }>
    }
    expect(payload.entry_file_path).toBe('docs/main.md')
    expect(payload.initial_entries.some(item => item.path === 'docs/main.md' && item.node_type === 'file')).toBe(true)
    expect(routerState.replace).toHaveBeenCalled()

    wrapper.unmount()
  })

  it('imports skill from github when source mode is github', async () => {
    resetHarnessState({ mode: 'new', workspaceId: 'ws-1' })
    const { vm, wrapper } = await mountSkillEditorVm()

    vm.form.sourceMode = 'github'
    vm.form.githubRepoUrl = 'https://github.com/openai/sample-skills'
    vm.form.githubSkillName = 'frontend-testing-skill'
    vm.form.dimension = 'WORKSPACE'
    vm.form.workspaceId = 'ws-1'
    vm.form.description = 'imported skill'
    vm.form.followOfficialSource = true

    apiMock.post.mockImplementation(async (url: string) => {
      if (String(url).endsWith('/skills/import/github')) {
        return { data: { id: 'skill-imported' } }
      }
      return { data: {} }
    })

    await vm.saveSkill()
    await flushAll()

    const importCall = apiMock.post.mock.calls.find(([url]) => String(url).endsWith('/skills/import/github'))
    expect(importCall).toBeTruthy()
    const payload = importCall?.[1] as {
      repo_url: string
      skill_name: string
      dimension: string
      workspace_id: string | null
      description: string | null
      follow_official_source: boolean
    }
    expect(payload.repo_url).toBe('https://github.com/openai/sample-skills')
    expect(payload.skill_name).toBe('frontend-testing-skill')
    expect(payload.dimension).toBe('WORKSPACE')
    expect(payload.workspace_id).toBe('ws-1')
    expect(payload.description).toBe('imported skill')
    expect(payload.follow_official_source).toBe(true)
    expect(routerState.replace).toHaveBeenCalled()
    expect(routerState.replace.mock.calls[0]?.[0]?.query?.readonly).toBe('1')

    wrapper.unmount()
  })

  it('waits for queued github skill import and opens imported skill', async () => {
    resetHarnessState({ mode: 'new', workspaceId: 'ws-1' })
    const { vm, wrapper } = await mountSkillEditorVm()

    vm.form.sourceMode = 'github'
    vm.form.githubRepoUrl = 'https://github.com/openai/sample-skills'
    vm.form.githubSkillName = 'frontend-testing-skill'
    vm.form.dimension = 'WORKSPACE'
    vm.form.workspaceId = 'ws-1'

    apiMock.post.mockImplementation(async (url: string) => {
      if (String(url).endsWith('/skills/import/github')) {
        return { data: { job_id: 'job-import-1', status: 'PENDING', job_type: 'IMPORT_SKILL' } }
      }
      return { data: {} }
    })
    apiMock.get.mockImplementation(async (url: string) => {
      if (String(url).endsWith('/provision-jobs/job-import-1')) {
        return {
          data: {
            job_id: 'job-import-1',
            job_type: 'IMPORT_SKILL',
            status: 'SUCCESS',
            progress: 100,
            stage: 'COMPLETED',
            result_json: { skill_id: 'skill-imported-async' },
          },
        }
      }
      return { data: {} }
    })

    await vm.saveSkill()
    await flushAll()

    expect(apiMock.get).toHaveBeenCalledWith('/provision-jobs/job-import-1')
    expect(routerState.replace).toHaveBeenCalledWith({
      name: 'skillsEdit',
      params: { skillId: 'skill-imported-async' },
      query: { wsId: 'ws-1' },
    })

    wrapper.unmount()
  })

  it('keeps official source skills read-only and syncs from the source endpoint', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-official', workspaceId: 'ws-1' })
    mockEditModeApi({
      skillId: 'skill-official',
      detail: {
        source_type: 'GITHUB_OFFICIAL',
        source_repo_url: 'https://github.com/openai/sample-skills',
        source_skill_name: 'frontend-testing-skill',
        source_subdir: 'skills/frontend-testing-skill',
        source_locked: true,
        source_commit_sha: 'abc123',
        source_last_synced_at: '2026-04-16T10:00:00Z',
      },
    })
    const { vm, wrapper } = await mountSkillEditorVm()

    expect(vm.isOfficialSourceSkill).toBe(true)
    expect(vm.isReadOnly).toBe(true)
    expect(vm.canSwitchToEdit).toBe(false)
    expect(vm.canSave).toBe(false)
    expect(vm.canPublish).toBe(false)
    expect(vm.canSyncOfficialSource).toBe(true)

    apiMock.post.mockClear()
    apiMock.post.mockResolvedValueOnce({
      data: {
        source_type: 'GITHUB_OFFICIAL',
        source_locked: true,
        source_repo_url: 'https://github.com/openai/sample-skills',
      },
    })

    await vm.syncOfficialSource()
    await flushAll()

    const syncCall = apiMock.post.mock.calls.find(([url]) => String(url).includes('/skills/skill-official/source/sync'))
    expect(syncCall).toBeTruthy()
    expect(elMessageSuccessMock).toHaveBeenCalledWith('skills.editor.sync_official_source_no_changes')

    wrapper.unmount()
  })

  it('validates github import fields in github source mode', async () => {
    resetHarnessState({ mode: 'new', workspaceId: 'ws-1' })
    const { vm, wrapper } = await mountSkillEditorVm()

    vm.form.sourceMode = 'github'
    vm.form.dimension = 'WORKSPACE'
    vm.form.workspaceId = 'ws-1'
    vm.form.name = ''
    vm.form.githubRepoUrl = ''
    vm.form.githubSkillName = ''

    apiMock.post.mockClear()
    await vm.saveSkill()
    await flushAll()

    expect(apiMock.post).not.toHaveBeenCalled()
    expect(vm.formErrors.githubRepoUrl).toBe(true)
    expect(vm.formErrors.githubSkillName).toBe(true)
    expect(vm.formErrors.name).toBeUndefined()

    wrapper.unmount()
  })

  it('uses github source mode when route query source=github', async () => {
    resetHarnessState({ mode: 'new', workspaceId: 'ws-1' })
    routeState.query = {
      ...routeState.query,
      source: 'github',
    }

    const { vm, wrapper } = await mountSkillEditorVm()

    expect(vm.form.sourceMode).toBe('github')
    expect(vm.isGithubImportMode).toBe(true)

    wrapper.unmount()
  })

  it('saves edited skill by patching metadata and persisting dirty files', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1' })
    mockEditModeApi()
    const { vm, wrapper } = await mountSkillEditorVm()

    apiMock.patch.mockClear()
    apiMock.put.mockClear()

    vm.form.name = 'Skill A Updated'
    vm.activeFileContent = 'updated markdown'
    await flushAll()
    expect(vm.dirtyFiles).toContain('SKILL.md')

    await vm.saveSkill()
    await flushAll()

    const patchCall = apiMock.patch.mock.calls.find(([url]) => String(url).includes('/skills/skill-1'))
    expect(patchCall).toBeTruthy()

    const putCall = apiMock.put.mock.calls.find(([url]) => String(url).includes('/skills/skill-1/files/content'))
    expect(putCall).toBeTruthy()
    expect((putCall?.[1] as { path: string }).path).toBe('SKILL.md')

    wrapper.unmount()
  })

  it('switches editor workspace scope immediately after moving a skill', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1' })
    workspaceStore.workspaces = [
      { id: 'ws-1', name: 'Workspace 1' },
      { id: 'ws-2', name: 'Workspace 2' },
    ]
    mockEditModeApi()
    const { vm, wrapper } = await mountSkillEditorVm()

    let ownerWorkspaceId = 'ws-1'
    const getCallsAfterPatch: Array<{ url: string, workspaceId: string }> = []

    apiMock.patch.mockImplementation(async (_url: string, payload: { workspace_id?: string | null }) => {
      ownerWorkspaceId = String(payload.workspace_id || '')
      return {
        data: {
          id: 'skill-1',
          name: vm.form.name,
          description: vm.form.description,
          dimension: 'WORKSPACE',
          workspace_id: ownerWorkspaceId,
          entry_file_path: vm.form.entryFilePath,
          can_manage: true,
          latest_version_no: 2,
        },
      }
    })
    apiMock.get.mockImplementation(async (url: string, config?: { params?: Record<string, unknown> }) => {
      getCallsAfterPatch.push({
        url,
        workspaceId: String(config?.params?.workspace_id || ''),
      })
      if (url.endsWith('/skills/skill-1')) {
        return {
          data: {
            id: 'skill-1',
            name: 'Skill A',
            description: 'Skill desc',
            dimension: 'WORKSPACE',
            workspace_id: ownerWorkspaceId,
            entry_file_path: 'SKILL.md',
            can_manage: true,
            average_score: null,
            review_count: 0,
            my_score: null,
            can_review: true,
            latest_version_no: 2,
          },
        }
      }
      if (url.endsWith('/skills/skill-1/reviews/overview')) {
        return {
          data: {
            average_score: null,
            review_count: 0,
            my_score: null,
            my_note: null,
            can_review: true,
            current_version_no: 2,
          },
        }
      }
      if (url.endsWith('/skills/skill-1/versions/pending')) {
        return { data: { has_pending_changes: false, changed_files_count: 0 } }
      }
      if (url.endsWith('/skills/skill-1/files/tree')) {
        return { data: { nodes: [{ path: 'SKILL.md', name: 'SKILL.md', node_type: 'file', children: [] }] } }
      }
      if (url.endsWith('/skills/skill-1/analyses/latest')) {
        return { data: null }
      }
      return { data: {} }
    })

    apiMock.patch.mockClear()
    apiMock.get.mockClear()
    routerState.replace.mockClear()

    vm.form.workspaceId = 'ws-2'
    await vm.saveSkill()
    await flushAll()

    const patchCall = apiMock.patch.mock.calls.find(([url]) => String(url).includes('/skills/skill-1'))
    expect(patchCall).toBeTruthy()
    expect((patchCall?.[1] as { workspace_id: string }).workspace_id).toBe('ws-2')
    expect((patchCall?.[2] as { params?: { workspace_id?: string } }).params?.workspace_id).toBe('ws-1')
    expect(vm.selectedWorkspaceId).toBe('ws-2')
    expect(routerState.replace).toHaveBeenCalledWith({
      path: routeState.path,
      query: { ...routeState.query, wsId: 'ws-2' },
    })
    expect(getCallsAfterPatch.some(call => call.workspaceId === 'ws-1')).toBe(false)
    expect(getCallsAfterPatch.some(call => call.workspaceId === 'ws-2')).toBe(true)
    expect(elMessageErrorMock).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('uses the updated workspace scope for the next ownership change', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1' })
    workspaceStore.workspaces = [
      { id: 'ws-1', name: 'Workspace 1' },
      { id: 'ws-2', name: 'Workspace 2' },
    ]
    mockEditModeApi()
    const { vm, wrapper } = await mountSkillEditorVm()

    let ownerWorkspaceId = 'ws-1'
    apiMock.patch.mockImplementation(async (_url: string, payload: { workspace_id?: string | null }) => {
      ownerWorkspaceId = String(payload.workspace_id || '')
      return {
        data: {
          id: 'skill-1',
          name: vm.form.name,
          description: vm.form.description,
          dimension: 'WORKSPACE',
          workspace_id: ownerWorkspaceId,
          entry_file_path: vm.form.entryFilePath,
          can_manage: true,
          latest_version_no: 2,
        },
      }
    })
    apiMock.get.mockImplementation(async (url: string) => {
      if (url.endsWith('/skills/skill-1')) {
        return {
          data: {
            id: 'skill-1',
            name: 'Skill A',
            description: 'Skill desc',
            dimension: 'WORKSPACE',
            workspace_id: ownerWorkspaceId,
            entry_file_path: 'SKILL.md',
            can_manage: true,
            average_score: null,
            review_count: 0,
            my_score: null,
            can_review: true,
            latest_version_no: 2,
          },
        }
      }
      if (url.endsWith('/skills/skill-1/reviews/overview')) {
        return { data: { average_score: null, review_count: 0, my_score: null, my_note: null, can_review: true, current_version_no: 2 } }
      }
      if (url.endsWith('/skills/skill-1/versions/pending')) {
        return { data: { has_pending_changes: false, changed_files_count: 0 } }
      }
      if (url.endsWith('/skills/skill-1/files/tree')) {
        return { data: { nodes: [{ path: 'SKILL.md', name: 'SKILL.md', node_type: 'file', children: [] }] } }
      }
      if (url.endsWith('/skills/skill-1/analyses/latest')) {
        return { data: null }
      }
      return { data: {} }
    })

    apiMock.patch.mockClear()
    vm.form.workspaceId = 'ws-2'
    await vm.saveSkill()
    await flushAll()

    vm.form.workspaceId = 'ws-1'
    await vm.saveSkill()
    await flushAll()

    expect(apiMock.patch).toHaveBeenCalledTimes(2)
    const secondPatchCall = apiMock.patch.mock.calls[1]
    expect((secondPatchCall?.[1] as { workspace_id: string }).workspace_id).toBe('ws-1')
    expect((secondPatchCall?.[2] as { params?: { workspace_id?: string } }).params?.workspace_id).toBe('ws-2')
    expect(vm.selectedWorkspaceId).toBe('ws-1')
    expect(ownerWorkspaceId).toBe('ws-1')
    expect(elMessageErrorMock).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('publishes by persisting dirty worktree changes first and then creating commit version', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1' })
    mockEditModeApi()
    const { vm, wrapper } = await mountSkillEditorVm()

    vm.activeFileContent = 'dirty-before-publish'
    await flushAll()

    expect(vm.canPublish).toBe(true)
    vm.openPublishConfirm()
    expect(vm.showPublishConfirm).toBe(true)
    vm.pendingPublishNote = 'publish note'

    apiMock.put.mockClear()
    apiMock.post.mockClear()

    await vm.confirmPublish()
    await flushAll()

    const persistCall = apiMock.put.mock.calls.find(([url]) => String(url).includes('/files/content'))
    expect(persistCall).toBeTruthy()

    const commitCall = apiMock.post.mock.calls.find(([url]) => String(url).includes('/versions/commit'))
    expect(commitCall).toBeTruthy()
    expect((commitCall?.[1] as { change_note: string }).change_note).toBe('publish note')

    const persistOrder = apiMock.put.mock.invocationCallOrder[0]
    const commitOrder = apiMock.post.mock.invocationCallOrder.find((_, index) => String(apiMock.post.mock.calls[index]?.[0]).includes('/versions/commit'))
    expect(persistOrder).toBeLessThan(Number(commitOrder))

    expect(vm.showPublishConfirm).toBe(false)
    expect(vm.pendingPublishNote).toBe('')

    wrapper.unmount()
  })

  it('restores selected historical version and reloads latest', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1' })
    mockEditModeApi()
    const { vm, wrapper } = await mountSkillEditorVm()

    vm.viewVersionId = 'ver-1'
    await flushAll()
    expect(vm.canRestoreSelectedVersion).toBe(true)

    apiMock.post.mockClear()
    await vm.confirmRestoreVersion()
    await flushAll()

    const restoreCall = apiMock.post.mock.calls.find(([url]) => String(url).includes('/versions/ver-1/restore'))
    expect(restoreCall).toBeTruthy()
    expect(vm.contentViewMode).toBe('edit')

    wrapper.unmount()
  })
})
