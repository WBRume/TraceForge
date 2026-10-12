import { computed, proxyRefs, type ShallowUnwrapRef } from 'vue'
import { useI18n } from 'vue-i18n'
import type { LocalCollaboration } from './useLocalCollaboration'

export type CollaborationContext = ShallowUnwrapRef<LocalCollaboration>
export type CollaborationAction = 'none' | 'connect' | 'recover' | 'reconnect' | 'device'

/** One presentation contract for the entry, drawer and composer; never changes execution permissions. */
export function collaborationPresentation(c: CollaborationContext) {
  const running = ['RUNNING', 'WAITING_HITL'].includes(c.phase)
  const conflicts = c.conflicts.length || c.state?.conflicts?.length || 0
  const localCount = c.local?.local_changes?.filter(file => !c.conflicts.some(conflict =>
    conflict.task_repository_id === file.task_repository_id && conflict.path === file.path)).length || 0
  const localAvailable = Boolean(c.available && c.driver && c.enabled && !c.preparationRequired
    && c.state?.driver_connected !== false && c.local?.baseline && !c.local?.errors?.length && c.local?.state !== 'RECOVERY_REQUIRED')
  let key = 'ready', action: CollaborationAction = 'none', tone = 'neutral', count = localCount
  if (c.loading) key = 'loading'
  else if (!c.enabled) { key = c.busy ? 'connecting' : 'connect'; action = c.busy ? 'none' : 'connect' }
  else if (c.state?.driver_connected === false) { key = 'offline'; action = c.canReconnect ? 'reconnect' : 'device'; tone = 'warning' }
  else if (!c.driver) { key = 'device'; action = 'device' }
  else if (c.busy) key = c.preparationRequired ? 'connecting' : c.phase === 'PREPARING' ? 'preparing' : 'transferring'
  else if (c.preparationRequired || !c.local?.baseline) { key = 'unprepared'; action = 'connect'; tone = 'warning' }
  else if (c.error || c.local?.errors?.length || c.local?.state === 'RECOVERY_REQUIRED' || c.phase === 'RECOVERY_REQUIRED') { key = 'error'; action = 'recover'; tone = 'warning' }
  else if (c.phase === 'CONFLICT_PENDING') { key = 'conflict'; count = conflicts; tone = 'warning' }
  else if (c.phase === 'PREPARING') key = 'preparing'
  else if (running) { key = c.phase === 'WAITING_HITL' ? 'waiting' : 'running'; count = conflicts }
  else if (['SETTLING', 'STOPPING', 'DELIVERY_PENDING'].includes(c.phase)) key = 'transferring'
  else if (localCount) key = 'local'
  else if (c.blocked) { key = 'unavailable'; action = 'recover'; tone = 'warning' }
  const setup = !c.enabled || (c.driver && (c.preparationRequired || !c.local?.baseline))
  const canRestore = localAvailable && !c.busy && !c.error && c.phase === 'CONFLICT_PENDING'
  const inputKey = !c.enabled ? '' : c.blocked ? key : localCount && localAvailable ? 'local' : ''
  return { key, action, tone, count, conflicts, localCount, localAvailable, setup, running, canRestore, inputKey }
}

export function useCollaborationPresentation(controller: () => LocalCollaboration | undefined) {
  const { t } = useI18n()
  return computed(() => {
    const instance = controller()
    if (!instance) return null
    const c = proxyRefs(instance), model = collaborationPresentation(c), params = { count: model.count }
    return {
      ...model,
      short: t(`collaboration.ui.states.${model.key}.short`, params),
      title: t(`collaboration.ui.states.${model.key}.title`, params),
      description: t(`collaboration.ui.states.${model.key}.description`, params),
      inputText: model.inputKey ? t(`collaboration.ui.states.${model.inputKey}.input`, params) : '',
      actionLabel: model.action === 'none' ? '' : t(`collaboration.ui.actions.${model.action}`),
    }
  })
}

export function openCollaborationView(controller: LocalCollaboration, device = false) {
  const model = collaborationPresentation(proxyRefs(controller))
  controller.view.value.page = device ? 'settings' : 'files'
  controller.view.value.tab = model.conflicts ? 'conflicts' : model.localCount && model.localAvailable ? 'local' : 'all'
  controller.view.value.pair = 'auto'
}
