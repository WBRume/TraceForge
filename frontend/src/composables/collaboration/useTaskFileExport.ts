import { computed, shallowRef, watch, type ComputedRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { collaborationApi } from '@/services/collaborationApi'
import type { CollaborationFile } from '@/types/collaboration'
import { formatApiError } from '@/utils/error'
import type { CollaborationReviewFile } from './review'

type ExportOptions = {
  workspaceId: () => string
  taskId: () => string
  scope: () => string
  files: ComputedRef<CollaborationReviewFile[]>
  visibleFiles: ComputedRef<CollaborationReviewFile[]>
  cloud: (file: CollaborationReviewFile) => CollaborationFile | null | undefined
}

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function useTaskFileExport(options: ExportOptions) {
  const { t } = useI18n()
  const remote = computed(() => collaborationApi(options.workspaceId(), options.taskId()))
  const selected = shallowRef(new Set<string>())
  const pending = shallowRef(false)
  const entries = computed(() => new Map(options.files.value.flatMap(file => {
    const source = options.cloud(file)
    if (!source || source.mode === '120000') return []
    const path = file.repo_slug ? `${file.repo_slug}/${file.path}` : file.path
    return [[file.key, { path, sha256: source.sha256, size: source.size }] as const]
  })))
  const visibleKeys = computed(() => options.visibleFiles.value.filter(file => entries.value.has(file.key)).map(file => file.key))
  const selectedFiles = computed(() => [...selected.value].flatMap(key => entries.value.get(key) || []))
  const visibleSelected = computed(() => visibleKeys.value.filter(key => selected.value.has(key)).length)
  const allChecked = computed(() => visibleKeys.value.length > 0 && visibleSelected.value === visibleKeys.value.length)
  const partial = computed(() => visibleSelected.value > 0 && !allChecked.value)

  watch([options.taskId, options.scope], () => { selected.value = new Set() })
  watch(entries, list => { selected.value = new Set([...selected.value].filter(key => list.has(key))) })

  function check(keys: string[], value: boolean) {
    const next = new Set(selected.value)
    for (const key of keys) {
      if (value) next.add(key)
      else next.delete(key)
    }
    selected.value = next
  }

  async function withDownload(load: () => Promise<Blob>, name: string) {
    if (pending.value) return
    pending.value = true
    try { download(await load(), name) }
    catch (error) { ElMessage.error(formatApiError(error, t('task_deliverables.download_failed'))) }
    finally { pending.value = false }
  }

  function single(key: string) {
    const file = entries.value.get(key)
    if (!file) return
    const api = remote.value
    return withDownload(async () => new Blob([await api.object(file.sha256)], { type: 'application/octet-stream' }), file.path.split('/').at(-1)!)
  }

  function zip() {
    const files = selectedFiles.value
    if (!files.length) return
    const api = remote.value
    return withDownload(() => api.exportFiles(files.map(({ path, sha256 }) => ({ path, sha256 }))), `task-${options.taskId().slice(0, 8)}-files.zip`)
  }

  return { entries, selected, pending, selectedFiles, visibleKeys, allChecked, partial, check, single, zip }
}
