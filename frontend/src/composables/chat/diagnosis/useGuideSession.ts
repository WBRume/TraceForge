import { shallowRef, watch } from 'vue'
import api from '@/utils/api'
import type { GuideSession } from '@/types/diagnosisPlaybook'

const errors: Record<string, string> = {
  AGENT_TURN_ACTIVE: '请等待当前 Agent 回合结束', STATE_VERSION_CONFLICT: '阶段状态已更新',
  STAGE_EVIDENCE_REQUIRED: '请先补充阶段证据', ROOT_CAUSE_CONFIRMATION_REQUIRED: '请先确认一个根因假说',
  EXECUTION_OBSERVATION_REQUIRED: '尚无执行结果', HYPOTHESIS_EVIDENCE_REQUIRED: '该假说尚无证据',
  HYPOTHESIS_NOT_SUPPORTED: '该假说未获证据支持或已被排除，不能确认为根因',
}
export function useGuideSession(options: { workspaceId: () => string; taskId: () => string; enabled: () => boolean; sessionGeneration?: () => number }) {
  const state = shallowRef<GuideSession | null>(null)
  const busy = shallowRef(false)
  const error = shallowRef('')
  let generation = 0
  let pending: { signature: string; key: string } | null = null
  let request: AbortController | null = null
  const base = () => `/workspaces/${options.workspaceId()}/tasks/${options.taskId()}/guide-session`
  const accept = (value: GuideSession) => {
    const expected = options.sessionGeneration?.()
    if (expected !== undefined && value.session_generation < expected) return
    if (state.value && value.session_generation < state.value.session_generation) return
    if (value.task_id !== options.taskId() || (state.value && value.version < state.value.version)) return
    state.value = value
  }
  const reload = async () => {
    if (!options.enabled() || !options.taskId()) return
    request?.abort()
    request = new AbortController()
    const signal = request.signal
    const current = generation
    try {
      const { data } = await api.get(base(), { signal })
      if (current === generation && !signal.aborted) { accept(data); error.value = '' }
    } catch { if (current === generation && !signal.aborted) error.value = '规程状态加载失败' }
  }
  watch(() => [options.workspaceId(), options.taskId(), options.enabled(), options.sessionGeneration?.()], (_v, _o, cleanup) => {
    generation++; state.value = null; busy.value = false; error.value = ''; pending = null
    void reload()
    cleanup(() => { generation++; request?.abort() })
  }, { immediate: true })
  const onEvent = (type: string, payload: any) => {
    if (!options.enabled() || payload.task_id !== options.taskId()) return
    if (type === 'playbook.guide_updated' && payload.snapshot) accept(payload.snapshot)
    if (type === 'playbook.resync') void reload()
  }
  const command = async (action: string, hypothesisId?: string) => {
    if (!state.value || busy.value) return
    const current = generation
    const body = { action, hypothesis_id: hypothesisId, expected_version: state.value.version }
    const signature = JSON.stringify(body)
    if (pending?.signature !== signature) pending = { signature, key: crypto.randomUUID() }
    busy.value = true; error.value = ''
    try {
      const { data } = await api.post(`${base()}/commands`, { ...body, idempotency_key: pending.key })
      if (current === generation) { accept(data); pending = null }
    } catch (e: any) {
      if (current !== generation) return
      if (e.response?.status === 409) { pending = null; await reload() }
      error.value = errors[e.response?.data?.detail?.code] || '操作失败，请重试'
    } finally { if (current === generation) busy.value = false }
  }
  return { state, busy, error, command, reload, onEvent }
}
