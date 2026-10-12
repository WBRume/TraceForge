import { onScopeDispose, ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import type { LocalCollaboration } from './useLocalCollaboration'

/** Both sidebar selection and router navigation must finish release before switching context. */
export function useCollaborationLeave(controller: LocalCollaboration) {
  const show = ref(false)
  let pending: Promise<boolean> | null = null, resolve: ((allowed: boolean) => void) | undefined
  function request() {
    if (pending) return pending
    if (!controller.participating.value && !controller.busy.value) return Promise.resolve(true)
    show.value = true
    pending = new Promise<boolean>(done => { resolve = done })
    return pending
  }
  function finish(allowed: boolean) { show.value = false; resolve?.(allowed); resolve = undefined; pending = null }
  async function confirm() {
    if (controller.busy.value || controller.leaving.value) return
    if (await controller.leave()) finish(true)
  }
  onBeforeRouteLeave(request)
  onBeforeRouteUpdate((to, from) => to.params.taskId !== from.params.taskId || to.params.wsId !== from.params.wsId ? request() : true)
  const beforeUnload = (event: BeforeUnloadEvent) => {
    if (controller.participating.value || controller.busy.value) { event.preventDefault(); event.returnValue = '' }
  }
  const pageHide = () => { void controller.leave() }
  window.addEventListener('beforeunload', beforeUnload)
  window.addEventListener('pagehide', pageHide)
  onScopeDispose(() => {
    finish(false)
    window.removeEventListener('beforeunload', beforeUnload)
    window.removeEventListener('pagehide', pageHide)
  })
  return { show, request, confirm, cancel: () => { if (!controller.leaving.value) finish(false) } }
}
