<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { AlertCircle, Loader2 } from '@/components/icons'
import ChatMessageContent from '@/components/chat/ChatMessageContent.vue'
import { mapHistoryMessages, type ChatMessageFields } from '@/composables/chat/shared/messageIdentity'
import { formatMessageTime } from '@/composables/chat/message/presenters'
import api from '@/utils/api'
import { useTaskAwarenessStore } from '@/stores/taskAwareness'

const props = defineProps<{
  workspaceId: string
  taskId: string
  taskName: string
}>()

const loading = ref(false)
const error = ref('')
const messages = ref<ChatMessageFields[]>([])
const displayMessages = computed(() => messages.value.map(msg => ({
  ...msg,
  senderLabel: msg.role === 'user'
    ? msg.creator_display_name?.trim() || (msg.creator_id ? `用户 ${msg.creator_id}` : '未知用户')
    : msg.role === 'system' ? '系统' : 'AI 助手',
  isExpert: msg.role === 'user' && msg.creator_is_workspace_expert,
})))
const awareness = useTaskAwarenessStore()
const liveOutput = computed(() => awareness.outputs[props.taskId]?.text || '')
let requestVersion = 0
let refreshTimer: ReturnType<typeof setTimeout> | undefined

const fetchHistory = async () => {
  if (!props.workspaceId || !props.taskId) return
  loading.value = true
  error.value = ''
  const version = ++requestVersion
  const workspaceId = props.workspaceId, taskId = props.taskId
  try {
    const res = await api.get(`/workspaces/${workspaceId}/tasks/${taskId}/history`, {
      params: { page: 1, page_size: 60 }
    })
    if (version !== requestVersion) return
    const rawMessages = res.data?.messages || []
    messages.value = mapHistoryMessages(rawMessages.map((m: any) => ({
      ...m,
      id: String(m.id),
      role: String(m.role || 'assistant').toLowerCase(),
      content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content || ''),
      created_at: m.created_at
    })))
  } catch (err: any) {
    if (version !== requestVersion) return
    error.value = err.response?.data?.detail || '加载会话上下文失败，请检查网络或重试。'
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

onMounted(() => {
  void fetchHistory()
})
const onContextChanged = (event: Event) => {
  if ((event as CustomEvent).detail?.taskId !== props.taskId) return
  clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => { void fetchHistory() }, 100)
}
window.addEventListener('task-context-changed', onContextChanged)
onBeforeUnmount(() => { requestVersion++; clearTimeout(refreshTimer); window.removeEventListener('task-context-changed', onContextChanged) })

watch(() => [props.workspaceId, props.taskId], () => {
  void fetchHistory()
})
</script>

<template>
  <div class="session-context-panel">
    <!-- 简易面板提示条：只读无操作说明 -->
    <div class="panel-readonly-notice">
      <span>会话只读面板 · 支持滚动查看上下文</span>
    </div>

    <div v-if="liveOutput" class="live-output" aria-label="实时输出"><span>最新输出</span><pre>{{ liveOutput }}</pre></div>

    <!-- 加载中状态 -->
    <div v-if="loading" class="panel-status-area">
      <Loader2 class="w-5 h-5 spin text-sky-500" />
      <span>正在加载会话历史…</span>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="error" class="panel-status-area error">
      <AlertCircle class="w-5 h-5 text-rose-500" />
      <span>{{ error }}</span>
      <button type="button" class="retry-btn" @click="fetchHistory">重试</button>
    </div>

    <!-- 空记录 -->
    <div v-else-if="!messages.length" class="panel-status-area empty">
      <span>暂无更多会话消息</span>
    </div>

    <!-- 可滚动查看的对话上下文列表（纯只读，无点击功能） -->
    <div v-else class="context-scroll-list">
      <ChatMessageContent
        v-for="msg in displayMessages"
        :key="msg.id"
        :msg="msg"
        :related-messages="messages"
        :author-label="msg.senderLabel"
        :time-label="formatMessageTime(msg.created_at)"
        :is-expert="msg.isExpert"
      />
    </div>
  </div>
</template>

<style scoped>
.live-output { max-height: 35%; overflow: auto; padding: 8px 12px; background: #f8fafc; font-size: 11px; color: #64748b; }
.live-output pre { white-space: pre-wrap; word-break: break-word; font-size: 12px; color: #334155; }
.session-context-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #ffffff;
}

.panel-readonly-notice {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #f0f9ff;
  border-bottom: 1px solid #e0f2fe;
  font-size: 11px;
  color: #0369a1;
  font-weight: 500;
  user-select: none;
}

.panel-status-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: #64748b;
  font-size: 13px;
}

.panel-status-area.error {
  color: #e11d48;
}

.retry-btn {
  margin-top: 4px;
  padding: 4px 12px;
  font-size: 12px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  color: #334155;
  cursor: pointer;
  transition: all 0.2s;
}

.retry-btn:hover {
  border-color: #0ea5e9;
  color: #0ea5e9;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 核心滚动区域：支持平滑滚动查看上下文，内部纯只读 */
.context-scroll-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: #ffffff !important;
  user-select: text; /* 允许选中文本查阅复制 */
}

</style>
