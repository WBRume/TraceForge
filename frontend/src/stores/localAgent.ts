import { computed, ref } from 'vue'
import { acceptHMRUpdate, defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  createTaskChangeProposal,
  downloadChangeProposalPatch,
  getLatestChangeProposal,
  listChangeProposalFiles,
} from '@/services/agentApi'
import type { AgentTask, ChangeProposal, ChangeProposalFile } from '@/types/agent'
import type { DesktopRepoMapping } from '@/types/sddDesktop'
import { DEFAULT_SERVER_URL, setApiServerUrl } from '@/utils/api'
import { getSddDesktop, isElectron } from '@/utils/runtime'
import { normalizeRemoteUrl, remoteUrlsMatch } from '@/composables/local-agent/localAgentUtils'

type WorkspaceLike = {
  id?: string
  git_repo_url?: string | null
}

type TaskLike = Partial<AgentTask> & {
  id: string
  workspace_id?: string
  git_repo_url?: string | null
}

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
  const proposalLoading = ref(false)
  const proposalGenerating = ref(false)
  const patchLoading = ref(false)

  const repoPath = ref('')
  const repoRemoteUrl = ref('')
  const repoStatus = ref('')
  const repoMapping = ref<DesktopRepoMapping | null>(null)

  const workspaceId = computed(() => task.value?.workspace_id || workspace.value?.id || '')
  const expectedRemoteUrl = computed(() => (
    proposal.value?.base_repo_url
    || task.value?.git_repo_url
    || workspace.value?.git_repo_url
    || ''
  ))
  const hasProposal = computed(() => Boolean(proposal.value && patchText.value))
  const repoReady = computed(() => (
    Boolean(repoPath.value && repoRemoteUrl.value && expectedRemoteUrl.value)
    && remoteUrlsMatch(repoRemoteUrl.value, expectedRemoteUrl.value)
    && repoStatus.value.startsWith('Clean')
  ))

  const resetProposalState = () => {
    proposal.value = null
    proposalFiles.value = []
    patchText.value = ''
  }

  const resetRepoState = () => {
    repoMapping.value = null
    repoPath.value = ''
    repoRemoteUrl.value = ''
    repoStatus.value = ''
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
      return null
    }
    const files = await listChangeProposalFiles(proposal.value.id)
    proposalFiles.value = files.items
    await downloadPatch()
    return proposal.value
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
    if (!desktop || !workspaceId.value || !expectedRemoteUrl.value) return
    repoMapping.value = await desktop.config.getRepoMapping({
      workspaceId: workspaceId.value,
      remoteUrl: expectedRemoteUrl.value,
    })
    repoPath.value = repoMapping.value?.localPath || ''
    if (repoPath.value) {
      await validateRepo()
    }
  }

  const chooseRepo = async () => {
    if (!desktop) return
    const result = await desktop.git.selectDirectory()
    if (result.canceled || !result.path) return
    repoPath.value = result.path
    await validateRepo()
  }

  const validateRepo = async () => {
    if (!desktop || !repoPath.value) return
    const valid = await desktop.git.validateGitRepo(repoPath.value)
    if (!valid.ok) {
      repoRemoteUrl.value = ''
      repoStatus.value = valid.stderr || '所选目录不是 Git 仓库'
      return
    }
    const remote = await desktop.git.getRemoteUrl(repoPath.value)
    repoRemoteUrl.value = remote.remoteUrl
    const status = await desktop.git.getStatus(repoPath.value)
    repoStatus.value = status.isClean
      ? `Clean · ${normalizeRemoteUrl(remote.remoteUrl)}`
      : `Dirty · ${status.entries.length} changed files`
  }

  const saveRepoMapping = async (lastVerificationCommand?: string | null) => {
    if (!desktop || !workspaceId.value || !repoPath.value || !expectedRemoteUrl.value) return
    await validateRepo()
    if (!remoteUrlsMatch(repoRemoteUrl.value, expectedRemoteUrl.value)) {
      ElMessage.error('本地仓库 remote.origin.url 与工作区仓库地址不一致')
      return
    }
    if (!repoStatus.value.startsWith('Clean')) {
      ElMessage.error('本地仓库存在未提交修改，请清理后再绑定')
      return
    }
    repoMapping.value = await desktop.config.setRepoMapping({
      workspaceId: workspaceId.value,
      remoteUrl: expectedRemoteUrl.value,
      localPath: repoPath.value,
      lastVerificationCommand: lastVerificationCommand ?? repoMapping.value?.lastVerificationCommand ?? null,
    })
    ElMessage.success('本地仓库已绑定')
  }

  const removeRepoMapping = async () => {
    if (!desktop || !workspaceId.value || !expectedRemoteUrl.value) return
    await desktop.config.removeRepoMapping({
      workspaceId: workspaceId.value,
      remoteUrl: expectedRemoteUrl.value,
    })
    resetRepoState()
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
    proposalLoading,
    proposalGenerating,
    patchLoading,
    repoPath,
    repoRemoteUrl,
    repoStatus,
    repoMapping,
    workspaceId,
    expectedRemoteUrl,
    hasProposal,
    repoReady,
    loadLocalConfig,
    syncCurrentAuthToConfig,
    setWorkspaceContext,
    setTaskContext,
    loadLatestProposal,
    generateChangeProposal,
    downloadPatch,
    loadRepoMapping,
    chooseRepo,
    validateRepo,
    saveRepoMapping,
    removeRepoMapping,
  }
})

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useLocalAgentStore, import.meta.hot))
}
