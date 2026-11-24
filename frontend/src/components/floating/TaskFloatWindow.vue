<script setup lang="ts">
import { nextTick, onMounted, onScopeDispose, shallowRef } from 'vue'
import { Undo2 } from '@/components/icons'
import { useDesktopFloatDrag } from '@/composables/useDesktopFloatDrag'
import { useAuthStore } from '@/stores/auth'
import type { TaskFloatWindowApi } from '@/types/taskFloat'
import { taskFloatChannel, type TaskFloatMessage, type TaskFloatSession } from '@/desktop/taskFloatChannel'
import SessionContextPanel from '@/components/global-search/SessionContextPanel.vue'
import FloatingDockFrame from './FloatingDockFrame.vue'
import FloatingDockHeading from './FloatingDockHeading.vue'

const props = defineProps<{ id: string; workspaceId: string; taskId: string; controls: TaskFloatWindowApi }>()
const auth = useAuthStore()
const hasSession = shallowRef(auth.isAuthenticated)
const session = shallowRef<TaskFloatSession>()
const liveOutput = shallowRef('')
const refreshKey = shallowRef(0)
const actionError = shallowRef('')
const startDrag = useDesktopFloatDrag(
  request => props.controls.drag?.(request) ?? Promise.resolve(),
  () => { actionError.value = '移动浮窗失败，请重试。' },
)
const refresh = () => { refreshKey.value++ }
const channel = taskFloatChannel(props.id)
channel.onmessage = async ({ data }: MessageEvent<TaskFloatMessage>) => {
  if (data.type === 'session') {
    const initial = !session.value
    session.value = data.session
    liveOutput.value = data.output
    if (initial) {
      await nextTick()
      channel.postMessage({ type: 'prepared' } satisfies TaskFloatMessage)
    }
  } else if (data.type === 'output') liveOutput.value = data.text
  else if (data.type === 'refresh') refresh()
}

function onStorage(event: StorageEvent) {
  if (event.key === null || event.key === 'sdd_token' || event.key === 'sdd_server_url') {
    hasSession.value = false
  }
}

async function finish(returnToClient: boolean) {
  try {
    if (returnToClient) await props.controls.returnToClient()
    else await props.controls.close()
  } catch {
    actionError.value = returnToClient ? '收回失败，请重试。' : '关闭失败，请重试。'
  }
}

// History also changes when a teammate posts or a run was started elsewhere.
const timer = window.setInterval(refresh, 6000)
onMounted(() => {
  window.addEventListener('storage', onStorage)
  channel.postMessage({ type: 'ready' } satisfies TaskFloatMessage)
})
onScopeDispose(() => {
  window.clearInterval(timer)
  window.removeEventListener('storage', onStorage)
  channel.close()
})
</script>

<template>
  <FloatingDockFrame v-if="session" desktop :desktop-drag="Boolean(controls.drag)" :title="session.taskName" :tone="session.tone"
    @desktop-drag-start="startDrag" @close="finish(false)">
    <template #header>
      <FloatingDockHeading label="会话" :workspace-name="session.workspaceName" :title="session.taskName" :tone="session.tone" />
    </template>
    <template #actions>
      <button type="button" class="action-icon-btn" aria-label="收回客户端" title="收回客户端" @click="finish(true)">
        <Undo2 class="w-3.5 h-3.5" />
      </button>
    </template>
    <p v-if="actionError" class="float-message" role="alert">{{ actionError }}</p>
    <SessionContextPanel v-if="hasSession" :workspace-id="workspaceId" :task-id="taskId" :live-output="liveOutput" :refresh-key="refreshKey"
      :initial-preview="session.preview" follow-latest />
    <p v-else class="float-message" role="status">登录状态已变化，请在客户端重新钉住会话。</p>
  </FloatingDockFrame>
</template>

<style scoped>
.float-message { padding: 8px 12px; margin: 0; color: #475569; font-size: 13px; }
</style>
