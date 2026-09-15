<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { AlertCircle, Loader2 } from 'lucide-vue-next'
import api from '@/utils/api'

interface HistoryMessageItem {
  id: string
  role: 'user' | 'assistant' | 'system' | string
  content: string
  created_at?: string
}

const props = defineProps<{
  workspaceId: string
  taskId: string
  taskName: string
}>()

const loading = ref(false)
const error = ref('')
const messages = ref<HistoryMessageItem[]>([])

const fetchHistory = async () => {
  if (!props.workspaceId || !props.taskId) return
  loading.value = true
  error.value = ''
  try {
    const res = await api.get(`/workspaces/${props.workspaceId}/tasks/${props.taskId}/history`, {
      params: { page: 1, page_size: 60 }
    })
    const rawMessages = res.data?.messages || []
    messages.value = rawMessages.map((m: any) => ({
      id: m.id || String(Math.random()),
      role: m.role || 'assistant',
      content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content || ''),
      created_at: m.created_at
    }))
  } catch (err: any) {
    error.value = err.response?.data?.detail || '加载会话上下文失败，请检查网络或重试。'
  } finally {
    loading.value = false
  }
}

const formatTime = (ts?: string) => {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

onMounted(() => {
  void fetchHistory()
})

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
      <div
        v-for="msg in messages"
        :key="msg.id"
        class="context-msg-row"
        :class="msg.role === 'user' ? 'is-user' : msg.role === 'system' ? 'is-system' : 'is-assistant'"
      >
        <!-- 系统消息 -->
        <div v-if="msg.role === 'system'" class="system-msg-text">
          {{ msg.content }}
        </div>

        <!-- 用户或助手消息：纯净文本呈现，无彩色 icon -->
        <template v-else>
          <div class="msg-content-col">
            <div class="msg-meta">
              <span class="sender-label">{{ msg.role === 'user' ? '用户' : 'AI 助手' }}</span>
              <span v-if="msg.created_at" class="msg-time">{{ formatTime(msg.created_at) }}</span>
            </div>
            <!-- 气泡内容：纯文本只读展示，不可点击触发任何操作 -->
            <div class="msg-bubble">
              {{ msg.content }}
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
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

/* 针对内部所有可能嵌套的内容，禁用外部点击跳转 */
.context-scroll-list :deep(a),
.context-scroll-list :deep(button:not(.retry-btn)) {
  pointer-events: none !important;
  cursor: default !important;
  text-decoration: none !important;
}

.context-msg-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.context-msg-row.is-user {
  flex-direction: row-reverse;
}

.context-msg-row.is-system {
  justify-content: center;
}

.system-msg-text {
  font-size: 11px;
  color: #94a3b8;
  background: #f1f5f9;
  padding: 2px 10px;
  border-radius: 999px;
}

.msg-content-col {
  display: flex;
  flex-direction: column;
  gap: 3px;
  max-width: 90%;
  width: 100%;
}

.is-user .msg-content-col {
  align-items: flex-end;
}

.msg-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #64748b;
}

.sender-label {
  font-weight: 600;
}

.msg-time {
  font-size: 10px;
  color: #94a3b8;
}

.msg-bubble {
  padding: 8px 12px;
  font-size: 12.5px;
  line-height: 1.55;
  border-radius: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.is-user .msg-bubble {
  background: linear-gradient(135deg, #0ea5e9, #0284c7);
  color: #ffffff;
  border-bottom-right-radius: 2px;
  box-shadow: 0 2px 8px rgba(14, 165, 233, 0.2);
}

.is-assistant .msg-bubble {
  background: #ffffff;
  color: #1e293b;
  border: 1px solid #e2e8f0;
  border-bottom-left-radius: 2px;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.04);
}
</style>
