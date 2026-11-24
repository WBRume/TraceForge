import { computed, onScopeDispose, shallowRef, watch } from 'vue'

export type ChatDraftScope = readonly [server: string, userId: string, workspaceId: string, taskId: string]

interface ChatDraftSnapshot {
  key: string
  content: string
}

const localChange = shallowRef<ChatDraftSnapshot>()
const memoryDrafts = new Map<string, string>()

function readDraft(key: string): string {
  if (!key) return ''
  const memoryDraft = memoryDrafts.get(key)
  if (memoryDraft !== undefined) return memoryDraft
  try {
    return localStorage.getItem(key) ?? ''
  } catch {
    return ''
  }
}

function writeDraft(key: string, content: string) {
  if (!key) return
  try {
    if (content) localStorage.setItem(key, content)
    else localStorage.removeItem(key)
    memoryDrafts.delete(key)
  } catch {
    memoryDrafts.set(key, content)
  }
  localChange.value = { key, content }
}

export function useChatTextDraft(getScope: () => ChatDraftScope | null) {
  const key = computed(() => {
    const scope = getScope()
    return scope ? `traceforge:chat-draft:${JSON.stringify(scope)}` : ''
  })
  const content = shallowRef('')

  watch(key, nextKey => { content.value = readDraft(nextKey) }, { immediate: true, flush: 'sync' })
  // A previous view may finish sending after the current view has mounted.
  watch(localChange, change => {
    if (change?.key === key.value) content.value = change.content
  }, { flush: 'sync' })

  function handleStorage(event: StorageEvent) {
    if (event.key === key.value || event.key === null) content.value = readDraft(key.value)
  }
  window.addEventListener('storage', handleStorage)
  onScopeDispose(() => window.removeEventListener('storage', handleStorage))

  return {
    current: computed<ChatDraftSnapshot>(() => ({ key: key.value, content: content.value })),
    set: (value: string) => writeDraft(key.value, value),
    clearSent: (sent: ChatDraftSnapshot) => {
      if (sent.content && readDraft(sent.key) === sent.content) writeDraft(sent.key, '')
    },
  }
}
