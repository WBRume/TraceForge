<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Send,
  TerminalSquare,
  AlertCircle,
  CheckCircle2,
  Plus,
  Play,
  Loader2,
  Upload,
  Download,
  Trash2,
  AlertTriangle,
  ChevronDown,
  Wrench,
  Brain,
  XCircle,
  Clock,
  DollarSign,
  RotateCcw,
  OctagonPause,
  TestTube,
  Database,
  Sparkles,
} from 'lucide-vue-next'
import api from '@/utils/api'

const route = useRoute()
const router = useRouter()

// ─── State ───
const tasks = ref<any[]>([])
const currentTask = ref<any>(null)
const chatInput = ref('')
const currentWorkspace = ref<any>(null)

// Chat bubbles: 仅自然语言 (user / assistant text)
const messages = ref<any[]>([])

// 终端日志面板：tool_use, tool_result, raw logs
const terminalLogs = ref<any[]>([])
const showTerminal = ref(false)

// 置顶富文本卡片区：HITL, status, result (独立于对话流)
const pinnedCards = ref<any[]>([])

// AI 思考面板
const thinkingContent = ref('')
const showThinking = ref(false)
const thinkingExpanded = ref(true)

// 运行状况总览
const resultsSummary = ref({
  visible: false,
  totalDurationMs: 0,
  totalCostUsd: 0,
  history: [] as any[],
  expanded: false
})

// Task creation modal
const showTaskModal = ref(false)
const newTaskName = ref('')
const newTaskDesc = ref('')
const newTaskSpec = ref('')
const pendingSpecFile = ref<File | null>(null)
const useBrainstorm = ref(false)
const creatingTask = ref(false)
const uploadingSpec = ref(false)
const selectedFileName = ref('')
const showDeleteTaskConfirm = ref(false)
const showInterruptConfirm = ref(false)
const taskToDelete = ref<any>(null)

// Engine state
const engineRunning = ref(false)

// WebSocket
let ws: WebSocket | null = null

// ─── Computed ───
const activeHitlCards = computed(() =>
  pinnedCards.value.filter(c => c.type === 'hitl' && !c.answered)
)
const statusCards = computed(() =>
  pinnedCards.value.filter(c => c.type === 'status')
)

// ─── Load Data ───
const loadTasks = async () => {
  const wsId = route.params.wsId
  const res = await api.get(`/workspaces/${wsId}/tasks`)
  tasks.value = res.data.items

  if (route.params.taskId) {
    selectTask(tasks.value.find((t: any) => t.id === route.params.taskId))
  } else if (tasks.value.length > 0) {
    selectTask(tasks.value[0])
  }
}

const loadWorkspace = async () => {
  const wsId = route.params.wsId
  const res = await api.get(`/workspaces/${wsId}`)
  currentWorkspace.value = res.data
}

// ─── Task Actions ───
const openNewTaskModal = () => {
  showTaskModal.value = true
}

const handleFileUpload = (event: any) => {
  const file = event.target.files[0]
  if (!file) return
  pendingSpecFile.value = file
  selectedFileName.value = file.name
}

const handleCreateTask = async () => {
  if (!newTaskName.value) return
  creatingTask.value = true
  try {
    const wsId = route.params.wsId
    // 1. 创建任务
    const res = await api.post(`/workspaces/${wsId}/tasks`, {
      name: newTaskName.value,
      description: newTaskDesc.value,
      use_brainstorm: useBrainstorm.value
    })
    
    const taskId = res.data.id

    // 2. 如果选择了文件，关联上传
    if (pendingSpecFile.value) {
      uploadingSpec.value = true
      const formData = new FormData()
      formData.append('file', pendingSpecFile.value)
      try {
        await api.post(`/workspaces/${wsId}/tasks/${taskId}/upload-spec`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        })
      } catch (uploadError) {
        console.error('Spec upload failed', uploadError)
        // 即使上传失败，任务也已经创建，这里可以视情况报错或提示
      } finally {
        uploadingSpec.value = false
      }
    }

    showTaskModal.value = false
    newTaskName.value = ''
    newTaskDesc.value = ''
    newTaskSpec.value = ''
    pendingSpecFile.value = null
    useBrainstorm.value = false
    selectedFileName.value = ''
    
    await loadTasks()
    router.push(`/ws/${wsId}/chat/${taskId}`)
    
    // 重新获取一下最新的 task 对象（包含更新后的路径）
    const latestTaskRes = await api.get(`/workspaces/${wsId}/tasks/${taskId}`)
    selectTask(latestTaskRes.data)
  } catch (e) {
    console.error('Failed to create task', e)
  } finally {
    creatingTask.value = false
  }
}

const selectTask = async (task: any) => {
  if (!task) return
  currentTask.value = task
  messages.value = []
  terminalLogs.value = []
  pinnedCards.value = []
  thinkingContent.value = ''
  showThinking.value = false
  resultsSummary.value = { visible: false, totalDurationMs: 0, totalCostUsd: 0, history: [], expanded: false }
  engineRunning.value = false

  router.push(`/ws/${route.params.wsId}/chat/${task.id}`)
  connectWebSocket(task.id)
}

const handleInterruptClick = () => {
  if (!engineRunning.value) return
  showInterruptConfirm.value = true
}

const confirmInterrupt = async () => {
  if (!currentTask.value) return
  showInterruptConfirm.value = false
  engineRunning.value = false
  pinnedCards.value = pinnedCards.value.filter(c => c.type !== 'status' && c.type !== 'hitl')
  
  try {
    await api.post(`/workspaces/${route.params.wsId}/tasks/${currentTask.value.id}/cancel`)
    currentTask.value.status = 'FAILED'
    
    // 更新任务列表中的状态
    const t = tasks.value.find(task => task.id === currentTask.value.id)
    if (t) t.status = 'FAILED'

    messages.value.push({
      id: Date.now().toString(),
      role: 'system',
      content: '⚠️ 已强行中断任务。',
    })
  } catch(e) { console.error('Interrupt failed', e) }
}

const handleInitialize = async () => {
  if (!currentTask.value) return
  messages.value = []
  terminalLogs.value = []
  pinnedCards.value = []
  thinkingContent.value = ''
  showThinking.value = false
  resultsSummary.value = { visible: false, totalDurationMs: 0, totalCostUsd: 0, history: [], expanded: false }
  
  engineRunning.value = true
  try {
    await api.post(`/workspaces/${route.params.wsId}/tasks/${currentTask.value.id}/initialize`)
    currentTask.value.status = 'CODING'
    
    // 更新任务列表中的状态
    const t = tasks.value.find(task => task.id === currentTask.value.id)
    if (t) t.status = 'CODING'

    messages.value.push({
      id: Date.now().toString(),
      role: 'system',
      content: '🔄 会话已初始化，正在重新规划和运行…',
    })
  } catch(e) { console.error('Initialize failed', e) }
}

const handleDeleteTask = (task: any) => {
  taskToDelete.value = task
  showDeleteTaskConfirm.value = true
}

const confirmDeleteTask = async () => {
  if (!taskToDelete.value) return
  try {
    await api.delete(`/workspaces/${route.params.wsId}/tasks/${taskToDelete.value.id}`)
    showDeleteTaskConfirm.value = false
    const deletedId = taskToDelete.value.id
    taskToDelete.value = null
    await loadTasks()
    if (currentTask.value?.id === deletedId) {
      currentTask.value = null
      router.push(`/ws/${route.params.wsId}/chat`)
    }
  } catch (e) {
    console.error('Failed to delete task', e)
  }
}

const handleExport = async () => {
  if (!currentTask.value) return
  try {
    const res = await api.get(`/workspaces/${route.params.wsId}/tasks/${currentTask.value.id}/export`)
    const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `task-session-${currentTask.value.id}.json`
    link.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    console.error('Failed to export session', e)
  }
}

// ─── WebSocket ───
const connectWebSocket = (taskId: string) => {
  if (ws) ws.close()
  ws = new WebSocket(`ws://localhost:8000/ws/task/${taskId}`)
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    handleWsMessage(data)
  }
  ws.onclose = () => console.log('WS Disconnected')
}

const terminalContainer = ref<HTMLElement | null>(null)
const chatContainer = ref<HTMLElement | null>(null)

const scrollToBottom = async (target: 'chat' | 'terminal') => {
  await nextTick()
  if (target === 'chat' && chatContainer.value) {
    chatContainer.value.scrollTop = chatContainer.value.scrollHeight
  } else if (target === 'terminal' && terminalContainer.value) {
    terminalContainer.value.scrollTop = terminalContainer.value.scrollHeight
  }
}

// ─── 事件分发：严格按类型分区 ───
const handleWsMessage = (msg: any) => {
  const { type, payload } = msg

  switch (type) {
    case 'chat_message': {
      // 自然语言对话气泡 (user / assistant text)
      messages.value.push({
        id: Date.now().toString(),
        role: payload.role,
        content: payload.content,
      })
      scrollToBottom('chat')
      break
    }

    case 'thinking': {
      // AI 思考过程 → 思考面板 (不进入对话气泡)
      thinkingContent.value = payload.content
      showThinking.value = true
      break
    }

    case 'tool_use': {
      // 工具调用 → 终端面板 (不进入对话气泡)
      terminalLogs.value.push({
        type: 'tool_use',
        tool_name: payload.tool_name,
        tool_input: payload.tool_input,
        tool_use_id: payload.tool_use_id,
        timestamp: new Date().toLocaleTimeString(),
      })
      scrollToBottom('terminal')
      break
    }

    case 'tool_result': {
      // 工具执行结果 → 终端面板
      terminalLogs.value.push({
        type: 'tool_result',
        tool_use_id: payload.tool_use_id,
        output: payload.output,
        is_error: payload.is_error,
        timestamp: new Date().toLocaleTimeString(),
      })
      scrollToBottom('terminal')
      break
    }

    case 'log': {
      // 原始日志 → 终端面板
      terminalLogs.value.push({
        type: 'log',
        content: payload.content,
        timestamp: new Date().toLocaleTimeString(),
      })
      scrollToBottom('terminal')
      break
    }

    case 'hitl_request': {
      // HITL 交互 → 置顶富文本卡片 (不进入对话流)
      pinnedCards.value.push({
        id: Date.now().toString(),
        type: 'hitl',
        hitl_type: payload.hitl_type,
        prompt: payload.prompt,
        options: payload.options,
        context: payload.context,
        answered: false,
        answer: '',
        tempInput: '',
      })
      break
    }

    case 'status': {
      // 阶段状态 → 置顶卡片
      engineRunning.value = payload.status === 'INIT' || payload.status === 'RUNNING'
      pinnedCards.value = pinnedCards.value.filter(c => c.type !== 'status')
      pinnedCards.value.push({
        id: Date.now().toString(),
        type: 'status',
        status: payload.status,
        message: payload.message,
        model: payload.model,
      })
      if (currentTask.value) {
        currentTask.value.status = 'CODING'
        const t = tasks.value.find(t => t.id === currentTask.value.id)
        if (t) t.status = 'CODING'
      }
      break
    }

    case 'result': {
      // 执行结果 → 汇总卡片 + 标记引擎停止
      engineRunning.value = false
      pinnedCards.value = pinnedCards.value.filter(c => c.type !== 'status')
      
      resultsSummary.value.visible = true
      resultsSummary.value.totalDurationMs += payload.duration_ms || 0
      resultsSummary.value.totalCostUsd += (payload.cost_usd || 0)
      resultsSummary.value.history.push({
        id: Date.now().toString() + Math.random().toString().slice(2, 6),
        duration_ms: payload.duration_ms,
        cost_usd: payload.cost_usd,
        success: payload.success,
        result: payload.result,
        timestamp: new Date().toLocaleTimeString()
      })

      // 更新任务状态
      if (currentTask.value) {
        currentTask.value.status = payload.success ? 'IDLE' : 'FAILED'
        const t = tasks.value.find(t => t.id === currentTask.value.id)
        if (t) t.status = currentTask.value.status
      }
      
      break
    }
  }
}

// ─── HITL 回复 ───
const submitHitl = (cardId: string, response: string) => {
  if (!ws || !response) return
  ws.send(JSON.stringify({
    type: 'hitl_response',
    payload: { response }
  }))
  const card = pinnedCards.value.find(c => c.id === cardId)
  if (card) {
    card.answered = true
    card.answer = response
  }
}

// ─── 用户发送消息 ───
const sendChat = () => {
  if (!chatInput.value.trim() || !ws) return

  const content = chatInput.value.trim()

  // 显示到本地对话气泡
  messages.value.push({
    id: Date.now().toString(),
    role: 'user',
    content,
  })

  // 通过 WebSocket 发送给后端 → CLI 引擎
  ws.send(JSON.stringify({
    type: 'chat_message',
    payload: { role: 'user', content }
  }))

  chatInput.value = ''
  engineRunning.value = true
  scrollToBottom('chat')
}

// ─── 执行高阶 MCP 验证 ───
const sendVerification = (type: 'ui' | 'api' | 'e2e') => {
  if (!ws) return
  let prompt = ''
  if (type === 'ui') {
    prompt = '请调度 Playwright MCP：直接在 Chrome 浏览器中模拟用户点击、输入、路由跳转，验证 UI 渲染与交互逻辑。注意：务必在测试结束后自行执行清理脏数据 (Teardown)。'
  } else if (type === 'api') {
    prompt = '请调度 Postman MCP：远程执行自动化 API 脚本，验证 HTTP 状态码、响应 JSON 结构、数据持久化成果。注意：务必在测试结束后自行执行清理脏数据 (Teardown)。'
  } else if (type === 'e2e') {
    prompt = '请串联调度 Playwright MCP + Postman MCP：通过 UI 触发请求，并从后端或 DB 验证数据一致性，完成全链路端到端测试。注意：务必在测试结束后自行清理脏数据 (Teardown)。'
  }
  
  messages.value.push({
    id: Date.now().toString(),
    role: 'user',
    content: `[高阶验证] ${prompt}`,
  })

  ws.send(JSON.stringify({
    type: 'chat_message',
    payload: { role: 'user', content: prompt }
  }))
  engineRunning.value = true
  scrollToBottom('chat')
}

// ─── 启动引擎 ───
const startTask = async () => {
  if (!currentTask.value) return

  // 使用任务描述作为初始 prompt
  const prompt = currentTask.value.description || `请根据任务 '${currentTask.value.name}' 开始工作`

  await api.post(
    `/workspaces/${route.params.wsId}/tasks/${currentTask.value.id}/start`,
    { prompt }
  )

  currentTask.value.status = 'CODING'
  engineRunning.value = true

  messages.value.push({
    id: Date.now().toString(),
    role: 'system',
    content: '🚀 引擎已启动，Claude CLI 正在执行…',
  })
  scrollToBottom('chat')
}

// ─── 格式化工具调用显示 ───
const formatToolInput = (input: any): string => {
  if (!input) return ''
  if (typeof input === 'string') return input
  try {
    return JSON.stringify(input, null, 2)
  } catch {
    return String(input)
  }
}

// ─── Lifecycle ───
onMounted(() => {
  loadTasks()
  loadWorkspace()
})

onUnmounted(() => {
  if (ws) ws.close()
})
</script>

<template>
  <div class="chat-layout">
    <!-- Left Sidebar: Task List -->
    <aside class="task-sidebar glass-panel">
      <div class="sidebar-header">
        <h3>Task Sessions</h3>
        <button class="icon-btn" @click="openNewTaskModal" title="New Task">
          <Plus class="w-4 h-4" />
        </button>
      </div>
      <div class="task-list">
        <div
          v-for="task in tasks"
          :key="task.id"
          class="task-item group"
          :class="{ active: currentTask?.id === task.id }"
          @click="selectTask(task)"
        >
          <div class="task-item-content">
            <div class="task-name">{{ task.name }}</div>
            <div class="task-status">
              <span class="status-dot" :class="task.status.toLowerCase()"></span>
              {{ task.status }}
            </div>
          </div>
          <button class="icon-btn delete-btn" @click.stop="handleDeleteTask(task)">
             <Trash2 class="w-3.5 h-3.5" />
          </button>
        </div>
        <div v-if="tasks.length === 0" class="empty-hint">
          No tasks found. Create one.
        </div>
      </div>
    </aside>

    <!-- Center: Chat + Pinned Cards -->
    <section class="chat-main" v-if="currentTask">
      <!-- Header -->
      <header class="chat-header glass-panel">
        <div class="header-left">
          <h2>{{ currentTask.name }}</h2>
          <span class="badge" :class="currentTask.status.toLowerCase()">{{ currentTask.status }}</span>
          <Loader2 v-if="engineRunning" class="w-4 h-4 spin text-primary" />
        </div>
        <div class="header-actions">
          <button
            v-if="currentTask.status === 'PENDING' || currentTask.status === 'FAILED'"
            class="btn-primary start-btn"
            @click="startTask"
          >
            <Play class="w-4 h-4" /> Start Engine
          </button>

          <div class="action-divider"></div>

          <button class="icon-btn" @click="handleInitialize" title="初始化 (重启CLI环境)">
            <RotateCcw class="w-4 h-4" />
          </button>
          <button class="icon-btn danger" @click="handleInterruptClick" title="中断当前任务" :disabled="!engineRunning">
            <OctagonPause class="w-4 h-4" />
          </button>

          <button class="icon-btn" @click="handleExport" title="Export Session">
            <Download class="w-4 h-4" />
          </button>
          <button
            class="icon-btn"
            :class="{ active: showTerminal }"
            @click="showTerminal = !showTerminal"
            title="Toggle Terminal"
          >
            <TerminalSquare class="w-4 h-4" />
          </button>
          <button class="icon-btn danger" @click="handleDeleteTask(currentTask)" title="Delete Task">
            <Trash2 class="w-4 h-4" />
          </button>
        </div>
      </header>

      <!-- ★ 置顶富文本卡片区 (独立，不随对话滚动) -->
      <div class="pinned-cards-area" v-if="activeHitlCards.length > 0 || statusCards.length > 0 || showThinking">

        <!-- AI 思考面板 -->
        <div v-if="showThinking && thinkingContent" class="pinned-card thinking-card">
          <div class="card-header" @click="thinkingExpanded = !thinkingExpanded">
            <div class="header-title flex items-center gap-2">
              <Brain class="w-4 h-4" />
              <span>AI 思考中…</span>
            </div>
            <ChevronDown class="w-4 h-4 toggle-icon transition-transform" :class="{'rotate-180': thinkingExpanded}" />
          </div>
          <div v-show="thinkingExpanded" class="card-body thinking-body fixed-height">
            <pre>{{ thinkingContent }}</pre>
          </div>
        </div>

        <!-- 阶段状态卡片 -->
        <div v-for="card in statusCards" :key="card.id" class="pinned-card status-card"
             :class="{ 'is-error': card.status === 'FAILED' }">
          <div class="card-header">
            <CheckCircle2 v-if="card.status === 'COMPLETED'" class="w-4 h-4 text-success" />
            <XCircle v-else-if="card.status === 'FAILED'" class="w-4 h-4 text-error" />
            <Loader2 v-else class="w-4 h-4 spin text-primary" />
            <span>{{ card.message }}</span>
          </div>
        </div>

        <!-- 运行用量总结与历史日志 -->
        <div v-if="resultsSummary.visible" class="pinned-card status-card">
          <div class="card-header cursor-pointer" @click="resultsSummary.expanded = !resultsSummary.expanded">
            <div class="header-title flex items-center gap-2">
              <CheckCircle2 class="w-4 h-4 text-success" />
              <span class="text-sm font-medium text-gray-700">阶段执行总览</span>
            </div>
            <div class="card-meta flex gap-3 text-xs text-gray-500 items-center">
              <span>
                <Clock class="w-3 h-3 inline pb-0.5" /> {{ (resultsSummary.totalDurationMs / 1000).toFixed(1) }}s
              </span>
              <span>
                <DollarSign class="w-3 h-3 inline pb-0.5" /> ${{ resultsSummary.totalCostUsd.toFixed(4) }}
              </span>
              <ChevronDown class="w-4 h-4 transition-transform inline" :class="{'rotate-180': resultsSummary.expanded}" />
            </div>
          </div>
          <div v-show="resultsSummary.expanded" class="card-body flex flex-col gap-2 mt-2 border-t pt-2 border-gray-100">
            <div v-for="(step, idx) in resultsSummary.history" :key="step.id" class="text-xs text-slate-500 flex justify-between items-center bg-gray-50 p-1.5 rounded">
              <span class="flex items-center gap-1">
                <CheckCircle2 v-if="step.success" class="w-3 h-3 text-green-500" />
                <XCircle v-else class="w-3 h-3 text-red-500" />
                阶段 {{ idx + 1 }}: {{ step.timestamp }}
              </span>
              <span class="flex gap-2">
                <span v-if="step.duration_ms"><Clock class="w-3 h-3 inline"/> {{ (step.duration_ms / 1000).toFixed(1) }}s</span>
                <span v-if="step.cost_usd"><DollarSign class="w-3 h-3 inline"/> ${{ step.cost_usd.toFixed(4) }}</span>
              </span>
            </div>
          </div>
        </div>

        <!-- HITL 交互卡片 -->
        <div v-for="card in activeHitlCards" :key="card.id" class="pinned-card hitl-card">
          <div class="card-header hitl-header">
            <AlertCircle class="w-5 h-5 text-amber" />
            <h4>需要人工确认</h4>
          </div>
          <div class="card-body">
            <p class="hitl-prompt">{{ card.prompt }}</p>
            <div v-if="card.context" class="context-box">
              <code>{{ card.context }}</code>
            </div>
          </div>
          <div class="hitl-actions">
            <template v-if="card.hitl_type === 'boolean'">
              <button class="btn-success" @click="submitHitl(card.id, 'y')">确认 (Y)</button>
              <button class="btn-danger" @click="submitHitl(card.id, 'n')">拒绝 (N)</button>
            </template>
            <template v-else>
              <input
                type="text"
                v-model="card.tempInput"
                placeholder="输入回复…"
                class="input-field hitl-input"
                @keyup.enter="submitHitl(card.id, card.tempInput)"
              >
              <button class="btn-primary" @click="submitHitl(card.id, card.tempInput)">提交</button>
            </template>
          </div>
        </div>
      </div>

      <!-- ★ 对话气泡区 (仅自然语言) -->
      <div class="chat-history" ref="chatContainer">
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="message-wrapper"
          :class="`role-${msg.role}`"
        >
          <div class="message-bubble glass-panel">
            <div class="msg-content">{{ msg.content }}</div>
          </div>
        </div>

        <div v-if="messages.length === 0" class="chat-empty-hint">
          <p>发送消息开始对话，或点击 <strong>Start Engine</strong> 启动 SDD 流程</p>
        </div>
      </div>

      <!-- Verification Quick Actions -->
      <div v-if="!engineRunning && messages.length > 0" class="verification-actions">
        <span class="verify-label">高阶测试:</span>
        <button class="btn-micro" @click="sendVerification('ui')" title="Playwright UI">
          <TestTube class="w-3" /> UI
        </button>
        <button class="btn-micro" @click="sendVerification('api')" title="Postman API">
          <Database class="w-3" /> API
        </button>
        <button class="btn-micro" @click="sendVerification('e2e')" title="全链路集成">
          <Sparkles class="w-3" /> E2E
        </button>
      </div>

      <!-- Input Area -->
      <div class="chat-input-area glass-panel">
        <input
          v-model="chatInput"
          type="text"
          placeholder="输入消息…"
          @keyup.enter="sendChat"
          class="chat-input"
        >
        <button class="send-btn" :disabled="!chatInput.trim()" @click="sendChat">
          <Send class="w-5 h-5" />
        </button>
      </div>
    </section>

    <!-- Empty State -->
    <section class="chat-main empty-state" v-else>
      <Loader2 class="w-8 h-8 spin text-primary-light" />
      <p class="empty-text">选择一个任务查看会话</p>
    </section>

    <!-- Right: Terminal Panel -->
    <aside class="terminal-sidebar glass-panel" :class="{ 'is-open': showTerminal }">
      <div class="terminal-header">
        <TerminalSquare class="w-4 h-4" />
        <span>Agent Activity</span>
      </div>
      <div class="terminal-body" ref="terminalContainer">
        <template v-for="(entry, idx) in terminalLogs" :key="idx">
          <!-- Tool Use -->
          <div v-if="entry.type === 'tool_use'" class="term-entry tool-use-entry">
            <div class="term-entry-header">
              <Wrench class="w-3 h-3" />
              <span class="tool-name">{{ entry.tool_name }}</span>
              <span class="term-time">{{ entry.timestamp }}</span>
            </div>
            <pre v-if="entry.tool_input" class="term-detail">{{ formatToolInput(entry.tool_input) }}</pre>
          </div>

          <!-- Tool Result -->
          <div v-else-if="entry.type === 'tool_result'" class="term-entry tool-result-entry"
               :class="{ 'is-error': entry.is_error }">
            <pre class="term-output">{{ entry.output }}</pre>
          </div>

          <!-- Raw Log -->
          <div v-else class="term-entry log-entry">
            <pre class="terminal-line">{{ entry.content }}</pre>
          </div>
        </template>

        <div v-if="terminalLogs.length === 0" class="term-empty">Waiting for activity…</div>
      </div>
    </aside>

    <!-- ─── Modals ─── -->
    <!-- New Task Modal -->
    <div v-if="showTaskModal" class="modal-overlay" @click.self="showTaskModal = false">
      <div class="modal glass-panel">
        <div class="modal-header">
          <Plus class="w-6 h-6 text-primary" />
          <h2>新建任务</h2>
        </div>
        <form @submit.prevent="handleCreateTask" class="modal-form">
          <div class="form-group">
            <label>任务名称</label>
            <input v-model="newTaskName" type="text" class="input-field" required placeholder="e.g. Implement User Profile API">
          </div>
          <div class="form-group">
            <label>描述 (作为初始 Prompt)</label>
            <textarea v-model="newTaskDesc" class="input-field" rows="3" placeholder="描述任务目标，这将作为 Claude CLI 的初始提示词…"></textarea>
          </div>
          <div class="form-group">
            <label>规范文档 (可选)</label>
            <div class="file-upload-box glass-panel">
              <Upload class="w-5 h-5 text-primary" v-if="!uploadingSpec" />
              <Loader2 class="w-5 h-5 spin text-primary" v-else />
              <div class="file-name">{{ selectedFileName || 'Upload Requirement Doc…' }}</div>
              <input type="file" @change="handleFileUpload" class="hidden-input" id="spec-upload-chat" accept=".pdf,.doc,.docx,.md,.txt">
              <label for="spec-upload-chat" class="btn-primary file-choose-btn">选择</label>
            </div>
          </div>
          <div class="form-group checkbox-group py-1">
            <label class="flex items-center gap-2 cursor-pointer text-sm text-slate-700 select-none">
              <input v-model="useBrainstorm" type="checkbox" class="w-4 h-4 accent-primary-600 rounded">
              使用 /brainstorm 进行初期需求与架构头脑风暴
            </label>
          </div>
          <div class="modal-actions">
            <button type="button" class="btn-secondary" @click="showTaskModal = false">取消</button>
            <button type="submit" class="btn-primary" :disabled="creatingTask">
              {{ creatingTask ? '创建中…' : '初始化' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Interrupt Confirmation Modal -->
    <div v-if="showInterruptConfirm" class="modal-overlay" @click.self="showInterruptConfirm = false">
      <div class="modal glass-panel delete-modal">
        <div class="modal-header danger">
          <OctagonPause class="w-6 h-6" />
          <span>中断任务确认</span>
        </div>
        <p class="delete-desc">
          确定要强制中断当前正在运行的 Claude CLI 引擎吗？
          中断后当前执行的原子动作可能无法回滚。
        </p>
        <div class="modal-actions">
          <button class="btn-secondary" @click="showInterruptConfirm = false">继续执行</button>
          <button class="btn-danger" @click="confirmInterrupt">立即中断</button>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div v-if="showDeleteTaskConfirm" class="modal-overlay" @click.self="showDeleteTaskConfirm = false">
      <div class="modal glass-panel delete-modal">
        <div class="modal-header danger">
          <AlertTriangle class="w-6 h-6" />
          <span>删除任务？</span>
        </div>
        <p class="delete-desc">
          确定删除会话 <strong>{{ taskToDelete?.name }}</strong>？
          所有历史记录和过程资产将被清除，此操作不可逆。
        </p>
        <div class="modal-actions">
          <button class="btn-secondary" @click="showDeleteTaskConfirm = false">保留</button>
          <button class="btn-danger" @click="confirmDeleteTask">永久删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ─── Layout ─── */
.chat-layout {
  display: flex;
  height: 100%;
  width: 100%;
  overflow: hidden;
  position: relative;
}

/* ─── Utilities ─── */
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.spin { animation: spin 1s linear infinite; }
.text-primary { color: var(--color-primary-600); }
.text-primary-light { color: var(--color-primary-100); }
.text-success { color: var(--color-accent-emerald); }
.text-error { color: var(--color-accent-rose); }
.text-amber { color: var(--color-accent-amber); }
.w-3 { width: 12px; height: 12px; }
.w-4 { width: 16px; height: 16px; }
.w-5 { width: 20px; height: 20px; }
.w-6 { width: 24px; height: 24px; }
.w-8 { width: 32px; height: 32px; }
.h-3 { width: 12px; height: 12px; }
.h-4 { width: 16px; height: 16px; }
.h-5 { width: 20px; height: 20px; }
.h-6 { width: 24px; height: 24px; }
.h-8 { width: 32px; height: 32px; }

/* ─── Sidebar ─── */
.task-sidebar {
  width: 250px;
  border-radius: 0;
  border: none;
  border-right: 1px solid rgba(0,0,0,0.05);
  display: flex;
  flex-direction: column;
  background-color: var(--color-surface-white);
  z-index: 5;
}

.sidebar-header {
  padding: var(--space-4);
  border-bottom: 1px solid rgba(0,0,0,0.05);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.sidebar-header h3 {
  margin: 0;
  font-weight: 600;
  color: var(--color-primary-900);
}

.task-list { flex: 1; overflow-y: auto; padding: var(--space-2); }

.task-item {
  padding: var(--space-3);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-1);
  cursor: pointer;
  transition: all var(--transition-fast);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.task-item:hover { background-color: var(--color-primary-50); }
.task-item.active {
  background-color: var(--color-primary-100);
  border-left: 3px solid var(--color-primary-500);
}
.task-item-content { flex: 1; min-width: 0; }

.task-name {
  font-weight: 500;
  color: var(--color-text-body);
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-item.active .task-name { color: var(--color-primary-900); font-weight: 600; }

.task-status {
  font-size: 0.75rem;
  color: var(--color-text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background-color: var(--color-text-muted);
}
.status-dot.coding, .status-dot.running { background-color: var(--color-primary-500); }
.status-dot.pending { background-color: var(--color-accent-amber); }
.status-dot.done { background-color: var(--color-accent-emerald); }
.status-dot.failed { background-color: var(--color-accent-rose); }

.delete-btn {
  opacity: 0;
  transition: opacity 0.2s;
  color: var(--color-text-muted);
}
.delete-btn:hover { color: var(--color-accent-rose); }
.group:hover .delete-btn { opacity: 1; }

.empty-hint {
  padding: var(--space-4);
  font-size: 0.875rem;
  color: var(--color-text-muted);
  text-align: center;
}

/* ─── Chat Main ─── */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
}
.chat-main.empty-state {
  justify-content: center;
  align-items: center;
}
.empty-text {
  margin-top: var(--space-4);
  color: var(--color-text-muted);
}

/* ─── Header ─── */
.chat-header {
  height: 60px;
  padding: 0 var(--space-6);
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-radius: 0;
  border: none;
  border-bottom: 1px solid rgba(0,0,0,0.05);
  background-color: rgba(255,255,255,0.8);
  backdrop-filter: blur(12px);
  z-index: 10;
  flex-shrink: 0;
}
.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.header-left h2 { margin: 0; font-size: 1.125rem; }

.badge {
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 12px;
  background-color: #E2E8F0;
  color: #475569;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.badge.coding, .badge.running { background-color: #DBEAFE; color: #1E40AF; }
.badge.done { background-color: #D1FAE5; color: #065F46; }
.badge.failed { background-color: #FEE2E2; color: #991B1B; }

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.action-divider {
  width: 1px;
  height: 20px;
  background: rgba(0,0,0,0.1);
  margin: 0 var(--space-1);
}

.icon-btn {
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 6px;
  border-radius: var(--radius-md);
  transition: all 0.2s;
  display: flex;
  align-items: center;
}
.icon-btn:hover { background-color: rgba(0,0,0,0.05); }
.icon-btn.active { color: var(--color-primary-600); background-color: var(--color-primary-50); }
.icon-btn.danger { color: var(--color-accent-rose); }
.icon-btn.danger:hover { background-color: rgba(239,68,68,0.05); }

.start-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  font-size: 0.875rem;
}

/* ─── ★ 置顶富文本卡片区 ─── */
.pinned-cards-area {
  padding: var(--space-3) var(--space-6);
  border-bottom: 1px solid rgba(0,0,0,0.05);
  background: linear-gradient(to bottom, rgba(248,250,252,0.95), rgba(248,250,252,0.8));
  backdrop-filter: blur(8px);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  flex-shrink: 0;
  max-height: 300px;
  overflow-y: auto;
}

.pinned-card {
  border-radius: var(--radius-md);
  padding: var(--space-3);
  box-shadow: var(--shadow-sm);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--color-text-body);
}
.card-meta {
  display: flex;
  gap: var(--space-4);
  margin-top: 6px;
  font-size: 0.75rem;
  color: var(--color-text-muted);
}
.card-meta span {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* Thinking Card */
.thinking-card {
  background: #F1F5F9;
  border: 1px solid #E2E8F0;
}
.thinking-body.fixed-height {
  max-height: 200px;
  overflow-y: auto;
}
.thinking-body pre {
  margin: 8px 0 0;
  font-family: var(--font-mono);
  font-size: 0.8rem;
  color: #64748B;
  white-space: pre-wrap;
  word-wrap: break-word;
}

/* Status Card */
.status-card {
  background: white;
  border: 1px solid #DBEAFE;
  border-left: 3px solid var(--color-primary-500);
}
.status-card.is-error {
  border-color: #FEE2E2;
  border-left-color: var(--color-accent-rose);
}

/* HITL Card */
.hitl-card {
  background: white;
  border: 1px solid #FCD34D;
  border-left: 4px solid #F59E0B;
}
.hitl-header h4 { margin: 0; font-size: 0.95rem; color: #92400E; }
.hitl-prompt { font-weight: 500; margin: 8px 0; font-size: 0.9rem; }
.context-box {
  background: #F1F5F9;
  padding: 8px;
  border-radius: 4px;
  font-size: 0.85rem;
  margin-bottom: 8px;
}
.hitl-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.hitl-input {
  flex: 1;
  font-size: 0.875rem;
  padding: 6px 12px;
}

.card-body { margin-top: 4px; }

/* ─── Chat History ─── */
.chat-history {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.chat-empty-hint {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
  font-size: 0.9rem;
}

.message-wrapper { display: flex; max-width: 80%; }
.role-user { align-self: flex-end; }
.role-system { align-self: flex-start; }
.role-assistant { align-self: flex-start; }

.message-bubble {
  padding: 12px 16px;
  border-radius: var(--radius-lg);
  font-size: 0.95rem;
  line-height: 1.6;
  box-shadow: var(--shadow-sm);
}
.role-user .message-bubble {
  background-color: var(--color-primary-600);
  color: white;
  border-bottom-right-radius: 4px;
}
.role-system .message-bubble,
.role-assistant .message-bubble {
  background-color: white;
  border: 1px solid #E2E8F0;
  border-bottom-left-radius: 4px;
}
.msg-content { white-space: pre-wrap; word-wrap: break-word; }

/* ─── Input Area ─── */
.chat-input-area {
  margin: var(--space-4) var(--space-6);
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  background-color: white;
  border-radius: 24px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.05);
  flex-shrink: 0;
}
.chat-input {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 1rem;
  padding: 8px 0;
  outline: none;
}
.send-btn {
  background: var(--color-primary-600);
  color: white;
  border: none;
  width: 36px; height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: transform 0.2s;
}
.send-btn:disabled { background: #CBD5E1; cursor: not-allowed; }
.send-btn:hover:not(:disabled) { transform: scale(1.05); }

/* ─── Terminal Sidebar ─── */
.terminal-sidebar {
  width: 0;
  opacity: 0;
  border-radius: 0;
  border: none;
  background-color: #0F172A;
  color: #E2E8F0;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: -4px 0 15px rgba(0,0,0,0.1);
  z-index: 20;
}
.terminal-sidebar.is-open { width: 420px; opacity: 1; }

.terminal-header {
  padding: 12px 16px;
  background-color: #1E293B;
  font-size: 0.85rem;
  font-weight: 600;
  color: #94A3B8;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid #334155;
  flex-shrink: 0;
}
.terminal-body {
  flex: 1;
  padding: 12px;
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: 0.8rem;
}
.terminal-body::-webkit-scrollbar { width: 6px; }
.terminal-body::-webkit-scrollbar-track { background: #0F172A; }
.terminal-body::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }

.term-entry {
  margin-bottom: 8px;
  padding: 6px 8px;
  border-radius: 4px;
}
.term-entry-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.tool-name {
  color: #60A5FA;
  font-weight: 600;
}
.term-time {
  margin-left: auto;
  color: #64748B;
  font-size: 0.7rem;
}
.term-detail {
  margin: 4px 0 0;
  color: #94A3B8;
  white-space: pre-wrap;
  word-wrap: break-word;
  max-height: 120px;
  overflow-y: auto;
}
.tool-use-entry { background: rgba(96, 165, 250, 0.08); }
.tool-result-entry { background: rgba(52, 211, 153, 0.08); }
.tool-result-entry.is-error { background: rgba(248, 113, 113, 0.08); }
.term-output {
  margin: 0;
  color: #A5B4FC;
  white-space: pre-wrap;
  word-wrap: break-word;
  max-height: 200px;
  overflow-y: auto;
}
.log-entry { background: transparent; }
.terminal-line {
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
  color: #A5B4FC;
  line-height: 1.4;
}
.term-empty {
  font-size: 0.75rem;
  color: #64748B;
  font-style: italic;
  margin-top: var(--space-2);
}

/* ─── Modals ─── */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.modal {
  width: 90%;
  max-width: 500px;
  padding: var(--space-8);
  background-color: white;
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-2xl);
}
.modal-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.modal-header h2 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 700;
}
.modal-header.danger {
  color: var(--color-accent-rose);
}
.modal-header.danger span {
  font-size: 1.2rem;
  font-weight: 700;
}

.modal-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-group label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #475569;
}

.input-field {
  padding: 10px 14px;
  border: 1px solid #E2E8F0;
  border-radius: var(--radius-md);
  font-family: inherit;
  font-size: 1rem;
  width: 100%;
  box-sizing: border-box;
}
.input-field:focus { border-color: var(--color-primary-500); outline: none; }

.file-upload-box {
  border: 1px dashed var(--color-primary-100);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  margin-top: 4px;
}
.file-upload-box:hover { border-style: solid; border-color: var(--color-primary-500); }
.file-name {
  flex: 1;
  font-size: 0.875rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.file-choose-btn { padding: 4px 12px; font-size: 0.75rem; cursor: pointer; }
.hidden-input { display: none; }

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.delete-modal { border-top: 4px solid var(--color-accent-rose); }
.delete-desc {
  font-size: 0.875rem;
  color: #475569;
  margin-bottom: var(--space-4);
}

/* ─── Buttons ─── */
.btn-primary {
  background: var(--color-primary-600);
  color: white;
  border: 1px solid var(--color-primary-700);
  padding: 8px 18px;
  border-radius: var(--radius-md);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-primary:hover { box-shadow: 0 2px 8px rgba(30,64,175,0.3); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-secondary {
  background: white;
  color: #475569;
  border: 1px solid #E2E8F0;
  padding: 8px 18px;
  border-radius: var(--radius-md);
  font-weight: 500;
  cursor: pointer;
}

.btn-micro {
  background: white;
  color: #475569;
  border: 1px solid #E2E8F0;
  padding: 4px 10px;
  border-radius: var(--radius-md);
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}
.btn-micro:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  border-color: var(--color-primary-200);
}

.verification-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 24px;
  background-color: #F8FAFC;
  border-top: 1px solid #F1F5F9;
}
.verify-label {
  font-size: 0.75rem;
  color: #94A3B8;
  margin-right: 4px;
}

.btn-success {
  background: #10B981;
  color: white;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
}

.btn-danger {
  background: #EF4444;
  color: white;
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
}
</style>
