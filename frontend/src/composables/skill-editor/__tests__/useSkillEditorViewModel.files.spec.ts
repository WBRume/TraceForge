import { beforeEach, describe, expect, it } from 'vitest'
import { apiMock, flushAll, mockEditModeApi, mountSkillEditorVm, resetHarnessState } from './harness'

type FlatNode = { path: string, node_type: string, children?: FlatNode[] }

const flattenPaths = (nodes: FlatNode[]): string[] => {
  const paths: string[] = []
  const walk = (items: FlatNode[]) => {
    items.forEach((item) => {
      paths.push(item.path)
      if (Array.isArray(item.children) && item.children.length > 0) {
        walk(item.children)
      }
    })
  }
  walk(nodes)
  return paths
}

describe('useSkillEditorViewModel file behaviors', () => {
  beforeEach(() => {
    resetHarnessState({ mode: 'new' })
  })

  it('initializes new mode with default SKILL.md file', async () => {
    const { vm, wrapper } = await mountSkillEditorVm()

    expect(vm.activeFilePath).toBe('SKILL.md')
    expect(vm.selectedTreePath).toBe('SKILL.md')
    expect(flattenPaths(vm.fileTree as FlatNode[])).toContain('SKILL.md')

    wrapper.unmount()
  })

  it('supports local create/rename/delete node workflow in new mode', async () => {
    const { vm, wrapper } = await mountSkillEditorVm()

    vm.createNode('file')
    vm.createNodeParentPath = ''
    vm.createNodeName = 'notes.md'
    await vm.confirmCreateNode()
    await flushAll()

    expect(flattenPaths(vm.fileTree as FlatNode[])).toContain('notes.md')
    expect(vm.activeFilePath).toBe('notes.md')
    expect(vm.dirtyFiles).toContain('notes.md')

    await vm.selectTreeNode('notes.md', 'file')
    vm.openRenameNodeDialog()
    vm.renameNodeName = 'renamed-notes.md'
    await vm.confirmRenameNode()
    await flushAll()

    expect(flattenPaths(vm.fileTree as FlatNode[])).not.toContain('notes.md')
    expect(flattenPaths(vm.fileTree as FlatNode[])).toContain('renamed-notes.md')
    expect(vm.dirtyFiles).toContain('renamed-notes.md')

    await vm.selectTreeNode('renamed-notes.md', 'file')
    vm.openDeleteNodeConfirm()
    await vm.confirmDeleteNode()
    await flushAll()

    expect(flattenPaths(vm.fileTree as FlatNode[])).not.toContain('renamed-notes.md')

    wrapper.unmount()
  })

  it('keeps dirty cache in worktree and marks binary file when opening file in edit mode', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1' })
    mockEditModeApi({
      treeNodes: [
        {
          path: 'SKILL.md',
          name: 'SKILL.md',
          node_type: 'file',
          children: [],
        },
        {
          path: 'script.sh',
          name: 'script.sh',
          node_type: 'file',
          children: [],
        },
      ],
      fileContentByPath: {
        'SKILL.md': { content: 'initial', is_binary: false },
        'script.sh': { content: '', is_binary: true },
      },
    })

    const { vm, wrapper } = await mountSkillEditorVm()

    const contentCallCountBeforeDirtyOpen = apiMock.get.mock.calls
      .filter(([url]) => String(url).includes('/files/content')).length

    vm.activeFileContent = 'changed'
    expect(vm.dirtyFiles).toContain('SKILL.md')

    await vm.openFile('SKILL.md')
    await flushAll()

    const contentCallCountAfterDirtyOpen = apiMock.get.mock.calls
      .filter(([url]) => String(url).includes('/files/content')).length

    expect(contentCallCountAfterDirtyOpen).toBe(contentCallCountBeforeDirtyOpen)

    await vm.openFile('script.sh')
    await flushAll()

    expect(vm.binaryFileMap['script.sh']).toBe(true)
    expect(vm.activeFilePath).toBe('script.sh')

    wrapper.unmount()
  })
})
