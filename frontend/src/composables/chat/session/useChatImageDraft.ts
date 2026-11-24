import { computed, onScopeDispose, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import api from '@/utils/api'

export interface ChatImageReference {
  id: string
  filename: string
  media_type: string
}

export interface ChatImageDraft {
  file: File
  previewUrl: string
}

export function messageChatImages(metadata: { chat_images?: unknown } | null | undefined): ChatImageReference[] {
  return Array.isArray(metadata?.chat_images) ? metadata.chat_images : []
}

export async function readChatImage(workspaceId: string, taskId: string, imageId: string, signal: AbortSignal) {
  const { data } = await api.get<Blob>(
    `/workspaces/${workspaceId}/tasks/${taskId}/chat-images/${encodeURIComponent(imageId)}`,
    { responseType: 'blob', signal },
  )
  return data
}

export const chatImageAccept = 'image/png,image/jpeg,image/webp,image/gif'
const supportedTypes = new Set(chatImageAccept.split(','))
const maxImages = 4
const maxImageBytes = 5 * 1024 * 1024

export function useChatImageDraft(getWorkspaceId: () => string, getTaskId: () => string) {
  const { t } = useI18n()
  const items = shallowRef<ChatImageDraft[]>([])
  let activeRequest: AbortController | undefined

  function removeSent(sent: readonly ChatImageDraft[]) {
    items.value = items.value.filter(item => {
      if (!sent.includes(item)) return true
      URL.revokeObjectURL(item.previewUrl)
      return false
    })
  }

  function reset() {
    activeRequest?.abort()
    removeSent(items.value)
  }

  watch([getWorkspaceId, getTaskId], reset, { flush: 'sync' })
  onScopeDispose(reset)

  function add(files: readonly File[]) {
    const next = [...items.value]
    for (const file of files) {
      if (next.length === maxImages) {
        ElMessage.warning(t('chat.images.too_many', { count: maxImages }))
        break
      }
      if (!supportedTypes.has(file.type) || !file.size || file.size > maxImageBytes) {
        ElMessage.warning(t('chat.images.invalid_file', { name: file.name }))
        continue
      }
      next.push({ file, previewUrl: URL.createObjectURL(file) })
    }
    items.value = next
  }

  function remove(previewUrl: string) {
    removeSent(items.value.filter(item => item.previewUrl === previewUrl))
  }

  async function upload(drafts: readonly ChatImageDraft[], workspaceId: string, taskId: string) {
    const controller = new AbortController()
    activeRequest = controller
    const references = new Map<string, ChatImageReference>()
    try {
      for (const { file } of drafts) {
        const form = new FormData()
        form.append('file', file)
        const { data } = await api.post<ChatImageReference>(
          `/workspaces/${workspaceId}/tasks/${taskId}/chat-images`, form, { signal: controller.signal },
        )
        references.set(data.id, data)
      }
      return [...references.values()]
    } finally {
      if (activeRequest === controller) activeRequest = undefined
    }
  }

  async function restore(references: readonly ChatImageReference[]) {
    const workspaceId = getWorkspaceId()
    const taskId = getTaskId()
    const controller = new AbortController()
    activeRequest = controller
    try {
      const files = await Promise.all(references.map(async ({ id, filename, media_type }) => {
        const blob = await readChatImage(workspaceId, taskId, id, controller.signal)
        return new File([blob], filename, { type: media_type })
      }))
      if (controller.signal.aborted) return
      removeSent(items.value)
      add(files)
    } catch {
      if (!controller.signal.aborted) ElMessage.error(t('chat.images.restore_failed'))
    } finally {
      if (activeRequest === controller) activeRequest = undefined
    }
  }

  return { items: computed(() => items.value), add, remove, removeSent, upload, restore }
}
