import { computed, inject, ref, shallowRef, watch, type InjectionKey } from 'vue'
import type { AnnotationSelection, ContextAnnotation } from './contextAnnotations'
import { generateClientMessageId } from '../shared/messageIdentity'

export function useContextAnnotations(getContextKey: () => string) {
  const drafts = ref<Record<string, ContextAnnotation[]>>({})
  const pending = shallowRef<(AnnotationSelection & { x: number; y: number; contextKey: string }) | null>(null)
  const contextKey = computed(getContextKey)
  const items = computed(() => drafts.value[contextKey.value] || [])
  watch(contextKey, () => { pending.value = null }, { flush: 'sync' })

  function select(selection: AnnotationSelection, position: { x: number; y: number }) {
    if (!contextKey.value || !selection.selectedText.trim()) return
    pending.value = { ...selection, ...position, contextKey: contextKey.value }
  }
  function add(comment = '') {
    const selection = pending.value
    if (!selection || selection.contextKey !== contextKey.value) return
    drafts.value[contextKey.value] = [...items.value, {
      id: generateClientMessageId(), source: selection.source, selectedText: selection.selectedText, comment: comment.trim(),
    }]
    pending.value = null
  }
  function update(id: string, comment: string) {
    drafts.value[contextKey.value] = items.value.map(item => item.id === id ? { ...item, comment: comment.trim() } : item)
  }
  function remove(id: string) {
    drafts.value[contextKey.value] = items.value.filter(item => item.id !== id)
  }
  function snapshot() { return { key: contextKey.value, items: [...items.value] } }
  function consume(sent: ReturnType<typeof snapshot>) {
    // Keep annotations added or edited while a request was in flight, including on another task.
    drafts.value[sent.key] = (drafts.value[sent.key] || []).filter(item =>
      !sent.items.some(previous => previous.id === item.id && previous.comment === item.comment))
  }
  return { items, pending, contextKey, select, add, update, remove, snapshot, consume,
    clear: () => { drafts.value[contextKey.value] = [] },
    dismiss: () => { pending.value = null },
  }
}

export type ContextAnnotations = ReturnType<typeof useContextAnnotations>
export const contextAnnotationsKey: InjectionKey<ContextAnnotations> = Symbol('context-annotations')
export const injectContextAnnotations = () => inject(contextAnnotationsKey, null)
