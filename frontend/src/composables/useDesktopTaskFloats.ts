import { onScopeDispose, shallowReactive, shallowRef, watch } from 'vue'
import type { Ref, WatchHandle } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { usePinnedFloatsStore, type PinnedSearchItem } from '@/stores/pinnedFloats'
import { useTaskAwarenessStore } from '@/stores/taskAwareness'
import { taskFloatChannel, type SessionPreview, type TaskFloatMessage, type TaskFloatSession } from '@/desktop/taskFloatChannel'
import type { PanelDrag, TaskFloatPlacement } from '@/types/taskFloat'
import { getSddDesktop } from '@/utils/runtime'
import { getApiServerUrl } from '@/utils/api'
import { fitFloatingPosition } from '@/components/floating/floatingGeometry'

type OpenFloat = {
  id: string
  item: PinnedSearchItem
  channel: BroadcastChannel
  presented: Ref<boolean>
  detached: Ref<boolean>
  stopWatching: WatchHandle[]
  nativeReady: boolean
  rendererReady: boolean
  pending?: TaskFloatPlacement
  frame?: number
  placing: boolean
  closing: boolean
  timeout: number
}

export function useDesktopTaskFloats() {
  const bridge = getSddDesktop()?.taskFloats
  const auth = useAuthStore()
  const awareness = useTaskAwarenessStore()
  const pins = usePinnedFloatsStore()
  const floats = shallowReactive(new Map<string, OpenFloat>())

  const isCurrent = (entry: OpenFloat) => floats.get(entry.item.id) === entry

  function release(entry: OpenFloat) {
    if (!isCurrent(entry)) return
    for (const stop of entry.stopWatching) stop()
    if (entry.frame !== undefined) cancelAnimationFrame(entry.frame)
    window.clearTimeout(entry.timeout)
    entry.channel.close()
    floats.delete(entry.item.id)
  }

  async function closeWindow(id: string) {
    try {
      await bridge?.close(id)
    } catch (error) {
      console.error('Failed to close task float', error)
    }
  }

  function finishClose(entry: OpenFloat) {
    if (!entry.nativeReady) release(entry)
    else void closeWindow(entry.id).then(() => release(entry))
  }

  function close(entry: OpenFloat) {
    if (entry.closing) return
    entry.closing = true
    entry.pending = undefined
    // Let a placement already sent to the host finish before hiding that window.
    if (!entry.placing) finishClose(entry)
  }

  function fail(entry: OpenFloat, error: unknown, requested = Boolean(entry.pending?.position)) {
    if (!isCurrent(entry)) return
    close(entry)
    if (requested) {
      console.error('Failed to display task float', error)
      ElMessage.error('无法移到桌面，请重新拖动。')
    }
  }

  function schedulePlacement(entry: OpenFloat) {
    if (entry.closing || !entry.nativeReady || !entry.rendererReady || !entry.pending || entry.placing || entry.frame !== undefined) return
    entry.frame = requestAnimationFrame(() => {
      entry.frame = undefined
      void place(entry)
    })
  }

  async function place(entry: OpenFloat) {
    const placement = entry.pending
    if (!bridge || !placement || !isCurrent(entry)) return
    entry.pending = undefined
    if (!placement.position && !entry.presented.value) return
    entry.placing = true
    try {
      await bridge.place(placement)
      if (!isCurrent(entry) || entry.closing) return
      entry.presented.value = Boolean(placement.position)
      if (placement.dropped) {
        const { item } = entry
        if (item.source === 'automatic') {
          pins.pinTask({ id: item.taskId, name: item.taskName, workspaceId: item.workspaceId, workspaceName: item.workspaceName })
        }
        entry.detached.value = true
      }
    } catch (error) {
      fail(entry, error, Boolean(placement.position))
    } finally {
      entry.placing = false
      if (isCurrent(entry)) {
        if (entry.closing) finishClose(entry)
        else schedulePlacement(entry)
      }
    }
  }

  function move(item: PinnedSearchItem, drag: Exclude<PanelDrag, { type: 'start' }>) {
    const entry = floats.get(item.id)
    if (!entry || entry.detached.value || entry.closing) return
    if (drag.type === 'end' && !drag.position) {
      close(entry)
      return
    }
    entry.pending = { id: entry.id, position: drag.position, dropped: drag.type === 'end' }
    schedulePlacement(entry)
  }

  async function prepare(item: PinnedSearchItem, getSession: () => TaskFloatSession, getPreview: () => SessionPreview | undefined) {
    if (!bridge || !auth.isAuthenticated || item.kind !== 'task' || floats.has(item.id)) return
    const id = crypto.randomUUID()
    const channel = taskFloatChannel(id)
    const output = () => awareness.outputs[item.taskId]?.text || ''
    const send = (message: TaskFloatMessage) => channel.postMessage(message)
    const sendSession = (session: TaskFloatSession) => send({ type: 'session', session, output: output() })
    // The native frame and its renderer are prepared while the same pointer remains captured.
    const entry: OpenFloat = {
      id, item, channel,
      presented: shallowRef(false), detached: shallowRef(false),
      nativeReady: false, rendererReady: false, placing: false, closing: false,
      stopWatching: [
        watch(output, text => { if (!entry.closing) send({ type: 'output', text }) }),
        watch(getSession, session => { if (entry.rendererReady && !entry.closing) sendSession(session) }),
      ],
      timeout: window.setTimeout(() => fail(entry, new Error('Task float did not become ready')), 8000),
    }
    channel.onmessage = ({ data }: MessageEvent<TaskFloatMessage>) => {
      if (entry.closing) return
      if (data.type === 'ready') sendSession({ ...getSession(), preview: getPreview() })
      else if (data.type === 'prepared') {
        entry.rendererReady = true
        window.clearTimeout(entry.timeout)
        schedulePlacement(entry)
      }
    }
    floats.set(item.id, entry)
    try {
      await bridge.prepare({ id, workspaceId: item.workspaceId, taskId: item.taskId, title: item.taskName, size: { ...item.size } })
      if (!isCurrent(entry)) {
        await closeWindow(id)
        return
      }
      entry.nativeReady = true
      schedulePlacement(entry)
    } catch (error) {
      fail(entry, error)
    }
  }

  if (bridge) {
    const closeAll = () => {
      for (const entry of floats.values()) close(entry)
    }
    let serverUrl = getApiServerUrl()
    const onServerChanged = () => {
      const newUrl = getApiServerUrl()
      if (newUrl === serverUrl) return
      serverUrl = newUrl
      closeAll()
    }
    const unlisten = bridge.onClosed(({ id, action, position }) => {
      for (const entry of floats.values()) {
        if (entry.id !== id) continue
        if (action === 'dismissed') {
          // Remove the parked panel before clearing its desktop visibility state.
          entry.closing = true
          awareness.dismiss(entry.item.runId)
          pins.unpin(entry.item.id)
        } else if (action === 'returned' && position) {
          pins.updatePosition(entry.item.id, fitFloatingPosition(position, entry.item.size, {
            width: window.innerWidth,
            height: window.innerHeight,
          }))
        }
        release(entry)
        break
      }
    })
    const refreshContext = (event: Event) => {
      const taskId = (event as CustomEvent).detail?.taskId
      for (const entry of floats.values()) {
        if (!entry.closing && entry.item.taskId === taskId) entry.channel.postMessage({ type: 'refresh' } satisfies TaskFloatMessage)
      }
    }
    watch(() => pins.items.map(item => item.id), (ids) => {
      for (const [pinId, entry] of floats) {
        if (!ids.includes(pinId)) close(entry)
      }
    }, { flush: 'sync' })
    watch(() => auth.token, closeAll, { flush: 'sync' })
    window.addEventListener('sdd-server-changed', onServerChanged)
    window.addEventListener('task-context-changed', refreshContext)
    onScopeDispose(() => {
      closeAll()
      unlisten()
      window.removeEventListener('sdd-server-changed', onServerChanged)
      window.removeEventListener('task-context-changed', refreshContext)
    })
  }

  return {
    available: Boolean(bridge),
    isDragging: (pinId: string) => floats.get(pinId)?.detached.value === false,
    isPreviewing: (pinId: string) => floats.get(pinId)?.presented.value === true,
    isDetached: (pinId: string) => floats.get(pinId)?.detached.value === true,
    prepare,
    move,
  }
}
