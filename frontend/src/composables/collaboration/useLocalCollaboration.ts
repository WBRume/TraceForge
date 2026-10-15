import { computed, effectScope, onScopeDispose, reactive, ref, shallowRef, watch, type EffectScope } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { getSddDesktop } from '@/utils/runtime'
import { formatApiError } from '@/utils/error'
import { onRepoPreferencesChanged, readRepoPreferences, saveRepoPreferences } from '@/composables/localRepoPreferences'
import { remoteUrlsMatch } from '@/composables/local-agent/localAgentUtils'
import { chooseGitRemote, getLocalGitRemotes } from '@/composables/local-agent/localGitRemotes'
import { collaborationApi, base64Bytes, bytesBase64 } from '@/services/collaborationApi'
import type { CollaborationBackup, CollaborationCapture, CollaborationConflict, CollaborationManifest, CollaborationMappingCheck, CollaborationState, LocalCollaborationStatus } from '@/types/collaboration'
import { expandManifest, expandStatus, manifestDelta } from '../../../shared/collaboration-delta'

const INSTANCE_KEY = 'traceforge.collaboration.instance'
const INSTANCE_ID = sessionStorage.getItem(INSTANCE_KEY) || crypto.randomUUID()
sessionStorage.setItem(INSTANCE_KEY, INSTANCE_ID)
function clientId() {
  const key = 'traceforge.collaboration.client'
  let id = localStorage.getItem(key)
  if (!id) { id = crypto.randomUUID(); localStorage.setItem(key, id) }
  return id
}
function createController(options: { workspaceId: () => string; task: () => Record<string, any> | null }, t: ReturnType<typeof useI18n>['t'], auth: ReturnType<typeof useAuthStore>) {
  const desktop = getSddDesktop()
  const state = shallowRef<CollaborationState | null>(null), local = shallowRef<LocalCollaborationStatus | null>(null)
  const input = shallowRef<CollaborationManifest | null>(null), cloud = shallowRef<CollaborationManifest | null>(null)
  const reviewBaselines = shallowRef(new Map<string, CollaborationManifest>())
  const baselineError = shallowRef('')
  const repositoryKey = (repositories: CollaborationManifest['repositories'] | CollaborationState['repositories']) => JSON.stringify(repositories.map(repo => [repo.task_repository_id, repo.base_commit_sha]).sort())
  // Publish a baseline with its matching cloud version, including during an update.
  const reviewBaseline = computed(() => reviewBaselines.value.get(repositoryKey(cloud.value?.repositories || state.value?.repositories || [])) || null)
  const reviewRunning = shallowRef(false), reviewLoading = shallowRef(false), reviewError = shallowRef('')
  let reviewRequested = false
  const previewConflicts = shallowRef<CollaborationConflict[]>([])
  const error = shallowRef(''), busy = shallowRef(false), loading = shallowRef(true)
  const preparationRequired = shallowRef(false)
  const participating = shallowRef(false), leaving = shallowRef(false), receivedOnce = shallowRef(false)
  const deliveryRetryRequired = shallowRef(false)
  const mappingChecks = shallowRef<CollaborationMappingCheck[]>([]), operationStage = shallowRef(''), operationSeconds = shallowRef(0)
  let stageStarted = 0
  const setStage = (stage: string) => { operationStage.value = stage; operationSeconds.value = 0; stageStarted = Date.now() }
  const stageClock = setInterval(() => { if (busy.value && operationStage.value) operationSeconds.value = Math.floor((Date.now() - stageStarted) / 1000) }, 1000)
  const directories = shallowRef<{ mapped_repositories?: number; task_root: string; repositories: Array<{ task_repository_id: string; local_worktree_path: string }> } | null>(null)
  const activity = ref({ direction: '', done: 0, total: 0, bytes: 0, totalBytes: 0 })
  const progressive = shallowRef(localStorage.getItem(`traceforge.collaboration.progressive:${options.task()?.id}`) === 'true')
  const view = ref({ page: 'files', tab: 'all', pair: 'auto', selected: '', selectedConflicts: [] as string[], conflictSetId: '' })
  const mappings = ref<Record<string, { local_path: string; configured_git_url: string }>>({})
  const available = Boolean(desktop?.collaboration)
  const identity = reactive({ client_id: clientId(), instance_id: INSTANCE_ID })
  const standaloneKey = `traceforge.collaboration.handoff:${options.workspaceId()}:${options.task()?.id}`
  let nativeIdentityReady = false, mappingsDirty = true, bindingMetadataLoaded = false
  const supported = computed(() => options.task()?.execution_location === 'SERVER')
  const enabled = computed(() => Boolean(state.value?.enabled))
  const driver = computed(() => state.value?.driver_user_id === auth.user?.id && state.value?.client_id === identity.client_id && state.value?.instance_id === identity.instance_id)
  const remoteSender = computed(() => !desktop && state.value?.driver_user_id === auth.user?.id && state.value?.driver_connected === true)
  const canReconnect = computed(() => available && enabled.value && state.value?.driver_user_id === auth.user?.id && (driver.value || state.value?.driver_connected === false))
  const phase = computed(() => busy.value && !enabled.value ? 'ENABLING' : state.value?.sync_phase || 'DISABLED')
  const label = computed(() => (preparationRequired.value ? t('collaboration.preparationRequired') : deliveryRetryRequired.value && !busy.value ? t('collaboration.deliveryRetryRequired') : t(`collaboration.phases.${phase.value}`, phase.value)) + (phase.value === 'READY' && local.value?.local_changes?.length ? ` · ${t('collaboration.localCount', { count: local.value.local_changes.length })}` : ''))
  const blocked = computed(() => supported.value && (busy.value || leaving.value || (participating.value || remoteSender.value) && (loading.value || enabled.value && (preparationRequired.value || Boolean(error.value) || local.value?.state === 'RECOVERY_REQUIRED' || (!driver.value && !remoteSender.value) || state.value?.driver_connected === false || !['READY', 'DISABLED'].includes(phase.value)))))
  const conflicts = computed(() => participating.value && ['RUNNING', 'WAITING_HITL'].includes(phase.value) ? previewConflicts.value : local.value?.conflicts || [])
  let generation = 0, refreshing = false, disposed = false
  let refreshQueued = false, localRefreshQueued = false, eventVersion = 0, observedVersion = 0
  let lastLease = 0, leaseRetryAt = 0, lastTarget = '', lastProgress = '', lastHandoff = ''
  let failedPreparation: { submission_id: string; operation_id: string; error_message: string } | null = null
  const remote = () => collaborationApi(options.workspaceId(), String(options.task()?.id || ''))
  let transportStatus: LocalCollaborationStatus | null = null
  async function snapshot(id: string) {
    const base = local.value?.baseline?.snapshot_id ? local.value.baseline : cloud.value || input.value
    const wire = await remote().snapshot(id, base?.snapshot_id)
    return expandManifest(base, wire)
  }
  const native = async <T>(kind: string, payload: Record<string, unknown>): Promise<T> => {
    if (!desktop?.collaboration) throw new Error(t('collaboration.desktopRequired'))
    const target = payload.target as CollaborationManifest | undefined
    const result = await desktop.collaboration.execute({ kind, payload: { ...payload,
      ...(target && transportStatus?.transport?.token && local.value?.baseline?.snapshot_id ? { target: manifestDelta(local.value.baseline, target) } : {}),
      delta_transport: true, status_token: transportStatus?.transport?.token,
      manifest_delta: state.value?.capabilities?.manifest_delta === 1,
    } }) as any
    const incoming = kind === 'capture' ? result.status : result
    if (incoming?.state && incoming.task_id) {
      transportStatus = expandStatus(transportStatus, incoming)
      return (kind === 'capture' ? { ...result, status: transportStatus } : transportStatus) as T
    }
    return result as T
  }
  const fence = () => ({ ...identity, lease_epoch: state.value!.lease_epoch, expected_state_version: state.value!.state_version, expected_workspace_revision: state.value!.workspace_revision, session_generation: state.value!.session_generation, session_revision: state.value!.session_revision })
  const check = (token: number) => { if (generation !== token || disposed) throw new Error('COLLABORATION_CONTEXT_CHANGED') }
  const renew = async () => {
    if (participating.value && !leaving.value && enabled.value && driver.value && state.value?.driver_connected !== false && Date.now() >= leaseRetryAt && Date.now() - lastLease > 20000) {
      try {
        await remote().post('lease', { ...identity, lease_epoch: state.value!.lease_epoch })
        lastLease = Date.now(); leaseRetryAt = 0
      } catch (reason) {
        const response = (reason as { response?: { status?: number; data?: { detail?: { code?: string } } } })?.response
        if (response?.status !== 409 || response.data?.detail?.code !== 'TASK_BUSY') throw reason
        // A held task row is not a renewed lease. Keep the last success and retry on the next heartbeat.
        leaseRetryAt = Date.now() + 10000
      }
    }
  }
  const heartbeat = setInterval(() => { void renew().catch(reason => { error.value = formatApiError(reason, t('collaboration.failed')) }) }, 10000)

  function missingBinding(reason: unknown, taskId: string) {
    const message = String(reason)
    const missing = /ENOENT\b[^\r\n]*[\\/]collaboration[\\/]bindings[\\/]([^\\/'"\r\n]+)\.json(?:['"]|$)/i.exec(message)
    return missing?.[1] === taskId || /\bCOLLABORATION_BINDING_MISSING\b/.test(message)
  }
  async function readBinding() {
    const taskId = String(options.task()?.id)
    try { return await native<LocalCollaborationStatus | null>('binding', { task_id: taskId, optional: true }) }
    catch (reason) { if (missingBinding(reason, taskId)) return null; throw reason }
  }

  async function loadMappings() {
    const token = generation, wsId = options.workspaceId()
    mappingsDirty = false
    const preferences = readRepoPreferences(wsId, String(auth.user?.id || ''))
    const next: typeof mappings.value = {}
    for (const repo of state.value?.repositories || []) {
      const stored = await desktop?.config.getRepoMapping({ workspaceId: wsId, remoteUrl: repo.repo_url })
      check(token)
      const preference = preferences.find(row => Boolean(repo.repository_id && row.repository_id === repo.repository_id) || remoteUrlsMatch(row.configured_git_url, repo.repo_url))
      if (stored?.localPath || preference?.local_path) next[repo.task_repository_id] = { local_path: stored?.localPath || preference!.local_path, configured_git_url: stored?.gitRemoteUrl || preference?.configured_git_url || repo.repo_url }
    }
    mappings.value = next
    if (available && (!nativeIdentityReady || !directories.value)) {
      const described = await native<NonNullable<typeof directories.value> & { client_id?: string; instance_id?: string }>('describe', { task_id: String(options.task()?.id), directory_mode: 'MAPPED', repositories: (state.value?.repositories || []).map(repo => ({ ...repo, ...next[repo.task_repository_id] })) })
      check(token); directories.value = described
      if (described.client_id && described.instance_id) Object.assign(identity, { client_id: described.client_id, instance_id: described.instance_id })
      nativeIdentityReady = true
    }
    if (available && !bindingMetadataLoaded) {
      local.value = await readBinding()
      check(token); bindingMetadataLoaded = true
    }
  }

  function bindingPrepared(status: LocalCollaborationStatus | null) {
    const expected = state.value?.repositories.map(repo => repo.task_repository_id).sort() || []
    return Boolean(status?.directory_mode === 'MAPPED' && status.baseline && expected.length && (!status.binding_id || status.binding_id === state.value?.binding_id)
      && JSON.stringify(status.repositories?.map(repo => repo.task_repository_id).sort()) === JSON.stringify(expected)
      && JSON.stringify(status.baseline.repositories.map(repo => repo.task_repository_id).sort()) === JSON.stringify(expected))
  }

  function mappedRepositories() {
    return state.value!.repositories.map(repo => ({ ...repo, ...mappings.value[repo.task_repository_id] }))
  }
  async function inspectMappings(token: number) {
    if (directories.value?.mapped_repositories !== 1) throw new Error(t('collaboration.restartDesktop'))
    const repositories = mappedRepositories()
    if (repositories.some(repo => !repo.local_path)) throw new Error(t('collaboration.mappingRequired'))
    setStage('checkingMappings')
    const result = await native<{ ready: boolean; checks: CollaborationMappingCheck[] }>('inspect_mappings', { task_id: String(options.task()?.id), repositories })
    check(token); mappingChecks.value = result.checks
    if (!result.ready) throw new Error(t('collaboration.mappingCheckFailed'))
    return repositories
  }

  async function checkMappings() {
    if (busy.value || !available || participating.value && !preparationRequired.value) return
    const token = generation
    busy.value = true; error.value = ''
    try { await loadMappings(); check(token); if (!(local.value?.baseline && (!local.value.released || local.value.suspended))) await inspectMappings(token) }
    catch (reason) { if (token === generation) error.value = formatApiError(reason, t('collaboration.failed')) }
    finally { if (token === generation) busy.value = false }
  }

  async function selectMapping(repositoryId: string) {
    if (!desktop || busy.value || participating.value && !preparationRequired.value) return
    const repo = state.value?.repositories.find(row => row.task_repository_id === repositoryId)
    if (!repo) return
    const token = generation
    busy.value = true; error.value = ''
    try {
      const selected = await desktop.git.selectDirectory(); check(token)
      if (selected.canceled || !selected.path) return
      const result = await desktop.git.validateGitRepo(selected.path); check(token)
      if (!result.ok) throw new Error(t('collaboration.ui.invalidRepo'))
      const remotes = await getLocalGitRemotes(selected.path); check(token)
      const remote = chooseGitRemote(remotes, { preferredUrl: repo.repo_url })?.fetchUrl || repo.repo_url
      await desktop.config.setRepoMapping({ workspaceId: options.workspaceId(), remoteUrl: repo.repo_url, localPath: selected.path, gitRemoteUrl: remote }); check(token)
      const preferences = readRepoPreferences(options.workspaceId(), String(auth.user?.id || ''))
        .filter(row => !(repo.repository_id && row.repository_id === repo.repository_id) && !remoteUrlsMatch(row.configured_git_url, repo.repo_url))
      saveRepoPreferences(options.workspaceId(), String(auth.user?.id || ''), [...preferences, { repository_id: repo.repository_id, configured_git_url: remote, local_path: selected.path }])
      mappingChecks.value = []; await loadMappings(); check(token)
      if (state.value?.repositories.every(row => mappings.value[row.task_repository_id])) await inspectMappings(token)
    } catch (reason) { if (token === generation) error.value = formatApiError(reason, t('collaboration.failed')) }
    finally { if (token === generation) busy.value = false }
  }

  async function prepareCurrentBinding(token: number, previousBindingId = local.value?.binding_id) {
    if (bindingPrepared(local.value) && !local.value?.released) { preparationRequired.value = false; return }
    preparationRequired.value = true
    await loadMappings(); check(token)
    const accepted = state.value!
    const repositories = local.value?.suspended && local.value?.baseline ? mappedRepositories() : await inspectMappings(token)
    setStage(local.value?.suspended && local.value?.baseline ? 'resumingBaseline' : 'capturingBaseline')
    const prepared = await native<LocalCollaborationStatus>('prepare', { ...accepted, task_id: String(options.task()?.id),
      directory_mode: 'MAPPED', previous_binding_id: previousBindingId, repositories })
    check(token); local.value = prepared
    if (!bindingPrepared(prepared)) throw new Error(prepared.errors?.join('\n') || t('collaboration.preparationRequired'))
    preparationRequired.value = false
  }

  async function cacheManifest(manifest: CollaborationManifest, token: number) {
    // A viewed manifest is only metadata. Download relative to the native baseline,
    // even when the server wire delta was empty relative to an already viewed input.
    manifest = local.value?.baseline ? manifestDelta(local.value.baseline, manifest) : manifest
    const api = remote()
    const hashes = [...new Set(manifest.repositories.flatMap(repo => repo.files.map(file => file.sha256)))]
    const sizes = new Map(manifest.repositories.flatMap(repo => repo.files.map(file => [file.sha256, file.size] as const)))
    activity.value = { direction: 'download', done: 0, total: 0, bytes: 0, totalBytes: 0 }
    for (let start = 0; start < hashes.length; start += 2000) {
      const cached = await native<{ missing: string[] }>('missing_objects', { sha256: hashes.slice(start, start + 2000) })
      activity.value.total += cached.missing.length; activity.value.totalBytes += cached.missing.reduce((sum, hash) => sum + (sizes.get(hash) || 0), 0)
      for (let index = 0; index < cached.missing.length; index += 4) {
        const objects = await Promise.all(cached.missing.slice(index, index + 4).map(async hash => {
          check(token)
          const content = bytesBase64(await api.object(hash)); check(token)
          activity.value.done++; activity.value.bytes += sizes.get(hash) || 0
          return { sha256: hash, content }
        }))
        check(token); await native('cache_objects', { objects })
      }
    }
  }

  async function receipt(snapshotId: string, status: LocalCollaborationStatus, token: number) {
    check(token)
    const payload = {
      ...fence(), operation_id: crypto.randomUUID(), snapshot_id: snapshotId, local_scan_id: crypto.randomUUID(),
      repository_results: (state.value?.repositories || []).map(repo => ({ task_repository_id: repo.task_repository_id, status: status.state === 'RECOVERY_REQUIRED' || status.errors?.length ? 'FAILED' : status.conflicts?.some(row => row.task_repository_id === repo.task_repository_id) ? 'CONFLICTS' : status.local_changes?.some(row => row.task_repository_id === repo.task_repository_id) ? 'LOCAL_CHANGES' : 'ALIGNED' })),
      conflicts: status.conflicts || [], pending_local_changes: status.local_changes || [],
    }
    const result = await remote().post('receipt', payload)
    check(token); state.value = result
  }

  async function uploadManifest(manifest: CollaborationManifest, token: number, objects = new Map<string, { sha256: string; content: string }>()) {
    const api = remote()
    const uploadIdentity = { ...identity, lease_epoch: state.value!.lease_epoch }, bindingId = state.value!.binding_id
    const checkUpload = () => {
      check(token)
      if (state.value?.binding_id !== bindingId || state.value?.lease_epoch !== uploadIdentity.lease_epoch
        || identity.client_id !== uploadIdentity.client_id || identity.instance_id !== uploadIdentity.instance_id) throw new Error('COLLABORATION_CONTEXT_CHANGED')
    }
    const hashes = [...new Set(manifest.repositories.flatMap(repo => repo.files.map(file => file.sha256)))]
    if (!hashes.length) return
    const sizes = new Map(manifest.repositories.flatMap(repo => repo.files.map(file => [file.sha256, file.size] as const)))
    activity.value = { direction: 'upload', done: 0, total: 0, bytes: 0, totalBytes: 0 }
    for (let start = 0; start < hashes.length; start += 1000) {
      checkUpload()
      const batch = hashes.slice(start, start + 1000)
      const missing = await api.post<{ missing: string[] }>('objects/missing', { hashes: batch })
      checkUpload()
      activity.value.total += missing.missing.length; activity.value.totalBytes += missing.missing.reduce((sum, hash) => sum + (sizes.get(hash) || 0), 0)
      for (let index = 0; index < missing.missing.length; index += 4) {
        await Promise.all(missing.missing.slice(index, index + 4).map(async hash => {
          checkUpload()
          const object = objects.get(hash) || await native<{ sha256: string; content: string }>('read_object', { sha256: hash })
          checkUpload(); await api.upload(hash, base64Bytes(object.content), uploadIdentity)
          checkUpload()
          activity.value.done++; activity.value.bytes += sizes.get(hash) || 0
        }))
      }
    }
  }

  async function reconcile(manifest: CollaborationManifest, token: number, preview = false) {
    const ownedBusy = !busy.value
    busy.value = true
    try {
      // Keep the known cloud file list visible even if receiving its bytes fails.
      // This is preview metadata, never evidence of a received local baseline.
      check(token); cloud.value = manifest
      setStage('downloadingChanges')
      await cacheManifest(manifest, token)
      check(token)
      if (preview && progressive.value) {
        const current = await remote().state(); check(token)
        if (current.progress_snapshot_id !== manifest.snapshot_id || !['RUNNING', 'WAITING_HITL'].includes(current.sync_phase)) return
      }
      setStage('applyingChanges')
      const result = await native<LocalCollaborationStatus>('reconcile', { task_id: manifest.task_id, operation_id: `${preview ? 'preview' : 'delivery'}-${manifest.snapshot_id}`, target: manifest, preview, progressive: preview && progressive.value })
      check(token)
      local.value = result; cloud.value = manifest
      if (preview) previewConflicts.value = result.preview_conflicts || []
      if (!preview) { await receipt(manifest.snapshot_id, result, token); lastTarget = manifest.snapshot_id }
      deliveryRetryRequired.value = false; error.value = ''; reviewError.value = ''
    } catch (reason) {
      if (token === generation) deliveryRetryRequired.value = true
      throw reason
    } finally { if (ownedBusy && token === generation) busy.value = false }
  }

  async function prepareInput(token: number) {
    const preparation = state.value?.pending_submission_id && state.value.pending_submission_id !== state.value.input_submission_id ? { submission_id: state.value.pending_submission_id, operation_id: `handoff:${state.value.pending_submission_id}` } : null
    if (!preparation || lastHandoff === preparation.operation_id) return
    const api = remote(), taskId = String(options.task()?.id)
    busy.value = true
    try {
      const capture = await native<CollaborationCapture>('capture', { task_id: taskId, operation_id: preparation.operation_id, include_objects: false, session_generation: state.value!.session_generation, session_revision: state.value!.session_revision })
      check(token); local.value = capture.status
      await uploadManifest(capture.manifest, token, new Map((capture.objects || []).map(object => [object.sha256, object])))
      check(token)
      const next = await api.post('handoff', { ...fence(), ...preparation, manifest: capture.manifest, input_cut_seq: capture.input_cut_seq ?? 0 })
      check(token); state.value = next; lastHandoff = preparation.operation_id
    } finally { if (token === generation) busy.value = false }
  }

  async function fetchReview() {
    if (!reviewRequested || participating.value || receivedOnce.value) return
    const token = generation
    reviewLoading.value = true; reviewError.value = ''
    try {
      const result = await remote().review(); check(token)
      if (!participating.value && !receivedOnce.value) {
        input.value = result.input; cloud.value = result.cloud; reviewRunning.value = result.running
      }
    } catch (reason) { if (token === generation && !participating.value && !receivedOnce.value) reviewError.value = formatApiError(reason, t('collaboration.failed')) }
    finally { if (token === generation) reviewLoading.value = false }
  }
  async function loadReviewBaseline() {
    const key = repositoryKey(state.value?.repositories || [])
    if (!reviewRequested || !state.value?.repositories.length || reviewBaselines.value.has(key)) return
    const token = generation
    try {
      const value = await remote().reviewBaseline(); check(token)
      reviewBaselines.value = new Map(reviewBaselines.value).set(repositoryKey(value.repositories), value); baselineError.value = ''
    } catch (reason) { if (token === generation) baselineError.value = formatApiError(reason, t('collaboration.failed')) }
  }
  async function loadReview() { reviewRequested = true; await refresh() }
  function refreshResults() { if (reviewRequested) void refresh() }

  async function reportPreparationFailure(token: number) {
    const failure = failedPreparation
    if (!failure) return
    // A lost handoff response may already have advanced this input. Never stop
    // an accepted input, a running Agent, or a newer message on a late failure.
    if (state.value?.pending_submission_id !== failure.submission_id || state.value.input_submission_id === failure.submission_id) {
      failedPreparation = null
      return
    }
    const result = await remote().post('fail-preparation', { ...fence(), ...failure })
    check(token); state.value = result; failedPreparation = null
  }

  async function refreshOnce() {
    const token = generation
    let preparingId: string | null | undefined
    try {
      const next = await remote().state(); check(token)
      state.value = next; observedVersion = next.state_version
      await loadReviewBaseline(); check(token)
      if (participating.value && driver.value && next.sync_phase === 'PREPARING' && next.input_mode !== 'CLOUD' && next.pending_submission_id !== next.input_submission_id) preparingId = next.pending_submission_id
      // Retry only the failure report after reconnect; do not capture/upload the
      // same failed input again when the acknowledgement was lost.
      if (failedPreparation && participating.value && driver.value) {
        const stillPending = next.pending_submission_id === failedPreparation.submission_id && next.input_submission_id !== failedPreparation.submission_id
        await reportPreparationFailure(token)
        if (stillPending) return
      }
      if (mappingsDirty || (available && !nativeIdentityReady) || preparationRequired.value) await loadMappings()
      check(token); loading.value = false
      if (!next.enabled) { preparationRequired.value = false; deliveryRetryRequired.value = false; await fetchReview(); return }
      if (!available || !driver.value || !participating.value || leaving.value) {
        // Keep a one-time receipt and its comparison pinned to the version actually downloaded.
        if (receivedOnce.value && !participating.value) return
        if (reviewRequested) { await fetchReview(); return }
        const target = ['RUNNING', 'WAITING_HITL'].includes(next.sync_phase) ? next.progress_snapshot_id || next.snapshot_id : next.snapshot_id
        if (target && cloud.value?.snapshot_id !== target) { const manifest = await snapshot(target); check(token); cloud.value = manifest }
        if (next.input_snapshot_id && input.value?.snapshot_id !== next.input_snapshot_id) { const manifest = await snapshot(next.input_snapshot_id); check(token); input.value = manifest }
        return
      }
      if (next.driver_connected === false) return
      await renew(); check(token)
      // Preparation failures require an explicit retry; events must not hide the failure.
      if (preparationRequired.value || deliveryRetryRequired.value) {
        if (preparingId) throw new Error(error.value || t('collaboration.preparationRequired'))
        return
      }
      if (!local.value) await loadMappings()
      const capturesLocal = next.sync_phase === 'PREPARING'
        || (next.snapshot_id !== lastTarget && ['DELIVERY_PENDING', 'CONFLICT_PENDING'].includes(next.sync_phase))
        || (['RUNNING', 'WAITING_HITL'].includes(next.sync_phase) && next.progress_snapshot_id && next.progress_snapshot_id !== lastProgress)
      if (!bindingPrepared(local.value) || !capturesLocal) try {
        const scanned = await native<LocalCollaborationStatus>('status', { task_id: String(options.task()?.id), background: true }); check(token); local.value = scanned
      } catch (reason) {
        if (!bindingPrepared(local.value)) {
          preparationRequired.value = true
          // Older desktop hosts return the filesystem error instead of a domain code.
          if (/COLLABORATION_BINDING_MISSING|ENOENT[^\n]*[\\/]collaboration[\\/]bindings[\\/]/i.test(String(reason))) throw new Error(t('collaboration.preparationRequired'))
        }
        throw reason
      }
      if (!bindingPrepared(local.value)) { preparationRequired.value = true; throw new Error(t('collaboration.preparationRequired')) }
      if (next.input_snapshot_id && input.value?.snapshot_id !== next.input_snapshot_id) {
        const accepted = await snapshot(next.input_snapshot_id); check(token)
        if (next.input_mode !== 'CLOUD' && accepted.source === 'HUMAN_HANDOFF' && (!local.value?.baseline || local.value.baseline.workspace_revision < accepted.workspace_revision)) {
          const operationId = next.input_submission_id ? `handoff:${next.input_submission_id}` : localStorage.getItem(standaloneKey)
          if (!operationId) throw new Error('COLLABORATION_INPUT_RECEIPT_REQUIRED')
          const advanced = await native<LocalCollaborationStatus>('accept_input', { task_id: accepted.task_id, operation_id: operationId, target: accepted }); check(token); local.value = advanced
          if (!next.input_submission_id) localStorage.removeItem(standaloneKey)
        }
        input.value = accepted
      }
      if (next.sync_phase === 'PREPARING') await prepareInput(token)
      else if (next.snapshot_id && next.snapshot_id !== lastTarget && ['DELIVERY_PENDING', 'CONFLICT_PENDING'].includes(next.sync_phase)) {
        await reconcile(await snapshot(next.snapshot_id), token)
      } else if (next.sync_phase === 'READY' && next.snapshot_id && !cloud.value) {
        const final = await snapshot(next.snapshot_id); check(token); cloud.value = final; lastTarget = next.snapshot_id
      } else if (['RUNNING', 'WAITING_HITL'].includes(next.sync_phase) && next.progress_snapshot_id && next.progress_snapshot_id !== lastProgress) {
        const candidate = await snapshot(next.progress_snapshot_id); check(token)
        await reconcile(candidate, token, true)
        lastProgress = next.progress_snapshot_id
      }
      error.value = ''
    } catch (reason) {
      if (token === generation) {
        error.value = formatApiError(reason, t('collaboration.failed')); loading.value = false
        if (preparingId && !failedPreparation) {
          failedPreparation = { submission_id: preparingId, operation_id: `preparation-failed:${preparingId}`, error_message: error.value.slice(0, 1000) }
          try { await reportPreparationFailure(token) } catch { /* Retain the report until a socket/state refresh can confirm it. */ }
        }
      }
    }
  }

  async function refresh() {
    if (!supported.value || !options.task()?.id || disposed || leaving.value) return
    refreshQueued = true
    await drainUpdates()
  }
  async function drainUpdates() {
    if (refreshing || busy.value || disposed || leaving.value) return
    refreshing = true
    try {
      do {
        const remoteRequested = refreshQueued || eventVersion > observedVersion
        const localRequested = localRefreshQueued
        refreshQueued = false; eventVersion = 0; localRefreshQueued = false
        if (remoteRequested) await refreshOnce()
        else if (localRequested && participating.value && !preparationRequired.value && !deliveryRetryRequired.value) await refreshComparison()
      } while ((refreshQueued || localRefreshQueued || eventVersion > observedVersion) && !busy.value && !disposed && !leaving.value)
    } finally { refreshing = false }
  }
  watch(busy, value => { if (!value) { operationStage.value = ''; if (!disposed && !leaving.value && (refreshQueued || localRefreshQueued || eventVersion)) void drainUpdates() } })

  async function enable() {
    if (busy.value || !available || !state.value) return
    if (state.value.enabled) { if (!participating.value) await claimDriver(); else await recover(); return }
    busy.value = true; error.value = ''
    const token = generation, taskId = String(options.task()?.id)
    try {
      await loadMappings(); check(token)
      if (state.value.repositories.some(repo => !mappings.value[repo.task_repository_id])) throw new Error(t('collaboration.mappingRequired'))
      local.value = await readBinding()
      check(token)
      if (!local.value?.suspended || !local.value.baseline) await inspectMappings(token)
      setStage('enablingCloud')
      const operationKey = `traceforge.collaboration.enable:${options.workspaceId()}:${taskId}`
      const operationId = localStorage.getItem(operationKey) || crypto.randomUUID()
      localStorage.setItem(operationKey, operationId)
      const previousBindingId = local.value?.binding_id
      check(token)
      const accepted = await remote().post('enable', { ...identity, operation_id: operationId }); check(token); state.value = accepted
      participating.value = true; receivedOnce.value = false
      preparationRequired.value = true
      await prepareCurrentBinding(token, previousBindingId)
      if (accepted.snapshot_id) await reconcile(await snapshot(accepted.snapshot_id), token)
      localStorage.removeItem(operationKey)
    } catch (reason) { if (token === generation) error.value = formatApiError(reason, t('collaboration.failed')) }
    finally { if (token === generation) busy.value = false }
  }

  async function restore(selected: CollaborationConflict[], conflictSetId: string, decision: 'accept' | 'keep' = 'accept') {
    if (!selected.length || busy.value || (!receivedOnce.value && (!participating.value || !driver.value || !state.value?.snapshot_id || phase.value !== 'CONFLICT_PENDING'))) return
    const token = generation
    busy.value = true; error.value = ''
    try {
      if (!participating.value) await resumeForDownload(token)
      local.value = await native<LocalCollaborationStatus>('restore', { task_id: String(options.task()?.id), operation_id: crypto.randomUUID(), conflict_set_id: conflictSetId, decision, selected: selected.map(row => ({ task_repository_id: row.task_repository_id, path: row.path, expected_sha256: row.expected_sha256 ?? row.local?.sha256 ?? null })) })
      check(token); if (participating.value) await receipt(state.value!.snapshot_id!, local.value, token)
    } catch (reason) { if (token === generation) error.value = formatApiError(reason, t('collaboration.failed')) }
    finally {
      try { if (!participating.value) await suspendLocal() } catch (reason) { error.value = formatApiError(reason, t('collaboration.failed')) }
      if (token === generation) busy.value = false
    }
  }

  async function readText(hash: string): Promise<string> {
    let object: { content: string } | null = null
    if (available) try { object = await native<{ content: string } | null>('read_object', { sha256: hash, optional: true }) }
    catch (reason) { if (!/\bLOCAL_CONTENT_OBJECT_MISSING\b/.test(String(reason))) throw reason }
    const data = object === null ? new Uint8Array(await remote().object(hash)) : base64Bytes(object.content)
    if (data.length > 2 * 1024 * 1024 || data.includes(0)) throw new Error(t('collaboration.binary'))
    return new TextDecoder('utf-8', { fatal: true }).decode(data)
  }
  async function refreshComparison() {
    if (busy.value) return
    if (!participating.value && !receivedOnce.value) { mappingsDirty = true; await loadReview(); return }
    const token = generation
    try {
      if (mappingsDirty || preparationRequired.value || !participating.value) await loadMappings()
      check(token)
      if (!available) return
      if (!participating.value || !enabled.value || preparationRequired.value) { await inspectMappings(generation); error.value = ''; return }
      if (!driver.value) return
      const scanned = await native<LocalCollaborationStatus>('status', { task_id: String(options.task()?.id), verify: true })
      check(token); local.value = scanned
      if (cloud.value?.source === 'PROGRESS') {
        const preview = await native<LocalCollaborationStatus>('reconcile', { task_id: String(options.task()?.id), operation_id: `compare-${cloud.value.snapshot_id}`, target: cloud.value, preview: true, progressive: false })
        check(token); previewConflicts.value = preview.preview_conflicts || []
      }
    } catch (reason) { if (token === generation) error.value = formatApiError(reason, t('collaboration.failed')) }
  }
  async function handoffLocalChanges() {
    if (busy.value || !participating.value || !driver.value || state.value?.driver_connected === false || local.value?.state === 'RECOVERY_REQUIRED' || phase.value !== 'READY') return
    error.value = ''
    const operationId = localStorage.getItem(standaloneKey) || `manual-${crypto.randomUUID()}`, token = generation
    localStorage.setItem(standaloneKey, operationId); busy.value = true
    try {
      const capture = await native<CollaborationCapture>('capture', { task_id: String(options.task()?.id), operation_id: operationId, include_objects: false, session_generation: state.value!.session_generation, session_revision: state.value!.session_revision })
      check(token); await uploadManifest(capture.manifest, token, new Map())
      const accepted = await remote().post('handoff', { ...fence(), operation_id: operationId, manifest: capture.manifest, input_cut_seq: capture.input_cut_seq ?? 0 }); check(token); state.value = accepted
      const manifest = await snapshot(accepted.input_snapshot_id!); check(token)
      const advanced = await native<LocalCollaborationStatus>('accept_input', { task_id: manifest.task_id, operation_id: operationId, target: manifest }); check(token)
      local.value = advanced; input.value = manifest; cloud.value = manifest; lastTarget = manifest.snapshot_id; localStorage.removeItem(standaloneKey)
    } catch (reason) { if (token === generation) error.value = formatApiError(reason, t('collaboration.failed')) }
    finally { if (token === generation) busy.value = false }
  }
  async function listBackups() {
    const empty = { backup_directory: '', backups: [] as CollaborationBackup[] }
    const taskId = String(options.task()?.id || '')
    if (!available || !taskId) return empty
    try { return await native<typeof empty>('backups', { task_id: taskId }) }
    catch (reason) {
      // Older desktop hosts throw ENOENT instead of returning an empty backup list.
      if (missingBinding(reason, taskId)) return empty
      throw reason
    }
  }
  async function exportBackup(backup: CollaborationBackup) {
    if (!desktop || !backup.sha256) return
    const object = await native<{ content: string }>('read_object', { sha256: backup.sha256 })
    await desktop.download.save({ suggestedName: `${backup.task_repository_id}-${backup.path.replace(/[\\/]/g, '_')}`, data: base64Bytes(object.content), mimeType: 'application/octet-stream' })
  }
  async function claimDriver() {
    if (!state.value?.enabled || busy.value || !available) return
    busy.value = true
    const token = generation
    try {
      await loadMappings(); check(token)
      const claimed = await remote().post('claim-driver', { ...identity, operation_id: crypto.randomUUID() }); check(token); state.value = claimed; participating.value = true; receivedOnce.value = false
      local.value = await readBinding()
      check(token); await prepareCurrentBinding(token)
      lastTarget = ''; lastProgress = ''; lastLease = 0; leaseRetryAt = 0; deliveryRetryRequired.value = false; error.value = ''
    } catch (reason) { error.value = formatApiError(reason, t('collaboration.failed')) }
    finally { busy.value = false }
    await refresh()
  }
  async function recover() {
    if (busy.value || !driver.value || !state.value || state.value.driver_connected === false) return
    busy.value = true; error.value = ''; setStage('checkingMappings')
    const token = generation
    try {
      const current = await remote().state(); check(token); state.value = current
      if (!driver.value || !current.enabled || current.driver_connected === false) throw new Error(t('collaboration.claimDriverRequired'))
      if (state.value.recovery_kind === 'SERVER_INPUT') state.value = await remote().post('recover-input', { ...fence(), operation_id: state.value.recovery_operation_id || `handoff:${state.value.pending_submission_id}` })
      else if (state.value.recovery_kind === 'SERVER_OUTPUT' || phase.value === 'STOPPING') state.value = await remote().post('recover-output', { ...fence(), operation_id: crypto.randomUUID() })
      else if (['RUNNING', 'WAITING_HITL'].includes(state.value.sync_phase) && state.value.progress_snapshot_id) {
        const id = state.value.progress_snapshot_id
        await reconcile(await snapshot(id), token, true); lastProgress = id
      }
      else if (state.value.snapshot_id) {
        if (!['DELIVERY_PENDING', 'CONFLICT_PENDING', 'RECOVERY_REQUIRED'].includes(state.value.sync_phase)) throw new Error(t('collaboration.claimDriverRequired'))
        if (preparationRequired.value || !bindingPrepared(local.value)) {
          local.value = await readBinding()
          check(token); await prepareCurrentBinding(token)
        }
        lastTarget = ''; await reconcile(await snapshot(state.value.snapshot_id), token)
      }
      deliveryRetryRequired.value = false; error.value = ''
    } catch (reason) { error.value = formatApiError(reason, t('collaboration.failed')) }
    finally { busy.value = false }
  }
  function setProgressive(value: boolean) {
    if (progressive.value === value) return
    progressive.value = value; localStorage.setItem(`traceforge.collaboration.progressive:${options.task()?.id}`, String(value)); lastProgress = ''
    if (participating.value) void refresh()
  }
  async function suspendLocal() {
    const bindingId = local.value?.binding_id
    if (!bindingId) return
    await native('suspend', { task_id: String(options.task()?.id), binding_id: bindingId })
    if (local.value) local.value = { ...local.value, released: true, suspended: true }
    transportStatus = null
  }
  async function leave(): Promise<boolean> {
    if (leaving.value) return false
    if (!participating.value) return true
    leaving.value = true; generation++; refreshQueued = false; localRefreshQueued = false; eventVersion = 0
    const lease = state.value && { ...identity, lease_epoch: state.value.lease_epoch, operation_id: crypto.randomUUID() }
    try {
      await suspendLocal()
      if (lease && driver.value && enabled.value) state.value = await remote().post('release-driver', lease)
      participating.value = false; error.value = ''; return true
    } catch (reason) { error.value = formatApiError(reason, t('collaboration.failed')); return false }
    finally { leaving.value = false; busy.value = false }
  }
  async function resumeForDownload(token: number) {
    await loadMappings(); check(token)
    local.value = await readBinding()
    check(token)
    const repositories = local.value?.baseline && local.value?.directory_mode === 'MAPPED' ? mappedRepositories() : await inspectMappings(token)
    local.value = await native<LocalCollaborationStatus>('prepare', { ...state.value, task_id: String(options.task()?.id),
      binding_id: local.value?.binding_id || `receive-${options.task()?.id}`, directory_mode: 'MAPPED', repositories })
    check(token)
  }
  async function receiveOnce() {
    if (!available || busy.value || participating.value || !state.value) return
    const token = generation
    busy.value = true; error.value = ''; receivedOnce.value = false
    try {
      await resumeForDownload(token)
      const before = local.value?.baseline || null
      setStage('downloadingChanges')
      const wire = await remote().post<CollaborationManifest>('latest-snapshot', { base_snapshot_id: local.value?.baseline?.snapshot_id || null }); check(token)
      const manifest = expandManifest(local.value?.baseline, wire)
      await cacheManifest(manifest, token); check(token)
      input.value = before; cloud.value = manifest
      setStage('applyingChanges')
      local.value = await native<LocalCollaborationStatus>('reconcile', { task_id: manifest.task_id, operation_id: `receive-${manifest.snapshot_id}`, target: manifest, preview: false })
      check(token)
      if (local.value.errors?.length || local.value.state === 'RECOVERY_REQUIRED') throw new Error(local.value.errors?.join('\n') || t('collaboration.failed'))
      receivedOnce.value = true
    } catch (reason) { if (token === generation) error.value = formatApiError(reason, t('collaboration.failed')) }
    finally {
      try { await suspendLocal() } catch (reason) { error.value = formatApiError(reason, t('collaboration.failed')) }
      if (token === generation) busy.value = false
    }
  }
  function onEvent(payload: Record<string, unknown>) {
    const version = Number(payload.state_version || 0)
    // A command response can advance state before its input/manifest is processed.
    // Deduplicate against the last fetched state, not that response's version.
    if (disposed || leaving.value || payload.task_id !== options.task()?.id || version <= observedVersion) return
    eventVersion = Math.max(eventVersion, version)
    void drainUpdates()
  }
  function onConnectionReady(taskId: string) { if (taskId === options.task()?.id) void refresh() }
  const stopLocalUpdates = desktop?.collaboration?.onChanged?.(event => {
    if (disposed || leaving.value || !participating.value || event.task_id !== options.task()?.id) return
    localRefreshQueued = true
    void drainUpdates()
  })
  const openDirectory = (repositoryId?: string) => {
    const path = repositoryId ? local.value?.repositories?.find(repo => repo.task_repository_id === repositoryId)?.local_worktree_path : local.value?.repositories?.[0]?.local_worktree_path
    return path ? desktop?.system.openPath(path) : undefined
  }
  const submissionMetadata = () => {
    // Only a persisted PREPARING state or explicit handoff may upload local input.
    return enabled.value && (participating.value || remoteSender.value) ? { collaboration: { ...(remoteSender.value ? { request_driver_input: true } : identity), binding_id: state.value?.binding_id, lease_epoch: state.value?.lease_epoch } } : {}
  }
  async function initializationIdentity() {
    if (!available || !supported.value) return undefined
    busy.value = true
    await loadMappings()
    const binding = await readBinding()
    return { ...identity, binding_id: binding?.binding_id || state.value?.binding_id }
  }
  async function resetForInitialization(command: Record<string, any>) {
    if (command.task_id !== options.task()?.id) throw new Error('COLLABORATION_CONTEXT_CHANGED')
    const receipt = await native('initialize', command)
    transportStatus = null
    local.value = await readBinding()
    cloud.value = input.value = null
    lastTarget = ''; lastProgress = ''; lastHandoff = ''; lastLease = 0
    preparationRequired.value = deliveryRetryRequired.value = false
    participating.value = true
    localStorage.removeItem(standaloneKey)
    return receipt
  }
  async function finishInitialization() {
    busy.value = false
    await refresh()
  }
  const stopMappingUpdates = onRepoPreferencesChanged(options.workspaceId(), String(auth.user?.id || ''), () => {
    mappingsDirty = true; mappingChecks.value = []
    void refresh()
  })
  watch(() => [options.workspaceId(), options.task()?.id], () => {
    generation++; transportStatus = null; state.value = null; local.value = null; input.value = null; cloud.value = null; error.value = ''; busy.value = false; loading.value = supported.value
    lastTarget = ''; lastProgress = ''; lastHandoff = ''; lastLease = 0; leaseRetryAt = 0; failedPreparation = null; mappings.value = {}; preparationRequired.value = false; deliveryRetryRequired.value = false
    refreshQueued = false; localRefreshQueued = false; eventVersion = 0; observedVersion = 0; mappingsDirty = true; directories.value = null
    void refresh()
  }, { immediate: true })
  onScopeDispose(() => { disposed = true; generation++; clearInterval(heartbeat); clearInterval(stageClock); stopMappingUpdates(); stopLocalUpdates?.() })
  return { initializationIdentity, resetForInitialization, finishInitialization, reviewBaseline, reviewRunning, reviewLoading, reviewError: computed(() => baselineError.value || reviewError.value), loadReview, refreshResults, participating, leaving, receivedOnce, leave, receiveOnce, supported, available, state, local, cloud, input, error, busy, loading, preparationRequired, mappingChecks, operationStage, operationSeconds, enabled, driver, remoteSender, canReconnect, phase, label, blocked, conflicts, mappings, refresh, enable, restore, readText, openDirectory, submissionMetadata, directories, activity, progressive, setProgressive, claimDriver, recover, onEvent, onConnectionReady, refreshComparison, checkMappings, selectMapping, view, handoffLocalChanges, listBackups, exportBackup }
}
type Controller = ReturnType<typeof createController>
const controllers = new Map<string, { scope: EffectScope; controller: Controller; users: number }>()
function ensureController(workspaceId: string, task: Record<string, any>, t: ReturnType<typeof useI18n>['t'], auth: ReturnType<typeof useAuthStore>) {
  const userId = auth.user!.id, key = JSON.stringify([userId, workspaceId, task.id])
  let entry = controllers.get(key)
  if (!entry) {
    const scope = effectScope(true)
    const controller = scope.run(() => {
      watch(() => auth.user?.id, current => { if (current !== userId) { controllers.delete(key); scope.stop() } })
      return createController({ workspaceId: () => workspaceId, task: () => task }, t, auth)
    })!
    entry = { scope, controller, users: 0 }; controllers.set(key, entry)
  }
  entry.users++
  const retained = entry
  return { controller: entry.controller, release: () => {
    retained.users--
    if (retained.users) return
    void retained.controller.leave().finally(() => {
      if (!retained.users) { if (controllers.get(key) === retained) controllers.delete(key); retained.scope.stop() }
    })
  } }
}

/** Drawers share the page controller; leaving the task releases its lease and watchers. */
export function useLocalCollaboration(options: { workspaceId: () => string; task: () => Record<string, any> | null }) {
  const { t } = useI18n(), auth = useAuthStore()
  const active = shallowRef<Controller | null>(null)
  watch(() => [options.workspaceId(), options.task()?.id, options.task()?.execution_location, options.task()?.task_type, auth.user?.id], (_, __, onCleanup) => {
    const task = options.task(), workspaceId = options.workspaceId(), userId = auth.user?.id
    if (!task?.id || task.execution_location !== 'SERVER' || task.task_type === 'DIAGNOSIS' || !userId) { active.value = null; return }
    const retained = ensureController(workspaceId, task, t, auth)
    active.value = retained.controller
    onCleanup(retained.release)
  }, { immediate: true })
  return {
    reviewBaseline: computed(() => active.value?.reviewBaseline.value || null),
    reviewRunning: computed(() => active.value?.reviewRunning.value || false),
    reviewLoading: computed(() => active.value?.reviewLoading.value || false),
    reviewError: computed(() => active.value?.reviewError.value || ''),
    loadReview: async () => { await active.value?.loadReview() },
    refreshResults: () => active.value?.refreshResults(),
    participating: computed(() => active.value?.participating.value || false), leaving: computed(() => active.value?.leaving.value || false),
    receivedOnce: computed(() => active.value?.receivedOnce.value || false),
    leave: async () => active.value ? active.value.leave() : true, receiveOnce: async () => { await active.value?.receiveOnce() },
    supported: computed(() => Boolean(active.value)), available: Boolean(getSddDesktop()?.collaboration),
    state: computed(() => active.value?.state.value || null), local: computed(() => active.value?.local.value || null),
    cloud: computed(() => active.value?.cloud.value || null), input: computed(() => active.value?.input.value || null),
    error: computed(() => active.value?.error.value || ''), busy: computed(() => active.value?.busy.value || false),
    loading: computed(() => active.value?.loading.value || false), enabled: computed(() => active.value?.enabled.value || false),
    preparationRequired: computed(() => active.value?.preparationRequired.value || false),
    mappingChecks: computed(() => active.value?.mappingChecks.value || []),
    operationStage: computed(() => active.value?.operationStage.value || ''), operationSeconds: computed(() => active.value?.operationSeconds.value || 0),
    driver: computed(() => active.value?.driver.value || false), phase: computed(() => active.value?.phase.value || 'OFF'),
    canReconnect: computed(() => active.value?.canReconnect.value || false),
    remoteSender: computed(() => active.value?.remoteSender.value || false),
    label: computed(() => active.value?.label.value || ''), blocked: computed(() => active.value?.blocked.value || false),
    conflicts: computed(() => active.value?.conflicts.value || []), mappings: computed(() => active.value?.mappings.value || {}),
    directories: computed(() => active.value?.directories.value || null), activity: computed(() => active.value?.activity.value || { direction: '', done: 0, total: 0, bytes: 0, totalBytes: 0 }),
    view: computed(() => active.value?.view.value || { page: 'files', tab: 'all', pair: 'auto', selected: '', selectedConflicts: [] as string[], conflictSetId: '' }),
    progressive: computed(() => active.value?.progressive.value || false), setProgressive: (value: boolean) => active.value?.setProgressive(value),
    initializationIdentity: async () => active.value?.initializationIdentity(),
    resetForInitialization: async (command: Record<string, any>) => { if (!active.value) throw new Error('COLLABORATION_CONTEXT_CHANGED'); return active.value.resetForInitialization(command) },
    finishInitialization: async () => { await active.value?.finishInitialization() },
    refresh: async () => { await active.value?.refresh() }, enable: async () => { await active.value?.enable() },
    restore: async (selected: CollaborationConflict[], id: string, decision: 'accept' | 'keep' = 'accept') => { await active.value?.restore(selected, id, decision) },
    readText: async (hash: string) => { if (!active.value) throw new Error('COLLABORATION_CONTEXT_CHANGED'); return active.value.readText(hash) },
    openDirectory: (repositoryId?: string) => active.value?.openDirectory(repositoryId), submissionMetadata: () => active.value?.submissionMetadata() || {},
    claimDriver: async () => { await active.value?.claimDriver() }, recover: async () => { await active.value?.recover() },
    onEvent: (payload: Record<string, unknown>) => active.value?.onEvent(payload),
    onConnectionReady: (taskId: string) => active.value?.onConnectionReady(taskId),
    refreshComparison: async () => { await active.value?.refreshComparison() },
    checkMappings: async () => { await active.value?.checkMappings() }, selectMapping: async (repositoryId: string) => { await active.value?.selectMapping(repositoryId) },
    handoffLocalChanges: async () => { await active.value?.handoffLocalChanges() },
    listBackups: async () => active.value ? active.value.listBackups() : { backup_directory: '', backups: [] as CollaborationBackup[] }, exportBackup: async (backup: CollaborationBackup) => { await active.value?.exportBackup(backup) },
  }
}
export type LocalCollaboration = ReturnType<typeof useLocalCollaboration>
