import { computed, reactive, ref, type ComputedRef, type Ref } from 'vue'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import {
  buildTreeFromEntries,
  collectDirectoryPaths,
  findNodeByPath,
  flattenFiles,
  flattenTreeEntries,
  pickDefaultFilePath,
} from './skillEditorTreeUtils'
import {
  normalizePathValue,
  parentDirPath,
  pathBaseName,
  pathStartsWithPrefix,
  rebasePathPrefix,
} from './skillEditorPathUtils'
import type { SkillFileNode, SkillNodeType } from './skillEditorTypes'

type TranslateFn = (key: string, params?: Record<string, unknown>) => string

type FormState = {
  entryFilePath: string
}

type UseSkillEditorFilesOptions = {
  t: TranslateFn
  actionError: Ref<string>
  form: Ref<FormState>
  isEdit: ComputedRef<boolean>
  isReadOnly: ComputedRef<boolean>
  skillId: ComputedRef<string | undefined>
  selectedWorkspaceId: Ref<string>
  currentRef: ComputedRef<string>
  isWorktreeRef: ComputedRef<boolean>
  onBeforeOpenFile?: () => void
  onAfterOpenFile?: () => Promise<void> | void
  onAfterRemoteMutation?: () => Promise<void> | void
}

export function useSkillEditorFiles(options: UseSkillEditorFilesOptions) {
  const {
    t,
    actionError,
    form,
    isEdit,
    isReadOnly,
    skillId,
    selectedWorkspaceId,
    currentRef,
    isWorktreeRef,
    onBeforeOpenFile,
    onAfterOpenFile,
    onAfterRemoteMutation,
  } = options

  const fileTree = ref<SkillFileNode[]>([])
  const activeFilePath = ref('')
  const selectedTreePath = ref('')
  const selectedTreeNodeType = ref<SkillNodeType>('file')
  const fileContents = reactive<Record<string, string>>({})
  const fileOriginalContents = reactive<Record<string, string>>({})
  const binaryFileMap = reactive<Record<string, boolean>>({})
  const dirtyFiles = ref<string[]>([])
  const loadingFile = ref(false)
  const treeLoading = ref(false)

  const showCreateNodeModal = ref(false)
  const creatingNode = ref(false)
  const showRenameNodeModal = ref(false)
  const renamingNode = ref(false)
  const showDeleteNodeConfirm = ref(false)
  const deletingNode = ref(false)
  const createNodeType = ref<SkillNodeType>('file')
  const createNodeParentPath = ref('')
  const createNodeName = ref('')
  const renameNodeSourcePath = ref('')
  const renameNodeType = ref<SkillNodeType>('file')
  const renameNodeName = ref('')
  const deleteNodePath = ref('')
  const deleteNodeType = ref<SkillNodeType>('file')

  const hasDirtyFiles = computed(() => dirtyFiles.value.length > 0)

  const workspaceParams = () => (
    selectedWorkspaceId.value ? { workspace_id: selectedWorkspaceId.value } : {}
  )

  const activeFileContent = computed({
    get: () => fileContents[activeFilePath.value] || '',
    set: (value: string) => {
      if (!activeFilePath.value) return
      fileContents[activeFilePath.value] = value
      const original = fileOriginalContents[activeFilePath.value] ?? ''
      const dirty = value !== original
      const next = new Set(dirtyFiles.value)
      if (dirty) next.add(activeFilePath.value)
      else next.delete(activeFilePath.value)
      dirtyFiles.value = [...next]
    },
  })

  const remapCachedPathPrefix = (oldPrefix: string, newPrefix: string) => {
    const contentEntries = Object.entries({ ...fileContents })
    contentEntries.forEach(([path, value]) => {
      if (!pathStartsWithPrefix(path, oldPrefix)) return
      const mappedPath = rebasePathPrefix(path, oldPrefix, newPrefix)
      fileContents[mappedPath] = value
      if (mappedPath !== path) {
        delete fileContents[path]
      }
    })

    const originalEntries = Object.entries({ ...fileOriginalContents })
    originalEntries.forEach(([path, value]) => {
      if (!pathStartsWithPrefix(path, oldPrefix)) return
      const mappedPath = rebasePathPrefix(path, oldPrefix, newPrefix)
      fileOriginalContents[mappedPath] = value
      if (mappedPath !== path) {
        delete fileOriginalContents[path]
      }
    })

    const binaryEntries = Object.entries({ ...binaryFileMap })
    binaryEntries.forEach(([path, value]) => {
      if (!pathStartsWithPrefix(path, oldPrefix)) return
      const mappedPath = rebasePathPrefix(path, oldPrefix, newPrefix)
      binaryFileMap[mappedPath] = value
      if (mappedPath !== path) {
        delete binaryFileMap[path]
      }
    })

    dirtyFiles.value = [...new Set(
      dirtyFiles.value.map(path => rebasePathPrefix(path, oldPrefix, newPrefix)),
    )]

    if (pathStartsWithPrefix(activeFilePath.value, oldPrefix)) {
      activeFilePath.value = rebasePathPrefix(activeFilePath.value, oldPrefix, newPrefix)
    }
    if (pathStartsWithPrefix(selectedTreePath.value, oldPrefix)) {
      selectedTreePath.value = rebasePathPrefix(selectedTreePath.value, oldPrefix, newPrefix)
    }
    if (pathStartsWithPrefix(form.value.entryFilePath, oldPrefix)) {
      form.value.entryFilePath = rebasePathPrefix(form.value.entryFilePath, oldPrefix, newPrefix)
    }
  }

  const removeCachedPathPrefix = (prefix: string) => {
    Object.keys({ ...fileContents }).forEach((path) => {
      if (pathStartsWithPrefix(path, prefix)) {
        delete fileContents[path]
      }
    })
    Object.keys({ ...fileOriginalContents }).forEach((path) => {
      if (pathStartsWithPrefix(path, prefix)) {
        delete fileOriginalContents[path]
      }
    })
    Object.keys({ ...binaryFileMap }).forEach((path) => {
      if (pathStartsWithPrefix(path, prefix)) {
        delete binaryFileMap[path]
      }
    })

    dirtyFiles.value = dirtyFiles.value.filter(path => !pathStartsWithPrefix(path, prefix))
    if (pathStartsWithPrefix(activeFilePath.value, prefix)) {
      activeFilePath.value = ''
    }
    if (pathStartsWithPrefix(selectedTreePath.value, prefix)) {
      selectedTreePath.value = ''
    }
    if (pathStartsWithPrefix(form.value.entryFilePath, prefix)) {
      form.value.entryFilePath = 'SKILL.md'
    }
  }

  const directoryOptions = computed(() => {
    const dirs = collectDirectoryPaths(fileTree.value || []).filter(path => path)
    return [{ value: '', label: t('skills.editor.root_directory') }, ...dirs.map(path => ({ value: path, label: path }))]
  })

  const createNodeDialogTitle = computed(() => (
    createNodeType.value === 'file'
      ? t('skills.editor.create_file_dialog_title')
      : t('skills.editor.create_folder_dialog_title')
  ))

  const createNodeNamePlaceholder = computed(() => (
    createNodeType.value === 'file'
      ? t('skills.editor.create_file_name_placeholder')
      : t('skills.editor.create_folder_name_placeholder')
  ))

  const selectedNodePathForActions = computed(() => (
    normalizePathValue(selectedTreePath.value || activeFilePath.value)
  ))

  const selectedNodeTypeForActions = computed<SkillNodeType>(() => (
    selectedTreePath.value ? selectedTreeNodeType.value : 'file'
  ))

  const canOperateSelectedNode = computed(() => (
    !isReadOnly.value
    && (!isEdit.value || !!skillId.value)
    && !!selectedNodePathForActions.value
  ))

  const renameNodeDialogTitle = computed(() => (
    renameNodeType.value === 'directory'
      ? t('skills.editor.rename_folder_dialog_title')
      : t('skills.editor.rename_file_dialog_title')
  ))

  const renameNodeNamePlaceholder = computed(() => (
    renameNodeType.value === 'directory'
      ? t('skills.editor.rename_folder_name_placeholder')
      : t('skills.editor.rename_file_name_placeholder')
  ))

  const rebuildLocalTreeFromEntries = (entries: Array<{ path: string, node_type: SkillNodeType }>) => {
    fileTree.value = buildTreeFromEntries(entries)
  }

  const createLocalNode = (path: string, nodeType: SkillNodeType) => {
    const normalizedPath = normalizePathValue(path)
    if (!normalizedPath) {
      throw new Error(t('skills.editor.create_node_name_required'))
    }
    const entries = flattenTreeEntries(fileTree.value)
    if (entries.some(entry => entry.path === normalizedPath)) {
      throw new Error(t('skills.editor.path_exists'))
    }
    entries.push({ path: normalizedPath, node_type: nodeType })
    rebuildLocalTreeFromEntries(entries)

    if (nodeType === 'file') {
      if (!(normalizedPath in fileContents)) {
        fileContents[normalizedPath] = ''
      }
      if (!(normalizedPath in fileOriginalContents)) {
        fileOriginalContents[normalizedPath] = ''
      }
      binaryFileMap[normalizedPath] = false
      if (!dirtyFiles.value.includes(normalizedPath)) {
        dirtyFiles.value = [...dirtyFiles.value, normalizedPath]
      }
    }
  }

  const renameLocalNode = (sourcePath: string, targetPath: string) => {
    const source = normalizePathValue(sourcePath)
    const target = normalizePathValue(targetPath)
    const entries = flattenTreeEntries(fileTree.value)
    const affected = entries.filter(entry => pathStartsWithPrefix(entry.path, source))
    if (!affected.length) {
      throw new Error(t('skills.editor.load_failed'))
    }

    const unaffected = entries.filter(entry => !pathStartsWithPrefix(entry.path, source))
    const occupiedPaths = new Set(unaffected.map(entry => entry.path))
    const remapped = affected.map(entry => ({
      ...entry,
      path: rebasePathPrefix(entry.path, source, target),
    }))

    for (const item of remapped) {
      if (occupiedPaths.has(item.path)) {
        throw new Error(t('skills.editor.path_exists'))
      }
    }

    rebuildLocalTreeFromEntries([...unaffected, ...remapped])
    remapCachedPathPrefix(source, target)
  }

  const deleteLocalNode = (path: string) => {
    const normalized = normalizePathValue(path)
    const entries = flattenTreeEntries(fileTree.value)
    const remaining = entries.filter(entry => !pathStartsWithPrefix(entry.path, normalized))
    if (remaining.length === entries.length) {
      throw new Error(t('skills.editor.load_failed'))
    }
    rebuildLocalTreeFromEntries(remaining)
    removeCachedPathPrefix(normalized)
  }

  const selectTreeNode = async (path: string, nodeType: SkillNodeType, onFileClick: (nextPath: string) => Promise<void>) => {
    selectedTreePath.value = path
    selectedTreeNodeType.value = nodeType
    if (nodeType === 'file') {
      await onFileClick(path)
    }
  }

  const loadFileTree = async () => {
    if (!isEdit.value || !skillId.value) return
    treeLoading.value = true
    try {
      const res = await api.get(`/skills/${skillId.value}/files/tree`, {
        params: { ...workspaceParams(), ref: currentRef.value },
      })
      fileTree.value = res.data.nodes || []
      const currentSelectionNode = selectedTreePath.value ? findNodeByPath(fileTree.value, selectedTreePath.value) : null
      if (!currentSelectionNode) {
        selectedTreePath.value = ''
      } else {
        selectedTreeNodeType.value = currentSelectionNode.node_type
      }

      const filePaths = flattenFiles(fileTree.value)
      const preferredPath = filePaths.includes(activeFilePath.value)
        ? activeFilePath.value
        : pickDefaultFilePath(fileTree.value, form.value.entryFilePath)
      if (preferredPath) {
        await openFile(preferredPath)
      } else {
        activeFilePath.value = ''
      }
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.load_failed'), t)
    } finally {
      treeLoading.value = false
    }
  }

  const openFile = async (path: string) => {
    if (!path) return

    if (!isEdit.value) {
      activeFilePath.value = path
      selectedTreePath.value = path
      selectedTreeNodeType.value = 'file'
      if (!(path in fileContents)) {
        fileContents[path] = ''
        fileOriginalContents[path] = ''
      }
      return
    }

    if (!skillId.value) return

    loadingFile.value = true
    onBeforeOpenFile?.()
    activeFilePath.value = path
    selectedTreePath.value = path
    selectedTreeNodeType.value = 'file'
    try {
      if ((path in fileContents) && (dirtyFiles.value.includes(path) || isWorktreeRef.value)) {
        await onAfterOpenFile?.()
        loadingFile.value = false
        return
      }

      const res = await api.get(`/skills/${skillId.value}/files/content`, {
        params: { ...workspaceParams(), path, ref: currentRef.value },
      })
      binaryFileMap[path] = Boolean(res.data.is_binary)
      fileContents[path] = res.data.content || ''
      if (isWorktreeRef.value) {
        fileOriginalContents[path] = res.data.content || ''
      }
      await onAfterOpenFile?.()
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.load_failed'), t)
    } finally {
      loadingFile.value = false
    }
  }

  const resetFilesForNewSkill = () => {
    fileTree.value = [{
      path: 'SKILL.md',
      name: 'SKILL.md',
      node_type: 'file',
      children: [],
    }]
    activeFilePath.value = 'SKILL.md'
    selectedTreePath.value = 'SKILL.md'
    selectedTreeNodeType.value = 'file'
    fileContents['SKILL.md'] = ''
    fileOriginalContents['SKILL.md'] = ''
    binaryFileMap['SKILL.md'] = false
    dirtyFiles.value = []
  }

  const persistDirtyFiles = async () => {
    if (!isEdit.value || !skillId.value) return

    const uniqueDirty = [...new Set(dirtyFiles.value)]
    for (const path of uniqueDirty) {
      await api.put(`/skills/${skillId.value}/files/content`, {
        path,
        content: fileContents[path] || '',
      }, {
        params: workspaceParams(),
      })
      fileOriginalContents[path] = fileContents[path] || ''
    }
    dirtyFiles.value = []
  }

  const buildInitialEntriesForCreate = () => {
    const normalizedEntryPath = normalizePathValue(form.value.entryFilePath || 'SKILL.md') || 'SKILL.md'
    const entries = flattenTreeEntries(fileTree.value).map(entry => ({
      path: normalizePathValue(entry.path),
      node_type: entry.node_type as SkillNodeType,
    })).filter(entry => !!entry.path)

    const hasEntryFile = entries.some(entry => entry.path === normalizedEntryPath && entry.node_type === 'file')
    if (!hasEntryFile) {
      entries.push({ path: normalizedEntryPath, node_type: 'file' })
      if (!(normalizedEntryPath in fileContents)) {
        fileContents[normalizedEntryPath] = ''
      }
    }

    const dedup = new Map<string, SkillNodeType>()
    entries.forEach((entry) => {
      const existing = dedup.get(entry.path)
      if (existing === 'directory' && entry.node_type === 'file') {
        dedup.set(entry.path, 'file')
        return
      }
      if (!existing) {
        dedup.set(entry.path, entry.node_type)
      }
    })

    return [...dedup.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([path, nodeType]) => ({
        path,
        node_type: nodeType,
        content: nodeType === 'file' ? (fileContents[path] || '') : null,
      }))
  }

  const resolveDefaultCreateParentPath = () => {
    if (selectedTreePath.value) {
      if (selectedTreeNodeType.value === 'directory') {
        return normalizePathValue(selectedTreePath.value)
      }
      return parentDirPath(selectedTreePath.value)
    }
    if (activeFilePath.value) {
      return parentDirPath(activeFilePath.value)
    }
    return ''
  }

  const createNode = (nodeType: SkillNodeType) => {
    if (isReadOnly.value) return
    if (isEdit.value && !skillId.value) return
    createNodeType.value = nodeType
    createNodeName.value = ''
    const defaultParent = resolveDefaultCreateParentPath()
    createNodeParentPath.value = directoryOptions.value.some(option => option.value === defaultParent)
      ? defaultParent
      : ''
    showCreateNodeModal.value = true
  }

  const cancelCreateNode = () => {
    if (creatingNode.value) return
    showCreateNodeModal.value = false
    createNodeName.value = ''
  }

  const buildCreateNodePath = () => {
    const parent = normalizePathValue(createNodeParentPath.value)
    const name = normalizePathValue(createNodeName.value)
    if (!name) {
      throw new Error(t('skills.editor.create_node_name_required'))
    }
    if (name.includes('/')) {
      throw new Error(t('skills.editor.create_node_name_no_slash'))
    }
    return parent ? `${parent}/${name}` : name
  }

  const confirmCreateNode = async () => {
    if (isReadOnly.value) return
    if (isEdit.value && !skillId.value) return
    let path = ''
    try {
      path = buildCreateNodePath()
    } catch (error) {
      actionError.value = error instanceof Error ? error.message : t('skills.editor.save_failed')
      return
    }

    creatingNode.value = true
    try {
      if (isEdit.value) {
        await api.post(`/skills/${skillId.value}/files`, {
          path,
          node_type: createNodeType.value,
          content: createNodeType.value === 'file' ? '' : null,
        }, {
          params: workspaceParams(),
        })
        await loadFileTree()
        await onAfterRemoteMutation?.()
      } else {
        createLocalNode(path, createNodeType.value)
      }
      if (createNodeType.value === 'file') {
        await openFile(path)
      } else {
        selectedTreePath.value = path
        selectedTreeNodeType.value = 'directory'
      }
      showCreateNodeModal.value = false
      createNodeName.value = ''
    } catch (error) {
      actionError.value = error instanceof Error
        ? error.message
        : formatApiError(error, t('skills.editor.save_failed'), t)
    } finally {
      creatingNode.value = false
    }
  }

  const openRenameNodeDialog = () => {
    if (!canOperateSelectedNode.value) return
    const sourcePath = selectedNodePathForActions.value
    renameNodeSourcePath.value = sourcePath
    renameNodeType.value = selectedNodeTypeForActions.value
    renameNodeName.value = pathBaseName(sourcePath)
    showRenameNodeModal.value = true
  }

  const cancelRenameNode = () => {
    if (renamingNode.value) return
    showRenameNodeModal.value = false
    renameNodeName.value = ''
  }

  const confirmRenameNode = async () => {
    if (isReadOnly.value) return
    if (isEdit.value && !skillId.value) return
    const sourcePath = normalizePathValue(renameNodeSourcePath.value)
    if (!sourcePath) return

    const newName = normalizePathValue(renameNodeName.value)
    if (!newName) {
      actionError.value = t('skills.editor.rename_node_name_required')
      return
    }
    if (newName.includes('/')) {
      actionError.value = t('skills.editor.rename_node_name_no_slash')
      return
    }

    const parent = parentDirPath(sourcePath)
    const targetPath = parent ? `${parent}/${newName}` : newName
    if (targetPath === sourcePath) {
      showRenameNodeModal.value = false
      return
    }

    renamingNode.value = true
    try {
      if (isEdit.value) {
        await api.post(`/skills/${skillId.value}/files/move`, {
          old_path: sourcePath,
          new_path: targetPath,
        }, {
          params: workspaceParams(),
        })
        remapCachedPathPrefix(sourcePath, targetPath)
      } else {
        renameLocalNode(sourcePath, targetPath)
      }
      selectedTreePath.value = targetPath
      selectedTreeNodeType.value = renameNodeType.value
      showRenameNodeModal.value = false
      renameNodeName.value = ''
      if (isEdit.value) {
        await loadFileTree()
        await onAfterRemoteMutation?.()
      }
      if (selectedTreeNodeType.value === 'file' && activeFilePath.value) {
        await openFile(activeFilePath.value)
      }
    } catch (error) {
      actionError.value = error instanceof Error
        ? error.message
        : formatApiError(error, t('skills.editor.save_failed'), t)
    } finally {
      renamingNode.value = false
    }
  }

  const openDeleteNodeConfirm = () => {
    if (!canOperateSelectedNode.value) return
    deleteNodePath.value = selectedNodePathForActions.value
    deleteNodeType.value = selectedNodeTypeForActions.value
    showDeleteNodeConfirm.value = true
  }

  const cancelDeleteNode = () => {
    if (deletingNode.value) return
    showDeleteNodeConfirm.value = false
  }

  const confirmDeleteNode = async () => {
    if (isReadOnly.value) return
    if (isEdit.value && !skillId.value) return
    const targetPath = normalizePathValue(deleteNodePath.value)
    if (!targetPath) return

    deletingNode.value = true
    try {
      if (isEdit.value) {
        await api.delete(`/skills/${skillId.value}/files`, {
          params: { ...workspaceParams(), path: targetPath },
        })
        removeCachedPathPrefix(targetPath)
      } else {
        deleteLocalNode(targetPath)
      }
      showDeleteNodeConfirm.value = false
      if (isEdit.value) {
        await loadFileTree()
        await onAfterRemoteMutation?.()
      }
    } catch (error) {
      actionError.value = error instanceof Error
        ? error.message
        : formatApiError(error, t('skills.editor.save_failed'), t)
    } finally {
      deletingNode.value = false
    }
  }

  return {
    fileTree,
    activeFilePath,
    selectedTreePath,
    selectedTreeNodeType,
    fileContents,
    fileOriginalContents,
    binaryFileMap,
    dirtyFiles,
    loadingFile,
    treeLoading,
    hasDirtyFiles,
    activeFileContent,
    showCreateNodeModal,
    creatingNode,
    showRenameNodeModal,
    renamingNode,
    showDeleteNodeConfirm,
    deletingNode,
    createNodeType,
    createNodeParentPath,
    createNodeName,
    renameNodeSourcePath,
    renameNodeType,
    renameNodeName,
    deleteNodePath,
    deleteNodeType,
    directoryOptions,
    createNodeDialogTitle,
    createNodeNamePlaceholder,
    canOperateSelectedNode,
    renameNodeDialogTitle,
    renameNodeNamePlaceholder,
    remapCachedPathPrefix,
    removeCachedPathPrefix,
    selectTreeNode,
    loadFileTree,
    openFile,
    resetFilesForNewSkill,
    persistDirtyFiles,
    buildInitialEntriesForCreate,
    createNode,
    cancelCreateNode,
    confirmCreateNode,
    openRenameNodeDialog,
    cancelRenameNode,
    confirmRenameNode,
    openDeleteNodeConfirm,
    cancelDeleteNode,
    confirmDeleteNode,
  }
}
