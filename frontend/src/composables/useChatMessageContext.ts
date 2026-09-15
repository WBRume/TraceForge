import { shallowRef, onScopeDispose } from 'vue'
import { searchApi } from '@/services/searchApi'
import type { MessageContext } from '@/types/search'

export function useChatMessageContext() {
  const anchored = shallowRef(false)
  const loading = shallowRef(false)
  const hasNew = shallowRef(false)
  const context = shallowRef<MessageContext | null>(null)
  let generation = 0
  let controller: AbortController | undefined
  const reset = () => {
    generation++
    controller?.abort()
    anchored.value = false
    loading.value = false
    hasNew.value = false
    context.value = null
  }
  const load = async (ws: string, task: string, message: string) => {
    reset()
    anchored.value = true
    loading.value = true
    const token = ++generation
    controller = new AbortController()
    try {
      const result = await searchApi.context(ws, task, message, controller.signal)
      if (token !== generation) return null
      context.value = result
      return result
    } finally { if (token === generation) loading.value = false }
  }
  const more = async (ws: string, task: string, direction: 'before' | 'after') => {
    const cursor = context.value?.[direction === 'before' ? 'before_cursor' : 'after_cursor']
    if (!cursor || loading.value) return null
    const token = ++generation
    controller = new AbortController()
    loading.value = true
    try {
      const result = await searchApi.moreContext(ws, task, cursor, direction, controller.signal)
      if (token !== generation || !context.value) return null
      context.value = { ...context.value, ...(direction === 'before'
        ? { before_cursor: result.before_cursor, has_before: result.has_before }
        : { after_cursor: result.after_cursor, has_after: result.has_after, at_latest: result.at_latest }) }
      return result
    } finally { if (token === generation) loading.value = false }
  }
  onScopeDispose(reset)
  return { anchored, loading, hasNew, context, load, more, reset }
}
