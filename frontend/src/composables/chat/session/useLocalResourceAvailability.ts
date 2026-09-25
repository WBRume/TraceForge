import { computed, ref, watch } from 'vue'

export function useLocalResourceAvailability(getTask: () => any) {
  const status = ref<'checking' | 'online' | 'offline'>('checking')
  watch(() => getTask()?.id, () => { status.value = 'checking' }, { flush: 'sync' })
  const isLocal = computed(() => getTask()?.execution_location === 'LOCAL')
  const blocked = computed(() => isLocal.value && status.value !== 'online')
  const label = computed(() => status.value === 'online' ? '本地资源在线'
    : status.value === 'offline' ? '本地资源离线' : '本地资源连接确认中')
  function receive(payload: any) {
    if (payload?.task_id !== getTask()?.id) return
    status.value = payload.status === 'online' ? 'online' : 'offline'
  }
  function disconnected(taskId: string) {
    if (taskId === getTask()?.id) status.value = 'checking'
  }
  return { isLocal, status, blocked, label, receive, disconnected }
}
