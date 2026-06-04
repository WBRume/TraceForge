import { beforeEach, describe, expect, it } from 'vitest'
import { flushAll, mockEditModeApi, mountSkillEditorVm, resetHarnessState } from './harness'

describe('useSkillEditorViewModel versions and diff', () => {
  beforeEach(() => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1' })
  })

  it('loads versions and initializes compare refs by default', async () => {
    mockEditModeApi()
    const { vm, wrapper } = await mountSkillEditorVm()

    expect(vm.versions.length).toBeGreaterThanOrEqual(2)
    expect(vm.compareToVersionId).toBe('ver-2')
    expect(vm.compareFromVersionId).toBe('ver-1')
    expect(vm.viewVersionId).toBe('ver-2')

    wrapper.unmount()
  })

  it('loads directory diff and auto-loads first file diff payload', async () => {
    mockEditModeApi({
      compareFiles: [
        {
          status: 'modified',
          path: 'SKILL.md',
          old_path: null,
          is_binary: false,
          additions: 2,
          deletions: 1,
        },
        {
          status: 'added',
          path: 'scripts/setup.sh',
          old_path: null,
          is_binary: false,
          additions: 10,
          deletions: 0,
        },
      ],
      fileDiffByPath: {
        'SKILL.md': {
          original: 'old content',
          modified: 'new content',
          is_binary: false,
        },
      },
    })

    const { vm, wrapper } = await mountSkillEditorVm()
    await vm.loadDirectoryDiff()
    await flushAll()

    expect(vm.diffFiles.length).toBe(2)
    expect(vm.activeDiffFilePath).toBe('SKILL.md')
    expect(vm.diffPayload.loaded).toBe(true)
    expect(vm.diffPayload.original).toBe('old content')
    expect(vm.diffPayload.modified).toBe('new content')
    expect(vm.diffPayload.isBinary).toBe(false)
    expect(vm.diffPayload.fromVersionNo).toBe(1)
    expect(vm.diffPayload.toVersionNo).toBe(2)

    wrapper.unmount()
  })

  it('loads file-level diff payload including binary flag', async () => {
    mockEditModeApi({
      fileDiffByPath: {
        'assets/logo.bin': {
          original: '',
          modified: '',
          is_binary: true,
        },
      },
    })

    const { vm, wrapper } = await mountSkillEditorVm()
    await vm.loadFileDiff('assets/logo.bin')
    await flushAll()

    expect(vm.activeDiffFilePath).toBe('assets/logo.bin')
    expect(vm.diffPayload.loaded).toBe(true)
    expect(vm.diffPayload.isBinary).toBe(true)
    expect(vm.diffPayload.fromVersionNo).toBe(1)
    expect(vm.diffPayload.toVersionNo).toBe(2)

    wrapper.unmount()
  })
})
