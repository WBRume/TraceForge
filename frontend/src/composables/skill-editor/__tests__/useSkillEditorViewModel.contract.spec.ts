import { beforeEach, describe, expect, it } from 'vitest'
import { apiMock, mockEditModeApi, mountSkillEditorVm, resetHarnessState, routerState } from './harness'

describe('useSkillEditorViewModel contract', () => {
  beforeEach(() => {
    resetHarnessState({ mode: 'new' })
  })

  it('exposes core facade fields and methods for component contract', async () => {
    const { vm, wrapper } = await mountSkillEditorVm()

    expect(vm).toHaveProperty('form')
    expect(vm).toHaveProperty('fileTree')
    expect(vm).toHaveProperty('versions')
    expect(vm).toHaveProperty('reviewOverview')
    expect(vm).toHaveProperty('activeFileContent')
    expect(vm).toHaveProperty('saveSkill')
    expect(vm).toHaveProperty('confirmPublish')
    expect(vm).toHaveProperty('confirmRestoreVersion')
    expect(vm).toHaveProperty('loadDirectoryDiff')
    expect(vm).toHaveProperty('loadFileDiff')
    expect(vm).toHaveProperty('submitRating')
    expect(vm).toHaveProperty('submitComment')
    expect(vm).toHaveProperty('handleEditorMount')
    expect(vm).toHaveProperty('toggleRightDrawer')
    expect(vm).toHaveProperty('openDrawerFile')
    expect(vm).toHaveProperty('activeEditorTab')
    expect(vm).toHaveProperty('isAnalysisTabActive')
    expect(vm).toHaveProperty('goEditorFilesTab')
    expect(vm).toHaveProperty('goEditorAnalysisTab')

    expect(typeof vm.saveSkill).toBe('function')
    expect(typeof vm.submitComment).toBe('function')
    expect(typeof vm.handleEditorMount).toBe('function')
    expect(typeof vm.goEditorAnalysisTab).toBe('function')

    wrapper.unmount()
  })

  it('keeps expected initial computed semantics in new mode', async () => {
    const { vm, wrapper } = await mountSkillEditorVm()

    expect(vm.isEdit).toBe(false)
    expect(vm.isReadOnly).toBe(false)
    expect(vm.canSave).toBe(true)
    expect(vm.canPublish).toBe(false)
    expect(vm.pageTitle).toBe('skills.editor.page_title_new')

    wrapper.unmount()
  })

  it('keeps expected initial computed semantics in edit mode', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1' })
    mockEditModeApi()

    const { vm, wrapper } = await mountSkillEditorVm()

    expect(vm.isEdit).toBe(true)
    expect(vm.skillId).toBe('skill-1')
    expect(vm.isReadOnly).toBe(false)
    expect(vm.canPublish).toBe(false)
    expect(vm.latestVersionId).toBe('ver-2')
    expect(vm.activeEditorTab).toBe('files')
    expect(vm.isAnalysisTabActive).toBe(false)

    wrapper.unmount()
  })

  it('derives analysis tab from the analysis child route', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1', analysis: true })
    mockEditModeApi()

    const { vm, wrapper } = await mountSkillEditorVm()

    expect(vm.activeEditorTab).toBe('analysis')
    expect(vm.isAnalysisTabActive).toBe(true)

    wrapper.unmount()
  })

  it('loads analysis for the currently selected latest version', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1', analysis: true })
    mockEditModeApi()

    const { wrapper } = await mountSkillEditorVm()
    const latestCall = apiMock.get.mock.calls.find(([url]) => String(url).endsWith('/skills/skill-1/analyses/latest'))
    const params = latestCall?.[1]?.params as Record<string, unknown>

    expect(params).toMatchObject({
      workspace_id: 'ws-1',
      ref_kind: 'VERSION',
      version_id: 'ver-2',
    })

    wrapper.unmount()
  })

  it('loads analysis for the selected historical version', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1', analysis: true, readonly: true })
    mockEditModeApi()

    const { vm, wrapper } = await mountSkillEditorVm()
    vm.viewVersionId = 'ver-1'
    await vm.loadLatestAnalysis()
    const latestCalls = apiMock.get.mock.calls.filter(([url]) => String(url).endsWith('/skills/skill-1/analyses/latest'))
    const params = latestCalls.at(-1)?.[1]?.params as Record<string, unknown>

    expect(params).toMatchObject({
      workspace_id: 'ws-1',
      ref_kind: 'VERSION',
      version_id: 'ver-1',
    })

    wrapper.unmount()
  })

  it('keeps analysis tab active on risk detail routes', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1', analysis: true, riskKey: 'risk-1' })
    mockEditModeApi()

    const { vm, wrapper } = await mountSkillEditorVm()

    expect(vm.activeEditorTab).toBe('analysis')
    expect(vm.isAnalysisTabActive).toBe(true)
    expect(vm.activeAnalysisRiskKey).toBe('risk-1')

    wrapper.unmount()
  })

  it('navigates between editor header tabs while preserving query', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1', readonly: true })
    mockEditModeApi()

    const { vm, wrapper } = await mountSkillEditorVm()

    await vm.goEditorAnalysisTab()
    expect(routerState.push).toHaveBeenCalledWith({
      name: 'skillsEditAnalysis',
      params: { skillId: 'skill-1' },
      query: { wsId: 'ws-1', readonly: '1' },
    })

    await vm.goEditorFilesTab()
    expect(routerState.push).toHaveBeenLastCalledWith({
      name: 'skillsEdit',
      params: { skillId: 'skill-1' },
      query: { wsId: 'ws-1', readonly: '1' },
    })

    await vm.goAnalysisRiskDetail('risk-1')
    expect(routerState.push).toHaveBeenLastCalledWith({
      name: 'skillsEditAnalysisRisk',
      params: { skillId: 'skill-1', riskKey: 'risk-1' },
      query: { wsId: 'ws-1', readonly: '1' },
    })

    wrapper.unmount()
  })
})
