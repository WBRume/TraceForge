import { computed, onScopeDispose, shallowRef, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { useProvisioningStore } from '@/stores/provisioning'
import type {
  AssetAiJob, AssetResolutionProposal, ResolutionApplyPayload, ResolutionDecisionPayload, useAssetDiscussion,
} from '@/composables/useAssetDiscussion'

type RewriteScope = 'anchor' | 'document'
type RewriteRequest = { threadId: string; proposalId: string; text: string; scope: RewriteScope }
type Anchor = { block_id: string; selected_text: string; char_start?: number; char_end?: number }
type ComparisonRequest = { threadIds: string[]; draftId: string }

function hasComparison(proposal: AssetResolutionProposal) {
  const patch = proposal.proposed_patch_json
  return Boolean(patch?.native_revision || patch?.merged_blocks_ast?.length || patch?.merged_block_ast)
}

export function useResolutionReview(options: {
  workspaceId: Readonly<Ref<string>>
  assetId: Readonly<Ref<string>>
  versionId: Readonly<Ref<string>>
  canGenerate: Readonly<Ref<boolean>>
  canApply: Readonly<Ref<boolean>>
  unavailableReason: Readonly<Ref<string>>
  requestedJobId: () => string | undefined
  onJobOpened: (jobId: string) => void
  discussion: ReturnType<typeof useAssetDiscussion>
}) {
  const { t } = useI18n()
  const store = useProvisioningStore()
  const { workspaceId, assetId, versionId, discussion } = options
  const threadsReady = computed(() => discussion.initialized.value && !discussion.loadingThreads.value)
  const showPicker = shallowRef(false)
  const selectedProposalId = shallowRef('')
  const dialogJobId = shallowRef('')
  const overwriteRequest = shallowRef<ComparisonRequest | null>(null)
  const relocation = shallowRef<RewriteRequest | null>(null)
  const submitting = shallowRef(false)
  const cancelling = shallowRef(false)
  const applying = shallowRef(false)
  const resultError = shallowRef('')
  let generation = 0

  const findProposal = (id: string) => discussion.threads.value.find(thread => thread.proposals?.some(item => item.id === id))
  const selectedProposal = computed(() => findProposal(selectedProposalId.value)?.proposals
    .find(item => item.id === selectedProposalId.value) || null)
  const dialogJob = computed(() => store.getTrackedJob(dialogJobId.value))
  const comparison = computed(() => !dialogJobId.value && selectedProposal.value && hasComparison(selectedProposal.value)
    ? selectedProposal.value : null)
  const legacyProposal = computed(() => !dialogJobId.value && !comparison.value ? selectedProposal.value : null)
  const pendingJobs = computed(() => store.jobList.flatMap(job => {
    const revision = job.revisionJob
    return revision && !job.terminal && revision.workspace_id === workspaceId.value
      && revision.asset_id === assetId.value && revision.context_json?.context_version_id === versionId.value
      ? [revision] : []
  }))

  const blockedReason = computed(() => {
    const proposal = selectedProposal.value
    const sources = proposal?.proposed_patch_json?.source_thread_ids
    if (!proposal) return ''
    if ((proposal.proposed_patch_json?.native_revision || sources?.length)
        && proposal.base_version_id !== versionId.value) return t('doc_review.joint_proposal_version_changed')
    if (!Array.isArray(sources) || !sources.length) return ''
    if (sources.some(id => !discussion.threads.value.some(thread => thread.id === id && thread.status === 'resolved'))) {
      return t('doc_review.joint_proposal_sources_changed')
    }
    return ''
  })

  const releaseJob = (expand = false) => {
    if (dialogJobId.value) store.minimizePreviewJob(dialogJobId.value, expand)
    dialogJobId.value = ''
    cancelling.value = false
    resultError.value = ''
  }

  const reset = () => {
    generation += 1
    releaseJob()
    showPicker.value = false
    selectedProposalId.value = ''
    overwriteRequest.value = null
    relocation.value = null
    submitting.value = cancelling.value = applying.value = false
  }

  watch([workspaceId, assetId, versionId], reset, { flush: 'sync' })
  onScopeDispose(reset)

  const openProposal = (proposalId: string) => {
    if (!findProposal(proposalId)) return false
    releaseJob()
    selectedProposalId.value = proposalId
    showPicker.value = false
    return true
  }

  const selectSources = () => {
    selectedProposalId.value = ''
    showPicker.value = true
  }

  const closeSources = () => {
    if (submitting.value) return
    showPicker.value = false
    selectedProposalId.value = ''
  }

  const attachJob = (jobId: string) => {
    releaseJob()
    showPicker.value = false
    selectedProposalId.value = ''
    store.showRevisionJobInDialog(jobId)
    dialogJobId.value = jobId
  }

  const openJob = async (jobId: string, isRequested = () => true) => {
    const owner = generation
    try {
      let job = store.getTrackedJob(jobId)?.revisionJob
      if (!job) {
        const { data } = await api.get<AssetAiJob>(`/document-revision-jobs/${encodeURIComponent(jobId)}`)
        job = data
      }
      if (generation !== owner || !isRequested()) return
      if (job.workspace_id !== workspaceId.value || job.asset_id !== assetId.value) {
        throw new Error(t('doc_review.revision_result_load_failed'))
      }
      if (!store.ingestRevisionJob(job)) throw new Error(t('doc_review.revision_result_load_failed'))
      attachJob(jobId)
    } catch (error) {
      if (generation === owner && isRequested()) ElMessage.error(formatApiError(error, t('doc_review.revision_result_load_failed'), t))
    }
  }

  watch(() => [options.requestedJobId(), assetId.value, versionId.value] as const, async ([jobId, asset, version], _, onCleanup) => {
    if (!jobId || !asset || !version) return
    let current = true
    onCleanup(() => { current = false })
    await openJob(jobId, () => current)
    if (current) options.onJobOpened(jobId)
  }, { immediate: true })

  const loadResult = async () => {
    const job = dialogJob.value?.revisionJob
    if (!job?.thread_id || job.status !== 'SUCCESS' || !threadsReady.value) return
    const owner = generation
    const current = () => generation === owner && dialogJobId.value === job.id && threadsReady.value
    resultError.value = ''
    try {
      const id = String(job.result_json?.proposal_id || '')
      const thread = await discussion.fetchThread(job.thread_id)
      if (!current()) return
      const proposal = thread?.proposals.find(item => item.id === id)
      if (!proposal || !hasComparison(proposal) || !openProposal(id)) throw new Error()
      store.markPreviewJobViewed(job.id)
    } catch {
      if (current()) resultError.value = t('doc_review.revision_result_load_failed')
    }
  }

  watch(() => threadsReady.value && dialogJob.value?.status === 'SUCCESS' ? dialogJobId.value : '', id => {
    if (id) void loadResult()
  })

  const closeRevision = async () => {
    if (applying.value || cancelling.value || submitting.value) return
    const job = dialogJob.value
    if (job && !job.terminal && !job.cancelRequested) {
      const owner = generation
      cancelling.value = true
      const cancelled = await store.cancelPreviewJob(job.jobId)
      if (owner !== generation || dialogJobId.value !== job.jobId) return
      cancelling.value = false
      if (!cancelled) {
        ElMessage.error(t('doc_review.ai_cancel_failed'))
        return
      }
    }
    const latest = job && store.getTrackedJob(job.jobId)
    if (latest?.terminal && latest.status !== 'SUCCESS') store.dismiss(latest.jobId)
    releaseJob()
    selectedProposalId.value = ''
  }

  const submit = async (path: string, payload: object) => {
    if (submitting.value) return null
    if (!options.canGenerate.value) {
      ElMessage.warning(options.unavailableReason.value)
      return null
    }
    const owner = generation
    const base = `/workspaces/${encodeURIComponent(workspaceId.value)}/assets/${encodeURIComponent(assetId.value)}`
    submitting.value = true
    try {
      // Submission can be acknowledged after navigation. The shared store still owns the job.
      const { data } = await api.post<AssetAiJob>(`${base}${path}`, payload)
      const current = owner === generation
      const job = store.ingestRevisionJob(data, !current)
      if (job && current) attachJob(job.jobId)
      return job
    } catch (error) {
      if (owner === generation) throw error
      return null
    } finally {
      if (owner === generation) submitting.value = false
    }
  }

  const generate = async (selected: string[], overwrite = false) => {
    if (!versionId.value || !selected.length || submitting.value) return
    const threadIds = [...new Set(selected)].sort()
    const matchesSources = (sources: unknown) => Array.isArray(sources)
      && sources.length === threadIds.length && threadIds.every(id => sources.includes(id))
    const running = pendingJobs.value.find(job => matchesSources(job.context_json?.source_thread_ids))
    if (running) {
      attachJob(running.id)
      return
    }
    if (!overwrite) {
      const owner = discussion.threads.value.find(thread => thread.id === threadIds[0])
      const draft = owner?.proposals.find(item => item.status === 'draft' && item.base_version_id === versionId.value
        && matchesSources(item.proposed_patch_json?.source_thread_ids))
      if (draft) {
        overwriteRequest.value = { threadIds, draftId: draft.id }
        return
      }
    }
    try {
      await submit('/resolution/proposals', {
        thread_ids: threadIds, context_version_id: versionId.value, overwrite_existing_draft: overwrite,
      })
    } catch (error) {
      const response = (error as { response?: { status?: number; data?: { detail?: { existing_draft_id?: string } } } }).response
      const draftId = response?.status === 409 ? response.data?.detail?.existing_draft_id : undefined
      if (draftId) overwriteRequest.value = { threadIds, draftId }
      else ElMessage.error(formatApiError(error, t('doc_review.proposal_create_failed'), t))
    }
  }

  const keepDraft = async () => {
    const request = overwriteRequest.value
    overwriteRequest.value = null
    if (!request || openProposal(request.draftId)) return
    const owner = generation
    try {
      await discussion.fetchThread(request.threadIds[0]!)
      if (owner === generation && !openProposal(request.draftId)) throw new Error()
    } catch {
      if (owner === generation) ElMessage.error(t('doc_review.revision_result_load_failed'))
    }
  }

  const overwriteDraft = async () => {
    const request = overwriteRequest.value
    overwriteRequest.value = null
    if (request) await generate(request.threadIds, true)
  }

  const submitRewrite = async (request: RewriteRequest, anchor?: Anchor) => {
    const owner = generation
    try {
      const job = await submit(`/threads/${request.threadId}/resolution/proposals/${request.proposalId}/rewrite`, {
        proposal_text: request.text, rewrite_scope: request.scope,
        context_version_id: versionId.value, relocated_anchor: anchor,
      })
      if (anchor && job && owner === generation) ElMessage.success(t('doc_review.anchor_relocation_applied'))
    } catch (error) {
      ElMessage.error(formatApiError(error, t('doc_review.proposal_rewrite_failed'), t))
      openProposal(request.proposalId)
    }
  }

  const rewrite = async (proposalId: string, text: string, scope: RewriteScope) => {
    const thread = findProposal(proposalId)
    if (!thread || !options.canGenerate.value || blockedReason.value) return
    const request = { threadId: thread.id, proposalId, text, scope }
    if (scope === 'anchor' && thread.anchor_status === 'missing') {
      relocation.value = request
      selectedProposalId.value = ''
      ElMessage.warning(t('doc_review.anchor_relocation_required'))
      return
    }
    await submitRewrite(request)
  }

  const relocate = async (anchor: Anchor) => {
    const request = relocation.value
    relocation.value = null
    if (request) await submitRewrite(request, anchor)
  }

  const regenerate = (proposalId: string, text: string, scope: RewriteScope) => {
    const sources = selectedProposal.value?.proposed_patch_json?.source_thread_ids
    if (Array.isArray(sources) && sources.length) return generate(sources, true)
    return rewrite(proposalId, text, scope)
  }

  const apply = async (proposalId: string, payload: ResolutionApplyPayload, decision?: ResolutionDecisionPayload | null) => {
    const thread = findProposal(proposalId)
    if (!thread || !options.canApply.value || blockedReason.value || applying.value) return
    const owner = generation
    applying.value = true
    try {
      await discussion.applyResolutionProposal(thread.id, proposalId, payload, undefined, decision)
      if (owner === generation) selectedProposalId.value = ''
    } catch (error) {
      if (owner === generation) ElMessage.error(formatApiError(error, t('doc_review.proposal_apply_failed'), t))
    } finally {
      if (owner === generation) applying.value = false
    }
  }

  return {
    showPicker, legacyProposal, comparison, dialogJob, pendingJobs, overwriteRequest, relocation,
    blockedReason, submitting, cancelling, applying, resultError,
    selectSources, closeSources, generate, openJob, openProposal, keepDraft, overwriteDraft,
    closeRevision, minimize: () => releaseJob(true), loadResult, rewrite, regenerate, relocate, apply, reset,
  }
}
