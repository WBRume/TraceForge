import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { formatApiError } from '@/utils/error'
import { repositoryUpdatesApi, subscribeRepositoryUpdates, type UpdateSummary, type UpdatePlan, type UpdateFileDetail } from '@/services/repositoryUpdates'

export function useRepositoryUpdates(context: () => { workspaceId: string; taskId: string }) {
  const summary = shallowRef<UpdateSummary | null>(null)
  const plan = computed(() => summary.value?.plan || null)
  const busy = ref(''), error = ref(''), readError = ref(''), selected = ref('')
  const detail = shallowRef<UpdateFileDetail | null>(null)
  const fileLoading = ref(false)
  const drafts = ref<Record<string, { text: string; version: number }>>({})
  let generation = 0, readVersion = 0, disposed = false, pendingRefresh = false, detailKey = ''
  const api = () => repositoryUpdatesApi(context().workspaceId, context().taskId)
  const files = computed(() => (plan.value?.repositories || []).flatMap(repo => repo.files.map(file => ({ ...file, repo, key: `${repo.id}:${file.path}` }))))
  const active = computed(() => files.value.find(file => file.key === selected.value) || null)
  const conflicts = computed(() => files.value.filter(file => file.conflict).length)
  function put(next: UpdatePlan) {
    if (summary.value) summary.value = { ...summary.value, plan: next }
  }
  async function reload() {
    const token = generation, request = ++readVersion
    try {
      const value = await api().get()
      if (!disposed && token === generation && request === readVersion) { summary.value = value; readError.value = '' }
    } catch (reason) {
      if (!disposed && token === generation && request === readVersion) readError.value = formatApiError(reason, '读取任务代码版本失败')
    }
  }
  async function command(action: string, extra: Record<string, unknown> = {}) {
    if (busy.value) return false
    const token = generation, current = plan.value
    busy.value = action; error.value = ''; readVersion++
    try {
      const result = action === 'prepare' ? await api().prepare() : current ? await api().command(action, current, extra) : null
      if (disposed || token !== generation) return false
      if (result && action !== 'discard') put(result)
      await reload()
      return true
    } catch (reason) {
      if (!disposed && token === generation) { error.value = formatApiError(reason, '任务代码更新未完成'); await reload() }
      return false
    } finally {
      if (!disposed && token === generation) {
        busy.value = ''
        if (pendingRefresh) { pendingRefresh = false; void reload() }
      }
    }
  }
  watch(() => [context().workspaceId, context().taskId], () => {
    generation++; summary.value = null; selected.value = ''; detail.value = null; error.value = ''; busy.value = ''
    detailKey = ''; readError.value = ''; pendingRefresh = false
    void reload()
  }, { immediate: true })
  watch(files, list => { if (!list.some(file => file.key === selected.value)) selected.value = list[0]?.key || '' })
  watch(() => plan.value?.id, () => { drafts.value = {} })
  watch(() => [plan.value?.id, plan.value?.version, selected.value], async (_, __, cleanup) => {
    const current = plan.value, file = active.value
    if (!current || !file) { detail.value = null; fileLoading.value = false; return }
    const key = `${current.id}:${file.key}`
    if (detailKey !== key) detail.value = null
    const abort = new AbortController(); let valid = true
    cleanup(() => { valid = false; abort.abort() })
    fileLoading.value = true
    try { const result = await api().file(current, file.repo.id, file.path, abort.signal); if (valid) { detail.value = result; detailKey = key } }
    catch (reason) { if (valid) error.value = formatApiError(reason, '读取文件版本失败') }
    finally { if (valid) fileLoading.value = false }
  })
  const unsubscribe = subscribeRepositoryUpdates(event => {
    if (event.task_id !== context().taskId) return
    if (busy.value) { pendingRefresh = true; return }
    if (event.id === plan.value?.id && event.version && event.version <= (plan.value?.version || 0)) return
    void reload()
  })
  onScopeDispose(() => { disposed = true; generation++; unsubscribe() })
  return { summary, plan, busy, error: computed(() => error.value || readError.value), files, active, selected, detail, fileLoading, conflicts, drafts, command, reload }
}
export type RepositoryUpdates = ReturnType<typeof useRepositoryUpdates>
