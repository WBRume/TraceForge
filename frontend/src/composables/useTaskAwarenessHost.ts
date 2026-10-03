import { onScopeDispose, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useTaskAwarenessStore } from '@/stores/taskAwareness'
import { flushDesktopWebhooks } from '@/utils/desktopWebhooks'

export function useTaskAwarenessHost() {
  const auth = useAuthStore()
  const route = useRoute()
  const awareness = useTaskAwarenessStore()
  const updateView = () => awareness.view(
    ['taskChat', 'taskSpec', 'workspaceAssetTaskDetail'].includes(String(route.name)) ? String(route.params.taskId || '') : '',
    document.visibilityState !== 'hidden' && document.hasFocus(),
  )
  const initiated = (event: Event) => { const data = (event as CustomEvent).detail; awareness.arm(data.taskId, data.requestId, data.jobId) }
  const rejected = (event: Event) => { const data = (event as CustomEvent).detail; awareness.disarm(data.taskId, data.requestId) }
  const restore = () => { awareness.reset(auth.user?.id || ''); updateView(); void awareness.refresh(); void flushDesktopWebhooks() }
  const jobObserved = (event: Event) => awareness.observeForegroundTerminal((event as CustomEvent).detail)
  const events: [EventTarget, string, EventListener][] = [
    [window, 'focus', updateView], [window, 'blur', updateView], [document, 'visibilitychange', updateView],
    [window, 'task-run-initiated', initiated], [window, 'task-run-rejected', rejected],
    [window, 'sdd-server-changed', restore],
    [window, 'task-job-observed', jobObserved],
  ]
  for (const [target, name, listener] of events) target.addEventListener(name, listener)
  watch(() => route.fullPath, updateView, { immediate: true, flush: 'sync' })
  watch(() => auth.user?.id, restore, { immediate: true })
  onScopeDispose(() => { for (const [target, name, listener] of events) target.removeEventListener(name, listener); awareness.stop() })
}
