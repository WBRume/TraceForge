import { computed, ref } from 'vue'
import { acceptHMRUpdate, defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  createTaskChangeProposal,
  downloadChangeProposalPatch,
  getLatestChangeProposal,
  listChangeProposalFiles,
  listChangeProposalRepoPatches,
} from '@/services/agentApi'
import type {
  AgentTask,
  ChangeProposal,
  ChangeProposalFile,
  ChangeProposalRepoPatch,
} from '@/types/agent'
import type { DesktopRepoMapping } from '@/types/sddDesktop'
import { DEFAULT_SERVER_URL, setApiServerUrl } from '@/utils/api'
import { getSddDesktop, isElectron } from '@/utils/runtime'
import { normalizeRemoteUrl, remoteUrlsMatch } from '@/composables/local-agent/localAgentUtils'

type WorkspaceLike = {
  id?: string
  git_repo_url?: string | null
  repositories?: { id?: string; repo_url?: string; repo_name?: string }[]
}

type TaskLike = Partial<AgentTask> & {
  id: string
  workspace_id?: string
  git_repo_url?: string | null
}

const keyFor = (remote: string) => normalizeRemoteUrl(remote)

export const useLocalAgentStore = defineStore('localAgent', () => {
  const authStore = useAuthStore()
  const desktop = getSddDesktop()
  const electronAvailable = computed(() => isElectron() && Boolean(desktop))

  const initialized = ref(false)
  const token = ref(authStore.token || '')
  const workspace = ref<WorkspaceLike | null>(null)
  const task = ref<TaskLike | null>(null)

  const proposal = ref<ChangeProposal | null>(null)
  const proposalFiles = ref<ChangeProposalFile[]>([])
  const patchText = ref('')
  const repoPatches = ref<ChangeProposalRepoPatch[]>([])
  const proposalLoading = ref(false)
  const proposalGenerating = ref(false)
  const patchLoading = ref(false)

  // Multi-repository mappings: normalized remote URL -> mapping/status.
  const repoMappings = ref<Record<string, DesktopRepoMapping>>({})
  const repoStatusMap = ref<Record<string, string>>({})
  const activeRemoteUrl = ref('')
  const pendingLocalPath = ref('')

  const workspaceId = computed(() => task.value?.workspace_id || workspace.value?.id || '')

  const workspaceRemotes = computed<string[]>(() => {
    const ws = workspace.value
    if (!ws) return []
    const repos = Array.isArray(ws.repositories) && ws.repositories.length > 0
      ? ws.repositories.map((item) => String(item.repo_url || '').trim()).filter(Boolean)
      : (ws.git_repo_url ? [String(ws.git_repo_url).trim()] : [])
    return repos
  })

  const expectedRemoteUrls = computed(() => workspaceRemotes.value)
  const expectedRemoteUrl = computed(() => workspaceRemotes.value[0] || '')

  const repoMapping = computed<DesktopRepoMapping | null>(() => (
    repoMappings.value[keyFor(activeRemoteUrl.value)] || null
  ))
  const repoPath = computed(() => repoMapping.value?.localPath || '')
  const repoRemoteUrl = computed(() => repoMapping.value?.remoteUrl || '')
  const repoStatus = computed(() => repoStatusMap.value[keyFor(activeRemoteUrl.value)] || '')

  const mappingFor = (remote: string): DesktopRepoMapping | null => (
    repoMappings.value[keyFor(remote)] || null
  )
  const statusFor = (remote: string): string => repoStatusMap.value[keyFor(remote)] || ''

  const repoReadyFor = (remote: string): boolean => {
    const mapping = mappingFor(remote)
    const status = statusFor(remote)
    return Boolean(mapping?.localPath && status.startsWith('Clean'))
  }

  const repoReady = computed(() => (
    Boolean(expectedRemoteUrl.value) && repoReadyFor(expectedRemoteUrl.value)
  ))

  const mappedCount = computed(() => (
    expectedRemoteUrls.value.filter((remote) => Boolean(mappingFor(remote)?.localPath)).length
  ))
  const missingRemotes = computed(() => (
    expectedRemoteUrls.value.filter((remote) => !mappingFor(remote)?.localPath)
  ))

  const proposalRemotes = computed<string[]>(() => (
    (proposal.value?.repositories || [])
      .map((item) => String(item.repo_url || '').trim())
      .filter(Boolean)
  ))
  const applyMissingRemotes = computed(() => (
    proposalRemotes.value.filter((remote) => !mappingFor(remote)?.localPath)
  ))

  const hasProposal = computed(() => Boolean(proposal.value && patchText.value))

  const resetProposalState = () => {
    proposal.value = null
    proposalFiles.value = []
    patchText.value = ''
    repoPatches.value = []
  }

  const resetRepoState = () => {
    repoMappings.value = {}
    repoStatusMap.value = {}
    activeRemoteUrl.value = ''
    pendingLocalPath.value = ''
  }

  const loadLocalConfig = async () => {
    if (initialized.value) return
    if (!desktop) {
      initialized.value = true
      return
    }
    const config = await desktop.config.getConfig()
    token.value = config.token || authStore.token || ''
    if (config.token) {
      authStore.setToken(config.token)
    }
    setApiServerUrl(DEFAULT_SERVER_URL)
    initialized.value = true
  }

  const syncCurrentAuthToConfig = async () => {
    token.value = authStore.token || ''
    if (!desktop) return
    await desktop.config.setConfig({
      serverUrl: DEFAULT_SERVER_URL,
      token: authStore.token || null,
    })
  }

  const setWorkspaceContext = async (nextWorkspace: WorkspaceLike | null) => {
    task.value = null
    workspace.value = nextWorkspace
    resetProposalState()
    await loadRepoMapping()
  }

  const setTaskContext = async (
    nextTask: TaskLike | null,
    nextWorkspace?: WorkspaceLike | null,
    options?: { loadLatest?: boolean },
  ) => {
    task.value = nextTask
    if (nextWorkspace !== undefined) {
      workspace.value = nextWorkspace
    }
    resetProposalState()
    resetRepoState()
    if (task.value?.id && options?.loadLatest !== false) {
      await loadLatestProposal(task.value)
    }
    await loadRepoMapping()
  }

  const hydrateProposal = async (nextProposal: ChangeProposal | null): Promise<ChangeProposal | null> => {
    proposal.value = nextProposal
    if (!proposal.value) {
      proposalFiles.value = []
      patchText.value = ''
      repoPatches.value = []
      return null
    }
    const files = await listChangeProposalFiles(proposal.value.id)
    proposalFiles.value = files.items
    await downloadPatch()
    await loadRepoPatches()
    return proposal.value
  }

  const loadRepoPatches = async () => {
    if (!proposal.value) {
      repoPatches.value = []
      return
    }
    const repos = Array.isArray(proposal.value.repositories) ? proposal.value.repositories : []
    if (repos.length === 0) {
      repoPatches.value = []
      return
    }
    try {
      const res = await listChangeProposalRepoPatches(proposal.value.id)
      repoPatches.value = res.items
    } catch {
      repoPatches.value = []
    }
  }

  const loadLatestProposal = async (targetTask = task.value): Promise<ChangeProposal | null> => {
    if (!targetTask?.id) return null
    proposalLoading.value = true
    try {
      return await hydrateProposal(await getLatestChangeProposal(targetTask.id))
    } catch {
      proposal.value = null
      proposalFiles.value = []
      patchText.value = ''
      repoPatches.value = []
      return null
    } finally {
      proposalLoading.value = false
    }
  }

  const generateChangeProposal = async (
    targetTask = task.value,
    targetWorkspace = workspace.value,
  ): Promise<ChangeProposal | null> => {
    if (!targetTask?.id) return null
    const targetWorkspaceId = String(targetTask.workspace_id || targetWorkspace?.id || workspaceId.value || '').trim()
    if (!targetWorkspaceId) {
      throw new Error('生成变更提案需要 workspace_id')
    }
    proposalGenerating.value = true
    proposalLoading.value = true
    try {
      const created = await createTaskChangeProposal({
        workspaceId: targetWorkspaceId,
        taskId: targetTask.id,
      })
      return await hydrateProposal(created)
    } finally {
      proposalGenerating.value = false
      proposalLoading.value = false
    }
  }

  const downloadPatch = async () => {
    if (!proposal.value) return
    patchLoading.value = true
    try {
      patchText.value = await downloadChangeProposalPatch(proposal.value.id)
    } finally {
      patchLoading.value = false
    }
  }

  const loadRepoMapping = async () => {
    resetRepoState()
    if (!desktop || !workspaceId.value) return
    const remotes = expectedRemoteUrls.value
    activeRemoteUrl.value = remotes[0] || ''
    if (remotes.length === 0) return
    for (const remote of remotes) {
      try {
        const mapping = await desktop.config.getRepoMapping({
          workspaceId: workspaceId.value,
          remoteUrl: remote,
        })
        if (mapping?.localPath) {
          repoMappings.value[keyFor(remote)] = mapping
          await validateRemote(remote, mapping.localPath)
        }
      } catch {
        // Per-repository mapping failures are tolerated.
      }
    }
  }

  const chooseRepo = async () => {
    if (!desktop) return
    const result = await desktop.git.selectDirectory()
    if (result.canceled || !result.path) return
    pendingLocalPath.value = result.path
    await validateRemote(activeRemoteUrl.value, result.path)
  }

  const chooseRepoFor = async (remote: string): Promise<string | null> => {
    if (!desktop) return null
    const result = await desktop.git.selectDirectory()
    if (result.canceled || !result.path) return null
    await validateRemote(remote, result.path)
    return result.path
  }

  const validateRepo = async () => {
    if (!desktop) return
    const targetPath = repoPath.value || pendingLocalPath.value
    if (!targetPath) return
    await validateRemote(activeRemoteUrl.value, targetPath)
  }

  const validateRemote = async (remote: string, localPath: string) => {
    if (!desktop || !localPath) return
    const key = keyFor(remote)
    const valid = await desktop.git.validateGitRepo(localPath)
    if (!valid.ok) {
      repoStatusMap.value[key] = valid.stderr || '所选目录不是 Git 仓库'
      return
    }
    const remoteInfo = await desktop.git.getRemoteUrl(localPath)
    const status = await desktop.git.getStatus(localPath)
    repoStatusMap.value[key] = status.isClean
      ? 'Clean · ' + normalizeRemoteUrl(remoteInfo.remoteUrl)
      : 'Dirty · ' + status.entries.length + ' changed files'
  }

  const saveRepoMapping = async (lastVerificationCommand?: string | null) => {
    if (!desktop || !workspaceId.value) return
    const remote = activeRemoteUrl.value
    const localPath = pendingLocalPath.value || repoPath.value
    if (!remote || !localPath) return
    await saveMappingFor(remote, localPath, lastVerificationCommand)
  }

  const saveMappingFor = async (
    remote: string,
    localPath: string,
    lastVerificationCommand?: string | null,
  ): Promise<boolean> => {
    if (!desktop || !workspaceId.value) return false
    await validateRemote(remote, localPath)
    const status = statusFor(remote)
    const detectedRemote = status.startsWith('Clean · ') ? status.slice('Clean · '.length) : ''
    if (detectedRemote && !remoteUrlsMatch(detectedRemote, remote)) {
      ElMessage.error('本地仓库 remote.origin.url 与仓库地址不一致')
      return false
    }
    if (!status.startsWith('Clean')) {
      ElMessage.error('本地仓库存在未提交修改，请清理后再绑定')
      return false
    }
    const mapping = await desktop.config.setRepoMapping({
      workspaceId: workspaceId.value,
      remoteUrl: remote,
      localPath,
      lastVerificationCommand: lastVerificationCommand ?? null,
    })
    repoMappings.value[keyFor(remote)] = mapping
    ElMessage.success('本地仓库已绑定')
    return true
  }

  const removeRepoMapping = async () => {
    if (!desktop || !workspaceId.value || !activeRemoteUrl.value) return
    await removeMappingFor(activeRemoteUrl.value)
  }

  const removeMappingFor = async (remote: string): Promise<void> => {
    if (!desktop || !workspaceId.value) return
    await desktop.config.removeRepoMapping({
      workspaceId: workspaceId.value,
      remoteUrl: remote,
    })
    delete repoMappings.value[keyFor(remote)]
    delete repoStatusMap.value[keyFor(remote)]
    ElMessage.success('本地仓库关联已取消')
  }

  return {
    authStore,
    desktop,
    electronAvailable,
    initialized,
    token,
    workspace,
    task,
    proposal,
    proposalFiles,
    patchText,
    repoPatches,
    proposalLoading,
    proposalGenerating,
    patchLoading,
    repoMappings,
    repoStatusMap,
    activeRemoteUrl,
    pendingLocalPath,
    repoPath,
    repoRemoteUrl,
    repoStatus,
    repoMapping,
    workspaceId,
    expectedRemoteUrl,
    expectedRemoteUrls,
    mappedCount,
    missingRemotes,
    proposalRemotes,
    applyMissingRemotes,
    hasProposal,
    repoReady,
    repoReadyFor,
    mappingFor,
    statusFor,
    loadLocalConfig,
    syncCurrentAuthToConfig,
    setWorkspaceContext,
    setTaskContext,
    loadLatestProposal,
    generateChangeProposal,
    downloadPatch,
    loadRepoPatches,
    loadRepoMapping,
    chooseRepo,
    chooseRepoFor,
    validateRepo,
    validateRemote,
    saveRepoMapping,
    saveMappingFor,
    removeRepoMapping,
    removeMappingFor,
  }
})

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useLocalAgentStore, import.meta.hot))
}
