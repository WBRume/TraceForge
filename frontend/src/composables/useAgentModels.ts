import { computed, onScopeDispose, shallowRef, watch } from 'vue'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'

export interface AgentModelSelection {
  backend: 'claude-code' | 'opencode' | 'dsh'
  model: string
}
export interface AgentModelOption { value: string; label: string }
interface ModelContext { workspaceId: string; taskId?: string; resourceId?: string; resourceRevision?: number }

export function useAgentModels(context: () => ModelContext) {
  const backend = shallowRef<AgentModelSelection['backend'] | null>(null)
  const options = shallowRef<AgentModelOption[]>([])
  const selected = shallowRef('')
  const loading = shallowRef(false)
  const error = shallowRef('')
  let sequence = 0
  let selectionRevision = 0
  let dirty = false
  let controller: AbortController | undefined
  const selection = computed<AgentModelSelection | undefined>(() =>
    backend.value && selected.value ? { backend: backend.value, model: selected.value } : undefined)

  async function reload() {
    const current = ++sequence
    const revision = selectionRevision
    controller?.abort()
    controller = new AbortController()
    const target = context()
    if (!target.workspaceId) return
    loading.value = true
    error.value = ''
    try {
      const { data } = await api.get(`/workspaces/${target.workspaceId}/agent-models`, {
        params: { task_id: target.taskId || undefined, resource_id: target.resourceId || undefined },
        signal: controller.signal,
      })
      if (current !== sequence) return
      if (!['claude-code', 'opencode', 'dsh'].includes(data?.backend) || !Array.isArray(data?.options)) {
        throw new Error('模型列表响应无效')
      }
      backend.value = data.backend
      options.value = data.options
      error.value = data.error || ''
      if (!dirty && revision === selectionRevision) selected.value = data.current_model || ''
      ensureOption()
    } catch (e) {
      if (current === sequence) error.value = formatApiError(e, '模型列表加载失败')
    } finally {
      if (current === sequence) loading.value = false
    }
  }
  function ensureOption() {
    if (selected.value && !options.value.some(option => option.value === selected.value)) {
      options.value = [{ value: selected.value, label: selected.value }, ...options.value]
    }
  }
  function select(value: string) { selected.value = value; dirty = true; ++selectionRevision }
  function observe(model?: string) {
    if (!model || dirty) return
    ++selectionRevision
    selected.value = model
    ensureOption()
  }
  function submitted(value?: AgentModelSelection) {
    if (value?.backend === backend.value && value?.model === selected.value) dirty = false
  }
  watch(() => JSON.stringify(context()), () => {
    backend.value = null
    options.value = []
    selected.value = ''
    error.value = ''
    loading.value = false
    dirty = false
    ++selectionRevision
    void reload()
  }, { immediate: true, flush: 'sync' })
  onScopeDispose(() => { ++sequence; controller?.abort() })
  return { backend, options, selected, selection, loading, error, select, observe, submitted, reload }
}
