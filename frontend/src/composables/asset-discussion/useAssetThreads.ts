import { computed, ref, shallowRef } from 'vue'
import api from '@/utils/api'
import type { AssetAiJob, AssetThread, AssetThreadMessage, AssetVersion, ResolutionApplyPayload, ResolutionDecisionPayload } from './types'
import type { AssetRequestScope } from './requestScope'
import type { AssetDocumentModel, RefreshAssetDocument } from './useAssetDocument'
import type { AssetThreadJobsModel } from './useAssetThreadJobs'

export function useAssetThreads(
  scope: AssetRequestScope,
  document: AssetDocumentModel,
  jobs: AssetThreadJobsModel,
  refresh: RefreshAssetDocument,
) {
  const { activeVersionId } = document
  const threads = ref<AssetThread[]>([])
  const loadingThreads = shallowRef(false)
  const selectedThreadId = shallowRef('')
  const selectedThread = computed(() => threads.value.find(item => item.id === selectedThreadId.value) || null)

  const setThread = (thread: AssetThread, owner = scope.capture()) => {
    if (!owner?.isCurrent() || thread.asset_id !== owner.assetId || thread.workspace_id !== owner.wsId) return
    const index = threads.value.findIndex(item => item.id === thread.id)
    if (index < 0) threads.value.push(thread)
    else threads.value[index] = thread
    threads.value.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
  }

  const fetchThread = (threadId: string, owner = scope.capture()) => {
    const versionId = activeVersionId.value
    return scope.run<AssetThread | undefined>(`thread:${threadId}`, threadId ? owner : undefined, async (request) => {
      const res = await api.get(`${request.baseUrl}/threads/${threadId}`, {
        params: { context_version_id: versionId || undefined }, signal: request.signal,
      })
      if (!request.isCurrent() || activeVersionId.value !== versionId) return
      const thread = res.data as AssetThread
      setThread(thread, request)
      return thread
    }, undefined)
  }

  const loadThreads = (versionId?: string, owner = scope.capture()) => scope.run<AssetThread[]>(
    'threads', owner, async (request) => {
      loadingThreads.value = true
      try {
        const res = await api.get(`${request.baseUrl}/threads`, {
          params: { context_version_id: versionId || undefined }, signal: request.signal,
        })
        if (!request.isCurrent() || (versionId && activeVersionId.value !== versionId)) return []
        threads.value = ((res.data?.items || []) as AssetThread[]).filter(item => (
          item.asset_id === request.assetId && item.workspace_id === request.wsId
        ))
        if (selectedThreadId.value && !threads.value.some(item => item.id === selectedThreadId.value)) {
          selectedThreadId.value = ''
        }
        await jobs.refreshThreadJobs(threads.value.map(item => item.id), request)
        return request.isCurrent() ? threads.value : []
      } finally {
        if (request.isLatest()) loadingThreads.value = false
      }
    }, [],
  )

  const createThread = async (payload: {
    block_id: string
    body: string
    selected_text?: string
    char_start?: number | null
    char_end?: number | null
    version_id?: string
  }) => {
    return scope.run(null, scope.capture(), async (request) => {
      const res = await api.post(`${request.baseUrl}/threads`, payload,
        { signal: request.signal },
      )
      if (!request.isCurrent()) return null
      const thread = res.data as AssetThread
      setThread(thread, request)
      selectedThreadId.value = thread.id
      await document.loadDocument(payload.version_id || activeVersionId.value || undefined, request)
      return request.isCurrent() ? thread : null
    }, null)
  }

  const sendThreadMessage = async (threadId: string, content: string) => {
    return scope.run(null, (!threadId) ? undefined : scope.capture(), async (request) => {
      const res = await api.post(
        `${request.baseUrl}/threads/${threadId}/messages`,
        { content },
        { signal: request.signal },
      )
      if (!request.isCurrent()) return null
      const created = res.data as AssetThreadMessage
      const thread = threads.value.find(item => item.id === threadId)
      if (thread && !thread.messages.some(item => item.id === created.id)) {
        thread.messages.push(created)
        thread.messages.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
        document.setMarkerCount(threadId, 1)
      }
      return created
    }, null)
  }

  const askAi = async (threadId: string, prompt?: string) => {
    return scope.run(null, (!threadId) ? undefined : scope.capture(), async (request) => {
      const res = await api.post(
        `${request.baseUrl}/threads/${threadId}/ai-jobs`,
        { prompt: prompt?.trim() || undefined },
        { signal: request.signal },
      )
      if (!request.isCurrent()) return null
      const job = res.data as AssetAiJob
      jobs.setThreadJob(job, request)
      return job
    }, null)
  }

  const createResolutionProposal = async (
    threadId: string,
    overwriteExistingDraft = false,
    contextVersionId?: string,
  ) => {
    return scope.run(null, (!threadId) ? undefined : scope.capture(), async (request) => {
      const res = await api.post(
        `${request.baseUrl}/threads/${threadId}/resolution/proposals`,
        {
          overwrite_existing_draft: overwriteExistingDraft,
          context_version_id: contextVersionId || undefined,
        },
        { signal: request.signal },
      )
      if (!request.isCurrent()) return null
      const job = res.data as AssetAiJob
      jobs.setThreadJob(job, request)
      return job
    }, null)
  }

  const rewriteResolutionProposal = async (
    threadId: string,
    proposalId: string,
    proposalText: string,
    rewriteScope: 'anchor' | 'document' = 'anchor',
    contextVersionId?: string,
    relocatedAnchor?: {
      block_id: string
      selected_text?: string
      char_start?: number | null
      char_end?: number | null
    },
  ) => {
    return scope.run(null, (!threadId || !proposalId) ? undefined : scope.capture(), async (request) => {
      const normalized = proposalText.trim()
      const normalizedScope = rewriteScope === 'document' ? 'document' : 'anchor'
      const res = await api.post(
        `${request.baseUrl}/threads/${threadId}/resolution/proposals/${proposalId}/rewrite`,
        {
          proposal_text: normalized,
          rewrite_scope: normalizedScope,
          context_version_id: contextVersionId || undefined,
          relocated_anchor: relocatedAnchor
            ? {
              block_id: relocatedAnchor.block_id,
              selected_text: relocatedAnchor.selected_text || undefined,
              char_start: relocatedAnchor.char_start ?? undefined,
              char_end: relocatedAnchor.char_end ?? undefined,
            }
            : undefined,
        },
        { signal: request.signal },
      )
      if (!request.isCurrent()) return null
      const job = res.data as AssetAiJob
      jobs.setThreadJob(job, request)
      return job
    }, null)
  }

  const applyResolutionProposal = async (
    threadId: string,
    proposalId: string,
    payload: ResolutionApplyPayload,
    changeNote?: string,
    decision?: ResolutionDecisionPayload | null,
  ) => {
    return scope.run(null, (!threadId || !proposalId) ? undefined : scope.capture(), async (request) => {
      const body: Record<string, any> = {
        proposal_id: proposalId,
        change_note: changeNote?.trim() || undefined,
      }
      if (Array.isArray(payload?.finalBlocksAst) && payload.finalBlocksAst.length) {
        body.final_blocks_ast = payload.finalBlocksAst
      } else {
        body.final_block_ast = payload?.finalBlockAst
      }
      if (decision?.title?.trim()) {
        body.decision = {
          ...decision,
          title: decision.title.trim(),
        }
      }
      const res = await api.post(
        `${request.baseUrl}/threads/${threadId}/resolution/apply`,
        body,
        { signal: request.signal },
      )
      if (!request.isCurrent()) return null
      const version = res.data as AssetVersion
      await refresh(version.id, request)
      return request.isCurrent() ? version : null
    }, null)
  }

  const manualEditBlock = async (blockId: string, newText: string) => {
    return scope.run(null, (!blockId) ? undefined : scope.capture(), async (request) => {
      const res = await api.post(
        `${request.baseUrl}/document/blocks/${blockId}`,
        { new_text: newText },
        { signal: request.signal },
      )
      if (!request.isCurrent()) return null
      const version = res.data as AssetVersion
      await refresh(version.id, request)
      return request.isCurrent() ? version : null
    }, null)
  }

  const updateThreadCloseHint = async (
    threadId: string,
    action: 'mark_no_close_needed' | 'reset_pending',
    contextVersionId?: string,
  ) => {
    return scope.run(null, (!threadId) ? undefined : scope.capture(), async (request) => {
      const params: Record<string, string> = {}
      if (contextVersionId) {
        params.context_version_id = contextVersionId
      }
      const res = await api.post(
        `${request.baseUrl}/threads/${threadId}/close-hint`,
        { action },
        { params, signal: request.signal },
      )
      if (!request.isCurrent()) return null
      const thread = res.data as AssetThread
      setThread(thread, request)
      return request.isCurrent() ? thread : null
    }, null)
  }

  const updateThreadState = async (threadId: string, status: 'open' | 'resolved' | 'closed') => {
    return scope.run(null, (!threadId) ? undefined : scope.capture(), async (request) => {
      const res = await api.post(
        `${request.baseUrl}/threads/${threadId}/state`,
        { status },
        { signal: request.signal },
      )
      if (!request.isCurrent()) return null
      const thread = res.data as AssetThread
      setThread(thread, request)
      await document.loadDocument(activeVersionId.value || undefined, request)
      return request.isCurrent() ? thread : null
    }, null)
  }

  const reset = () => {
    threads.value = []
    selectedThreadId.value = ''
    loadingThreads.value = false
  }

  return {
    threads, selectedThreadId, selectedThread, loadingThreads, setThread, fetchThread, loadThreads,
    createThread, sendThreadMessage, askAi, createResolutionProposal, rewriteResolutionProposal,
    applyResolutionProposal, manualEditBlock, updateThreadCloseHint, updateThreadState, reset,
  }
}

export type AssetThreadsModel = ReturnType<typeof useAssetThreads>
