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
import { readRepoPreferences, saveRepoPreferences } from '@/composables/localRepoPreferences'
import { remoteUrlsMatch } from '@/composables/local-agent/localAgentUtils'
import { getSddDesktop, isElectron } from '@/utils/runtime'
import { normalizeRemoteUrl } from '@/composables/local-agent/localAgentUtils'
import { chooseGitRemote, getLocalGitRemotes } from '@/composables/local-agent/localGitRemotes'

type WorkspaceLike = {
  id?: string
  git_repo_url?: string | null
  repositories?: { id?: string; repository_id?: string; repo_url?: string; repo_name?: string }[]
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
    return Boolean(mapping?.localPath && (status.startsWith('Clean') || status.startsWith('Dirty')))
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
    // 仅在本地登录态缺失时采纳桌面持久化 token（避免旧 config token 复活/覆盖当前会话；
    // 登出时 auth store 已同步清理 config.token，见 stores/auth.ts clearDesktopPersistedToken）
    if (config.token && !authStore.token) {
      authStore.setToken(config.token)
    }
    token.value = authStore.token || config.token || ''
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

  const repositoryIdForRemote = (remote: string): string => {
    const ws = workspace.value
    if (!ws) return ''
    const repos = Array.isArray(ws.repositories) ? ws.repositories : []
    const found = repos.find(r => remoteUrlsMatch(r.repo_url, remote))
    return found?.repository_id || found?.id || ''
  }

  const syncToPreferences = (wsId: string, userId: string, mapping: DesktopRepoMapping) => {
    const current = readRepoPreferences(wsId, userId)
    const repoId = repositoryIdForRemote(mapping.remoteUrl)
    const next = current.filter(r => (
      (repoId ? r.repository_id !== repoId : true) &&
      !remoteUrlsMatch(r.configured_git_url, mapping.remoteUrl)
    ))
    next.push({
      repository_id: repoId || mapping.remoteUrl,
      local_path: mapping.localPath,
      configured_git_url: mapping.gitRemoteUrl || mapping.remoteUrl,
    })
    saveRepoPreferences(wsId, userId, next)
  }

  const removeFromPreferences = (wsId: string, userId: string, remote: string) => {
    const current = readRepoPreferences(wsId, userId)
    const repoId = repositoryIdForRemote(remote)
    const next = current.filter(r => (
      (repoId ? r.repository_id !== repoId : true) &&
      !remoteUrlsMatch(r.configured_git_url, remote)
    ))
    saveRepoPreferences(wsId, userId, next)
  }

  const loadRepoMapping = async () => {
    resetRepoState()
    const targetWsId = workspaceId.value
    if (!targetWsId) return
    const remotes = expectedRemoteUrls.value
    activeRemoteUrl.value = remotes[0] || ''
    if (remotes.length === 0) return

    

    const userId = String(authStore.user?.id || '')
    const localPrefs = readRepoPreferences(targetWsId, userId)

    for (const remote of remotes) {
      try {
        let mapping: DesktopRepoMapping | null = null

        // 1. 若有桌面客户端，先从 desktop.config 读取
        let fromDesktop = false
        if (desktop) {
          mapping = await desktop.config.getRepoMapping({
            workspaceId: targetWsId,
            remoteUrl: remote,
          })
          if (mapping?.localPath) fromDesktop = true
        }

        const repoId = repositoryIdForRemote(remote)

        // 2. 若未从 desktop 获取到有效路径，尝试从 localStorage preferences 回显
        if (!mapping?.localPath) {
          const matchedPref = localPrefs.find(p => (
            (repoId && p.repository_id === repoId) ||
            remoteUrlsMatch(p.configured_git_url, remote)
          ))
          if (matchedPref?.local_path) {
            mapping = {
              workspaceId: targetWsId,
              remoteUrl: remote,
              localPath: matchedPref.local_path,
              gitRemoteUrl: matchedPref.configured_git_url || remote,
              updatedAt: new Date().toISOString(),
            }
          }
        }

        

        if (mapping?.localPath) {
          if (!mapping.gitRemoteUrl) {
            if (desktop) {
              const availableRemotes = await getLocalGitRemotes(mapping.localPath)
              mapping.gitRemoteUrl = chooseGitRemote(availableRemotes, { preferredUrl: remote })?.fetchUrl || remote
            } else {
              mapping.gitRemoteUrl = remote
            }
          }
          repoMappings.value[keyFor(remote)] = mapping

          // 保持双向同步：如果不是来自桌面端的有效映射，补全写入 desktop.config
          if (desktop && !fromDesktop) {
            void desktop.config.setRepoMapping({
              workspaceId: targetWsId,
              remoteUrl: remote,
              localPath: mapping.localPath,
              gitRemoteUrl: mapping.gitRemoteUrl,
            }).catch(() => {})
          }
          syncToPreferences(targetWsId, userId, mapping)

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
    const targetPath = repoPath.value || pendingLocalPath.value
    if (!targetPath) return
    await validateRemote(activeRemoteUrl.value, targetPath)
  }

  const validateRemote = async (remote: string, localPath: string) => {
    if (!localPath) return
    const key = keyFor(remote)
    if (desktop) {
      const valid = await desktop.git.validateGitRepo(localPath)
      if (!valid.ok) {
        repoStatusMap.value[key] = valid.stderr || '所选目录不是 Git 仓库'
        return
      }
      const remotes = desktop.git.getFetchRemotes
        ? await desktop.git.getFetchRemotes(localPath)
        : [{ name: 'origin', fetchUrl: (await desktop.git.getRemoteUrl(localPath)).remoteUrl }]
      // Mapping is a user-selected patch destination, not remote identity validation.
      const remoteInfo = { remoteUrl: remotes.map(item => item.fetchUrl).filter(Boolean).join(', ') || '无 fetch remote' }
      const status = await desktop.git.getStatus(localPath)
      repoStatusMap.value[key] = status.isClean
        ? 'Clean · ' + remoteInfo.remoteUrl
        : 'Dirty · ' + remoteInfo.remoteUrl
    } else {
      const normalizedPath = localPath.trim()
      const isPathLike = /^[a-zA-Z]:[\\/]/.test(normalizedPath) || normalizedPath.startsWith('/')
      if (!isPathLike) {
        repoStatusMap.value[key] = '请输入有效的本机绝对路径（如 G:/repo 或 /home/repo）'
        return
      }
      repoStatusMap.value[key] = 'Clean · 本机路径已就绪'
    }
  }

  const saveRepoMapping = async (lastVerificationCommand?: string | null, gitRemoteUrl?: string) => {
    if (!workspaceId.value) return
    const remote = activeRemoteUrl.value
    const localPath = pendingLocalPath.value || repoPath.value
    if (!remote || !localPath) return
    await saveMappingFor(remote, localPath, lastVerificationCommand, gitRemoteUrl)
  }

  const saveMappingFor = async (
    remote: string,
    localPath: string,
    lastVerificationCommand?: string | null,
    gitRemoteUrl?: string,
  ): Promise<boolean> => {
    const targetWsId = workspaceId.value
    if (!targetWsId) return false
    await validateRemote(remote, localPath)
    const status = statusFor(remote)
    if (!status.startsWith('Clean') && !status.startsWith('Dirty')) {
      ElMessage.error(status || '本地仓库检测失败')
      return false
    }

    let finalGitRemoteUrl = gitRemoteUrl?.trim()
    if (!finalGitRemoteUrl) {
      if (desktop) {
        const defaultGitRemote = chooseGitRemote(await getLocalGitRemotes(localPath), {
          currentUrl: mappingFor(remote)?.gitRemoteUrl,
          preferredUrl: remote,
        })
        finalGitRemoteUrl = defaultGitRemote?.fetchUrl || remote
      } else {
        finalGitRemoteUrl = mappingFor(remote)?.gitRemoteUrl || remote
      }
    }

    let mapping: DesktopRepoMapping
    if (desktop) {
      mapping = await desktop.config.setRepoMapping({
        workspaceId: targetWsId,
        remoteUrl: remote,
        localPath,
        gitRemoteUrl: finalGitRemoteUrl,
        lastVerificationCommand: lastVerificationCommand ?? null,
      })
    } else {
      mapping = {
        workspaceId: targetWsId,
        remoteUrl: remote,
        localPath,
        gitRemoteUrl: finalGitRemoteUrl,
        lastVerificationCommand: lastVerificationCommand ?? null,
        updatedAt: new Date().toISOString(),
      }
    }

    repoMappings.value[keyFor(remote)] = mapping
    const userId = String(authStore.user?.id || '')
    syncToPreferences(targetWsId, userId, mapping)

    ElMessage.success('本地仓库已绑定')
    return true
  }

  const removeRepoMapping = async () => {
    if (!workspaceId.value || !activeRemoteUrl.value) return
    await removeMappingFor(activeRemoteUrl.value)
  }

  const removeMappingFor = async (remote: string): Promise<void> => {
    const targetWsId = workspaceId.value
    if (!targetWsId) return
    if (desktop) {
      await desktop.config.removeRepoMapping({
        workspaceId: targetWsId,
        remoteUrl: remote,
      })
    }
    const userId = String(authStore.user?.id || '')
    removeFromPreferences(targetWsId, userId, remote)

    delete repoMappings.value[keyFor(remote)]
    delete repoStatusMap.value[keyFor(remote)]
    ElMessage.success('本地仓库关联已取消')
  }
  return {
    authStore,
    desktop: computed(() => desktop),
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
