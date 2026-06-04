import { computed, onBeforeUnmount, ref, shallowRef, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'
import { buildBackendWsUrl } from '@/utils/ws'

export type AssetSummary = {
  id: string
  task_id: string
  workspace_id: string
  asset_type: string
  name: string
  created_at: string
}

export type AssetVersion = {
  id: string
  asset_id: string
  version_no: number
  base_version_id?: string | null
  original_ext?: string | null
  original_mime?: string | null
  normalized_markdown?: string | null
  blocks_json?: any
  render_json?: any
  change_note?: string | null
  created_by: string
  created_at: string
}

export type AssetThreadMarker = {
  thread_id: string
  block_id: string
  selected_text?: string | null
  char_start?: number | null
  char_end?: number | null
  status: 'open' | 'resolved' | 'closed'
  creator_id: string
  created_at: string
  message_count: number
}

export type AssetThreadMessage = {
  id: string
  thread_id: string
  role: 'user' | 'ai' | 'system'
  content: string
  creator_id?: string | null
  creator_display_name?: string | null
  creator_avatar_svg?: string | null
  metadata_json?: any
  created_at: string
}

export type AssetResolutionProposal = {
  id: string
  thread_id: string
  base_version_id: string
  proposed_patch_json?: any
  diff_text?: string | null
  status: 'draft' | 'applied' | 'discarded'
  creator_id: string
  created_at: string
  updated_at?: string | null
}

export type ResolutionApplyPayload = {
  finalBlockAst?: any
  finalBlocksAst?: any[]
}

export type ResolutionDecisionPayload = {
  title: string
  body?: string | null
  impact_scope?: string | null
  requirement_id?: string | null
  promote_candidate?: boolean
}

export type AssetThread = {
  id: string
  asset_id: string
  version_id: string
  task_id: string
  workspace_id: string
  block_id: string
  selected_text?: string | null
  char_start?: number | null
  char_end?: number | null
  status: 'open' | 'resolved' | 'closed'
  creator_id: string
  creator_display_name?: string | null
  creator_avatar_svg?: string | null
  resolved_by?: string | null
  resolved_at?: string | null
  resolved_version_id?: string | null
  close_hint_state?: 'none' | 'pending' | 'no_close_needed'
  close_hint_reason?: string | null
  close_hint_version_id?: string | null
  anchor_status?: 'valid' | 'missing'
  effective_anchor?: {
    block_id?: string
    selected_text?: string | null
    char_start?: number | null
    char_end?: number | null
    source?: string
    block_text?: string
  } | null
  created_at: string
  updated_at?: string | null
  messages: AssetThreadMessage[]
  proposals: AssetResolutionProposal[]
}

export type AssetDocumentCapabilities = {
  can_view: boolean
  can_comment: boolean
  can_ai_reply: boolean
  can_apply_resolution: boolean
  inline_review_enabled: boolean
  ai_available: boolean
  ai_unavailable_reason?: string | null
}

export type AssetDocumentPayload = {
  asset: AssetSummary
  active_version?: AssetVersion | null
  blocks: any[]
  thread_markers: AssetThreadMarker[]
  capabilities: AssetDocumentCapabilities
}

export type AssetAiJob = {
  id: string
  workspace_id: string
  task_id?: string | null
  asset_id?: string | null
  thread_id?: string | null
  channel: 'ASSET_THREAD' | 'TASK_CHAT'
  queue_key: string
  status: 'PENDING' | 'RUNNING' | 'WAITING_HITL' | 'SUCCESS' | 'FAILED' | 'CANCELLED'
  progress: number
  message?: string | null
  prompt_text?: string | null
  context_json?: Record<string, any> | null
  result_json?: Record<string, any> | null
  error_message?: string | null
  session_id?: string | null
  creator_id: string
  started_at?: string | null
  finished_at?: string | null
  created_at: string
  updated_at?: string | null
}

type ThreadJobKind = 'THREAD_AI_REPLY' | 'RESOLUTION_PROPOSAL' | 'RESOLUTION_REWRITE'

type UseAssetDiscussionOptions = {
  wsId: MaybeRefOrGetter<string>
  assetId: MaybeRefOrGetter<string | null | undefined>
  userId: MaybeRefOrGetter<string | null | undefined>
}

export function useAssetDiscussion(options: UseAssetDiscussionOptions) {
  const { t } = useI18n()
  const documentData = ref<AssetDocumentPayload | null>(null)
  const versions = ref<AssetVersion[]>([])
  const threads = ref<AssetThread[]>([])
  const loadingDocument = ref(false)
  const loadingVersions = ref(false)
  const loadingThreads = ref(false)
  const selectedThreadId = ref('')
  const onlineUsers = ref<string[]>([])
  const wsConnected = ref(false)
  const assistantJobMap = ref<Record<string, AssetAiJob>>({})
  const proposalJobMap = ref<Record<string, AssetAiJob>>({})
  const error = ref('')

  const ws = shallowRef<WebSocket | null>(null)
  const reconnectTimer = shallowRef<number | null>(null)
  const wsManualClose = ref(false)
  const jobPollTimers = shallowRef<Record<string, number>>({})

  const wsIdRef = computed(() => String(toValue(options.wsId) || ''))
  const assetIdRef = computed(() => {
    const val = toValue(options.assetId)
    return val ? String(val) : ''
  })
  const userIdRef = computed(() => {
    const val = toValue(options.userId)
    return val ? String(val) : 'anonymous'
  })

  const activeVersionId = computed(() => documentData.value?.active_version?.id || '')
  const markersByBlock = computed<Record<string, AssetThreadMarker[]>>(() => {
    const map: Record<string, AssetThreadMarker[]> = {}
    const markers = documentData.value?.thread_markers || []
    for (const marker of markers) {
      if (!map[marker.block_id]) {
        map[marker.block_id] = []
      }
      map[marker.block_id].push(marker)
    }
    return map
  })

  const selectedThread = computed(() => (
    threads.value.find(item => item.id === selectedThreadId.value) || null
  ))

  const capabilities = computed<AssetDocumentCapabilities>(() => (
    documentData.value?.capabilities || {
      can_view: false,
      can_comment: false,
      can_ai_reply: false,
      can_apply_resolution: false,
      inline_review_enabled: false,
      ai_available: false,
      ai_unavailable_reason: null,
    }
  ))

  const clearError = () => {
    error.value = ''
  }

  const setThread = (thread: AssetThread) => {
    const idx = threads.value.findIndex(item => item.id === thread.id)
    if (idx >= 0) {
      threads.value[idx] = thread
    } else {
      threads.value.push(thread)
    }
    threads.value.sort((a, b) => (
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    ))
  }

  const setMarkerCount = (threadId: string, delta: number) => {
    if (!documentData.value) return
    const markers = documentData.value.thread_markers || []
    const marker = markers.find(item => item.thread_id === threadId)
    if (!marker) return
    marker.message_count = Math.max(0, Number(marker.message_count || 0) + delta)
  }

  const isThreadJobActive = (status?: string | null): boolean => (
    status === 'PENDING' || status === 'RUNNING' || status === 'WAITING_HITL'
  )

  const resolveThreadJobKind = (job: AssetAiJob | null | undefined): ThreadJobKind => {
    const raw = String(job?.context_json?.job_kind || '').trim().toUpperCase()
    if (raw === 'RESOLUTION_REWRITE') return 'RESOLUTION_REWRITE'
    if (raw === 'RESOLUTION_PROPOSAL') return 'RESOLUTION_PROPOSAL'
    return 'THREAD_AI_REPLY'
  }

  const stopThreadJobPolling = (threadId: string) => {
    const timer = jobPollTimers.value[threadId]
    if (timer === undefined) return
    window.clearTimeout(timer)
    const next = { ...jobPollTimers.value }
    delete next[threadId]
    jobPollTimers.value = next
  }

  const stopAllThreadJobPolling = () => {
    for (const timer of Object.values(jobPollTimers.value)) {
      window.clearTimeout(timer)
    }
    jobPollTimers.value = {}
  }

  const scheduleThreadJobPolling = (threadId: string) => {
    if (!threadId || jobPollTimers.value[threadId] !== undefined) return

    const tick = async () => {
      try {
        const items = await loadThreadJobs(threadId, true)
        if (!items.length) {
          clearThreadJobs(threadId)
          try {
            await fetchThread(threadId)
          } catch {
            // Ignore transient sync errors.
          }
          stopThreadJobPolling(threadId)
          return
        }

        const activeJob = items[0]
        if (!isThreadJobActive(activeJob?.status)) {
          stopThreadJobPolling(threadId)
          return
        }
      } catch {
        // Retry on transient failures.
      }

      const timer = window.setTimeout(tick, 1800)
      jobPollTimers.value = { ...jobPollTimers.value, [threadId]: timer }
    }

    const timer = window.setTimeout(tick, 1800)
    jobPollTimers.value = { ...jobPollTimers.value, [threadId]: timer }
  }

  const setThreadJob = (job: AssetAiJob | null | undefined) => {
    if (!job?.thread_id) return
    const kind = resolveThreadJobKind(job)
    if (kind === 'RESOLUTION_PROPOSAL' || kind === 'RESOLUTION_REWRITE') {
      proposalJobMap.value = {
        ...proposalJobMap.value,
        [job.thread_id]: job,
      }
    } else {
      assistantJobMap.value = {
        ...assistantJobMap.value,
        [job.thread_id]: job,
      }
    }
    if (isThreadJobActive(job.status)) {
      scheduleThreadJobPolling(job.thread_id)
    } else {
      stopThreadJobPolling(job.thread_id)
    }
  }

  const clearThreadJobs = (threadId: string) => {
    stopThreadJobPolling(threadId)
    if (assistantJobMap.value[threadId]) {
      const nextAssistant = { ...assistantJobMap.value }
      delete nextAssistant[threadId]
      assistantJobMap.value = nextAssistant
    }
    if (proposalJobMap.value[threadId]) {
      const nextProposal = { ...proposalJobMap.value }
      delete nextProposal[threadId]
      proposalJobMap.value = nextProposal
    }
  }

  const clearThreadJobByKind = (threadId: string, kind: ThreadJobKind) => {
    if (kind === 'RESOLUTION_PROPOSAL' || kind === 'RESOLUTION_REWRITE') {
      if (!proposalJobMap.value[threadId]) return
      const next = { ...proposalJobMap.value }
      delete next[threadId]
      proposalJobMap.value = next
      return
    }
    if (!assistantJobMap.value[threadId]) return
    const next = { ...assistantJobMap.value }
    delete next[threadId]
    assistantJobMap.value = next
  }

  const loadThreadJobs = async (threadId: string, activeOnly = true) => {
    if (!wsIdRef.value || !assetIdRef.value || !threadId) return []
    const res = await api.get(
      `/workspaces/${wsIdRef.value}/assets/${assetIdRef.value}/threads/${threadId}/ai-jobs`,
      { params: { active_only: activeOnly } },
    )
    const items = (res.data?.items || []) as AssetAiJob[]
    if (!items.length) {
      if (activeOnly) {
        clearThreadJobs(threadId)
      }
      return []
    }
    if (activeOnly) {
      clearThreadJobs(threadId)
    }
    for (const item of items) {
      setThreadJob(item)
    }
    return items
  }

  const refreshThreadJobs = async (threadIds: string[]) => {
    if (!threadIds.length) return
    await Promise.all(threadIds.map(async (threadId) => {
      try {
        await loadThreadJobs(threadId, true)
      } catch {
        // Keep thread rendering available even if one job query fails.
      }
    }))
  }

  const fetchThread = async (threadId: string) => {
    if (!wsIdRef.value || !assetIdRef.value || !threadId) return
    const params: Record<string, string> = {}
    if (activeVersionId.value) {
      params.context_version_id = activeVersionId.value
    }
    const res = await api.get(
      `/workspaces/${wsIdRef.value}/assets/${assetIdRef.value}/threads/${threadId}`,
      { params },
    )
    const thread = res.data as AssetThread
    setThread(thread)
    return thread
  }

  const loadDocument = async (versionId?: string) => {
    if (!wsIdRef.value || !assetIdRef.value) {
      documentData.value = null
      return null
    }
    loadingDocument.value = true
    clearError()
    try {
      const params: Record<string, string> = {}
      if (versionId) {
        params.version_id = versionId
      }
      const res = await api.get(`/workspaces/${wsIdRef.value}/assets/${assetIdRef.value}/document`, { params })
      documentData.value = res.data as AssetDocumentPayload
      return documentData.value
    } catch (err: any) {
      error.value = err?.response?.data?.detail || t('doc_review.document_load_failed')
      documentData.value = null
      return null
    } finally {
      loadingDocument.value = false
    }
  }

  const loadVersions = async () => {
    if (!wsIdRef.value || !assetIdRef.value) {
      versions.value = []
      return []
    }
    loadingVersions.value = true
    try {
      const res = await api.get(`/workspaces/${wsIdRef.value}/assets/${assetIdRef.value}/versions`)
      versions.value = (res.data?.items || []) as AssetVersion[]
      return versions.value
    } finally {
      loadingVersions.value = false
    }
  }

  const loadThreads = async (versionId?: string) => {
    if (!wsIdRef.value || !assetIdRef.value) {
      threads.value = []
      return []
    }
    loadingThreads.value = true
    try {
      const params: Record<string, string> = {}
      if (versionId) {
        params.context_version_id = versionId
      }
      const res = await api.get(`/workspaces/${wsIdRef.value}/assets/${assetIdRef.value}/threads`, { params })
      threads.value = (res.data?.items || []) as AssetThread[]
      if (selectedThreadId.value && !threads.value.some(item => item.id === selectedThreadId.value)) {
        selectedThreadId.value = ''
      }
      await refreshThreadJobs(threads.value.map(item => item.id))
      return threads.value
    } finally {
      loadingThreads.value = false
    }
  }

  const refresh = async (versionId?: string) => {
    await loadDocument(versionId)
    await Promise.all([
      loadVersions(),
      loadThreads(versionId || activeVersionId.value || undefined),
    ])
  }

  const createThread = async (payload: {
    block_id: string
    body: string
    selected_text?: string
    char_start?: number | null
    char_end?: number | null
    version_id?: string
  }) => {
    if (!wsIdRef.value || !assetIdRef.value) return null
    const res = await api.post(`/workspaces/${wsIdRef.value}/assets/${assetIdRef.value}/threads`, payload)
    const thread = res.data as AssetThread
    setThread(thread)
    selectedThreadId.value = thread.id
    await loadDocument(payload.version_id || activeVersionId.value || undefined)
    return thread
  }

  const sendThreadMessage = async (threadId: string, content: string) => {
    if (!wsIdRef.value || !assetIdRef.value || !threadId) return null
    const res = await api.post(
      `/workspaces/${wsIdRef.value}/assets/${assetIdRef.value}/threads/${threadId}/messages`,
      { content },
    )
    const created = res.data as AssetThreadMessage
    const thread = threads.value.find(item => item.id === threadId)
    if (thread && !thread.messages.some(item => item.id === created.id)) {
      thread.messages.push(created)
      thread.messages.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
      setMarkerCount(threadId, 1)
    }
    return created
  }

  const askAi = async (threadId: string, prompt?: string) => {
    if (!wsIdRef.value || !assetIdRef.value || !threadId) return null
    const res = await api.post(
      `/workspaces/${wsIdRef.value}/assets/${assetIdRef.value}/threads/${threadId}/ai-jobs`,
      { prompt: prompt?.trim() || undefined },
    )
    const job = res.data as AssetAiJob
    setThreadJob(job)
    return job
  }

  const createResolutionProposal = async (
    threadId: string,
    overwriteExistingDraft = false,
    contextVersionId?: string,
  ) => {
    if (!wsIdRef.value || !assetIdRef.value || !threadId) return null
    const res = await api.post(
      `/workspaces/${wsIdRef.value}/assets/${assetIdRef.value}/threads/${threadId}/resolution/proposals`,
      {
        overwrite_existing_draft: overwriteExistingDraft,
        context_version_id: contextVersionId || undefined,
      },
    )
    const job = res.data as AssetAiJob
    setThreadJob(job)
    return job
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
    if (!wsIdRef.value || !assetIdRef.value || !threadId || !proposalId) return null
    const normalized = proposalText.trim()
    const scope = rewriteScope === 'document' ? 'document' : 'anchor'
    const res = await api.post(
      `/workspaces/${wsIdRef.value}/assets/${assetIdRef.value}/threads/${threadId}/resolution/proposals/${proposalId}/rewrite`,
      {
        proposal_text: normalized,
        rewrite_scope: scope,
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
    )
    const job = res.data as AssetAiJob
    setThreadJob(job)
    return job
  }

  const applyResolutionProposal = async (
    threadId: string,
    proposalId: string,
    payload: ResolutionApplyPayload,
    changeNote?: string,
    decision?: ResolutionDecisionPayload | null,
  ) => {
    if (!wsIdRef.value || !assetIdRef.value || !threadId || !proposalId) return null
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
      `/workspaces/${wsIdRef.value}/assets/${assetIdRef.value}/threads/${threadId}/resolution/apply`,
      body,
    )
    const version = res.data as AssetVersion
    await refresh(version.id)
    return version
  }

  const cancelAiJob = async (jobId: string) => {
    if (!wsIdRef.value || !jobId) return null
    const res = await api.post(`/workspaces/${wsIdRef.value}/ai-jobs/${jobId}/cancel`)
    const job = res.data as AssetAiJob
    setThreadJob(job)
    return job
  }

  const updateThreadCloseHint = async (
    threadId: string,
    action: 'mark_no_close_needed' | 'reset_pending',
    contextVersionId?: string,
  ) => {
    if (!wsIdRef.value || !assetIdRef.value || !threadId) return null
    const params: Record<string, string> = {}
    if (contextVersionId) {
      params.context_version_id = contextVersionId
    }
    const res = await api.post(
      `/workspaces/${wsIdRef.value}/assets/${assetIdRef.value}/threads/${threadId}/close-hint`,
      { action },
      { params },
    )
    const thread = res.data as AssetThread
    setThread(thread)
    return thread
  }

  const updateThreadState = async (threadId: string, status: 'open' | 'resolved' | 'closed') => {
    if (!wsIdRef.value || !assetIdRef.value || !threadId) return null
    const res = await api.post(
      `/workspaces/${wsIdRef.value}/assets/${assetIdRef.value}/threads/${threadId}/state`,
      { status },
    )
    const thread = res.data as AssetThread
    setThread(thread)
    await loadDocument(activeVersionId.value || undefined)
    return thread
  }

  const clearWsTimer = () => {
    if (reconnectTimer.value !== null) {
      window.clearTimeout(reconnectTimer.value)
      reconnectTimer.value = null
    }
  }

  const buildWsUrl = (assetId: string, userId: string): string => {
    return buildBackendWsUrl(`/ws/assets/${assetId}/discussion`, {
      userId: userId || 'anonymous',
    })
  }

  const scheduleReconnect = () => {
    if (wsManualClose.value || reconnectTimer.value !== null || !assetIdRef.value) return
    reconnectTimer.value = window.setTimeout(() => {
      reconnectTimer.value = null
      connectWs()
    }, 1200)
  }

  const handleWsEvent = async (eventData: any) => {
    const eventType = String(eventData?.type || '')
    if (eventType === 'presence') {
      onlineUsers.value = Array.isArray(eventData.online_users) ? eventData.online_users : []
      return
    }
    if (eventType === 'thread_created' && eventData.thread) {
      setThread(eventData.thread as AssetThread)
      await loadDocument(activeVersionId.value || undefined)
      return
    }
    if (eventType === 'thread_updated' && eventData.thread) {
      setThread(eventData.thread as AssetThread)
      await loadDocument(activeVersionId.value || undefined)
      return
    }
    if (eventType === 'message_created' && eventData.thread_id && eventData.message) {
      const threadId = String(eventData.thread_id)
      const message = eventData.message as AssetThreadMessage
      const thread = threads.value.find(item => item.id === threadId)
      if (thread) {
        if (!thread.messages.some(item => item.id === message.id)) {
          thread.messages.push(message)
          thread.messages.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
          setMarkerCount(threadId, 1)
        }
      } else {
        try {
          await fetchThread(threadId)
        } catch {
          // Ignore transient fetch failure for delayed sync.
        }
      }
      if (message.role === 'ai') {
        clearThreadJobByKind(threadId, 'THREAD_AI_REPLY')
      }
      return
    }
    if (eventType === 'proposal_created' && eventData.thread_id && eventData.proposal) {
      const threadId = String(eventData.thread_id)
      const thread = threads.value.find(item => item.id === threadId)
      const proposal = eventData.proposal as AssetResolutionProposal
      if (thread) {
        const idx = thread.proposals.findIndex(item => item.id === proposal.id)
        if (idx >= 0) {
          thread.proposals[idx] = proposal
        } else {
          thread.proposals.unshift(proposal)
        }
      }
      clearThreadJobByKind(threadId, 'RESOLUTION_PROPOSAL')
      clearThreadJobByKind(threadId, 'RESOLUTION_REWRITE')
      return
    }
    if (eventType === 'version_applied' && eventData.version?.id) {
      await refresh(String(eventData.version.id))
      return
    }
    if (
      (eventType === 'ai_job_update' || eventType === 'ai_job_done' || eventType === 'ai_job_failed')
      && eventData.job
    ) {
      const job = eventData.job as AssetAiJob
      const kind = resolveThreadJobKind(job)
      setThreadJob(job)
      // Proposal/rewrite jobs may finish before `proposal_created` arrives or when that
      // event is transiently dropped; force a thread refresh as a reliable fallback.
      if (
        (eventType === 'ai_job_done' || eventType === 'ai_job_failed')
        && job.thread_id
        && (kind === 'RESOLUTION_PROPOSAL' || kind === 'RESOLUTION_REWRITE')
      ) {
        try {
          await fetchThread(String(job.thread_id))
        } catch {
          // Ignore transient pull failures; polling/reconnect will retry.
        }
      }
    }
  }

  const connectWs = () => {
    clearWsTimer()
    const assetId = assetIdRef.value
    if (!assetId) {
      disconnectWs()
      return
    }
    wsManualClose.value = false
    if (ws.value) {
      ws.value.onopen = null
      ws.value.onmessage = null
      ws.value.onerror = null
      ws.value.onclose = null
      ws.value.close()
      ws.value = null
    }

    const socket = new WebSocket(buildWsUrl(assetId, userIdRef.value))
    ws.value = socket
    socket.onopen = () => {
      wsConnected.value = true
    }
    socket.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)
        void handleWsEvent(data)
      } catch {
        // Ignore malformed events
      }
    }
    socket.onerror = () => {
      wsConnected.value = false
    }
    socket.onclose = () => {
      wsConnected.value = false
      if (assetIdRef.value === assetId) {
        scheduleReconnect()
      }
    }
  }

  const disconnectWs = () => {
    wsManualClose.value = true
    clearWsTimer()
    wsConnected.value = false
    if (ws.value) {
      ws.value.onopen = null
      ws.value.onmessage = null
      ws.value.onerror = null
      ws.value.onclose = null
      ws.value.close()
      ws.value = null
    }
  }

  watch(
    () => assetIdRef.value,
    async (assetId) => {
      selectedThreadId.value = ''
      onlineUsers.value = []
      stopAllThreadJobPolling()
      assistantJobMap.value = {}
      proposalJobMap.value = {}
      if (!assetId) {
        documentData.value = null
        versions.value = []
        threads.value = []
        disconnectWs()
        return
      }
      await refresh()
      connectWs()
    },
    { immediate: true },
  )

  onBeforeUnmount(() => {
    stopAllThreadJobPolling()
    disconnectWs()
  })

  return {
    documentData,
    versions,
    threads,
    selectedThreadId,
    selectedThread,
    markersByBlock,
    activeVersionId,
    capabilities,
    loadingDocument,
    loadingVersions,
    loadingThreads,
    onlineUsers,
    wsConnected,
    assistantJobMap,
    proposalJobMap,
    error,
    clearError,
    loadDocument,
    loadVersions,
    loadThreads,
    loadThreadJobs,
    refresh,
    createThread,
    sendThreadMessage,
    askAi,
    createResolutionProposal,
    rewriteResolutionProposal,
    applyResolutionProposal,
    cancelAiJob,
    updateThreadCloseHint,
    updateThreadState,
    fetchThread,
  }
}
