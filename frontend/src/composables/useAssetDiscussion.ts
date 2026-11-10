import { computed, onScopeDispose, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { createAssetRequestScope, type AssetRequestOwner } from './asset-discussion/requestScope'
import { useAssetDocument } from './asset-discussion/useAssetDocument'
import { useAssetThreads } from './asset-discussion/useAssetThreads'
import { useAssetThreadJobs } from './asset-discussion/useAssetThreadJobs'
import { useAssetDiscussionSubscription } from './asset-discussion/useAssetDiscussionSubscription'

export type * from './asset-discussion/types'

type UseAssetDiscussionOptions = {
  wsId: MaybeRefOrGetter<string>
  assetId: MaybeRefOrGetter<string | null | undefined>
}

export function useAssetDiscussion(options: UseAssetDiscussionOptions) {
  const { t } = useI18n()
  const authStore = useAuthStore()
  const wsId = computed(() => String(toValue(options.wsId) || ''))
  const assetId = computed(() => String(toValue(options.assetId) || ''))
  const scope = createAssetRequestScope()
  const document = useAssetDocument(scope, () => t('doc_review.document_load_failed'))
  const jobs = useAssetThreadJobs(scope, (threadId, owner) => discussion.fetchThread(threadId, owner))
  const discussion = useAssetThreads(scope, document, jobs, refresh)
  const subscription = useAssetDiscussionSubscription(document, discussion, jobs, refresh, () => authStore.token || '')

  async function refresh(versionId?: string, owner = scope.capture()): Promise<void> {
    await scope.run('refresh', owner, async (request) => {
      const data = await document.loadDocument(versionId, request)
      if (!request.isCurrent() || !data || document.documentData.value !== data) return
      await Promise.all([
        document.loadVersions(request),
        discussion.loadThreads(versionId || data.active_version?.id || undefined, request),
      ])
    }, undefined)
  }

  const cleanup = () => {
    scope.invalidate()
    jobs.reset()
    subscription.disconnect()
  }

  watch([wsId, assetId], ([workspaceId, documentId], _previous, onCleanup) => {
    cleanup()
    document.reset()
    discussion.reset()
    const owner = scope.activate(workspaceId, documentId)
    onCleanup(cleanup)
    if (!owner) return
    void initialize(owner)
  }, { immediate: true, flush: 'sync' })

  async function initialize(owner: AssetRequestOwner) {
    try {
      await refresh(undefined, owner)
    } catch {
      // Keep live synchronization available after a transient initial query failure.
    }
    if (owner.isCurrent()) subscription.connect(owner)
  }

  onScopeDispose(cleanup)

  return {
    documentData: document.documentData,
    versions: document.versions,
    threads: discussion.threads,
    selectedThreadId: discussion.selectedThreadId,
    selectedThread: discussion.selectedThread,
    markersByBlock: document.markersByBlock,
    activeVersionId: document.activeVersionId,
    capabilities: document.capabilities,
    loadingDocument: document.loadingDocument,
    loadingVersions: document.loadingVersions,
    loadingThreads: discussion.loadingThreads,
    onlineUsers: subscription.onlineUsers,
    wsConnected: subscription.wsConnected,
    assistantJobMap: jobs.assistantJobMap,
    proposalJobMap: jobs.proposalJobMap,
    error: document.error,
    clearError: document.clearError,
    loadDocument: document.loadDocument,
    loadVersions: document.loadVersions,
    loadThreads: discussion.loadThreads,
    loadThreadJobs: async (threadId: string, activeOnly = true) => (await jobs.loadThreadJobs(threadId, activeOnly)) || [],
    refresh,
    createThread: discussion.createThread,
    sendThreadMessage: discussion.sendThreadMessage,
    askAi: discussion.askAi,
    createResolutionProposal: discussion.createResolutionProposal,
    rewriteResolutionProposal: discussion.rewriteResolutionProposal,
    applyResolutionProposal: discussion.applyResolutionProposal,
    manualEditBlock: discussion.manualEditBlock,
    cancelAiJob: jobs.cancelAiJob,
    updateThreadCloseHint: discussion.updateThreadCloseHint,
    updateThreadState: discussion.updateThreadState,
    fetchThread: discussion.fetchThread,
  }
}
