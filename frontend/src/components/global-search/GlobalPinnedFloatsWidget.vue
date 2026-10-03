<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { usePinnedFloatsStore, type PinnedSearchItem } from '@/stores/pinnedFloats'
import { useTaskAwarenessStore } from '@/stores/taskAwareness'
import { Loader2, TriangleAlert, Check, XCircle, OctagonPause, ExternalLink, Copy } from '@/components/icons'
import FloatingDockFrame from '@/components/floating/FloatingDockFrame.vue'
import UserAvatar from '@/components/user/UserAvatar.vue'
import SessionContextPanel from './SessionContextPanel.vue'

const store = usePinnedFloatsStore()
const awareness = useTaskAwarenessStore()
const router = useRouter()
const copied = ref('')
const label = (item: PinnedSearchItem) => item.kind === 'task' ? '会话' : item.role === 'user' ? '用户发言' : 'AI 回复'
const tone = (item: PinnedSearchItem) => ({ AI_RUNNING: 'is-running', AI_HITL_SUSPENDED: 'is-waiting', AI_RUN_FINISHED: 'is-finished', AI_RUN_ERROR: 'is-error', AI_RUN_INTERRUPTED: '', AI_RUN_STOPPED: '' })[item.runtimeState || 'AI_RUN_STOPPED'] || (item.kind === 'message' ? item.role === 'user' ? 'is-user' : 'is-assistant' : '')
const stateLabel = (item: PinnedSearchItem) => ({ AI_RUNNING: '后台执行中', AI_HITL_SUSPENDED: '等待人工确认', AI_RUN_FINISHED: '执行完成', AI_RUN_ERROR: '执行异常', AI_RUN_INTERRUPTED: '本轮执行已中断', AI_RUN_STOPPED: '' })[item.runtimeState || 'AI_RUN_STOPPED']
const close = (item: PinnedSearchItem) => { awareness.dismiss(item.runId); store.unpin(item.id) }
const open = (item: PinnedSearchItem) => { store.setMinimized(item.id, false); awareness.consume(item.runId) }
const minimize = (item: PinnedSearchItem) => {
  const run = awareness.runs[item.runId || '']
  if (item.source === 'automatic' && item.runtimeState === 'AI_RUN_FINISHED' && run?.consumed === run?.event.run.version) close(item)
  else store.setMinimized(item.id, true)
}
const jump = (item: PinnedSearchItem) => { void router.push({ name: 'taskChat', params: { wsId: item.workspaceId, taskId: item.taskId } }) }
const copy = async (item: PinnedSearchItem) => {
  try { await navigator.clipboard.writeText(item.snippetText); copied.value = item.id; setTimeout(() => { if (copied.value === item.id) copied.value = '' }, 1600) } catch { /* Optional clipboard permission. */ }
}
</script>

<template>
  <div class="pinned-floats-container">
    <TransitionGroup name="float">
      <FloatingDockFrame v-for="item in store.items" :key="item.id" :geometry="item" :title="`${item.workspaceName} / ${item.taskName}`" :tone="tone(item)"
        @position="store.updatePosition(item.id, $event)" @size="store.updateSize(item.id, $event)" @dock-top="store.updateDockTop(item.id, $event)"
        @open="open(item)" @minimize="minimize(item)" @close="close(item)">
        <template #header>
          <span class="panel-badge" :class="tone(item)">{{ label(item) }}</span>
          <span v-if="item.workspaceName" class="panel-ws-badge">{{ item.workspaceName }}</span>
          <span class="panel-title" :title="item.taskName">{{ item.taskName }}</span>
        </template>
        <template #pill>
          <div v-if="item.runtimeState && item.runtimeState !== 'AI_RUN_STOPPED'" class="pill-type-dot" :class="tone(item)" :title="stateLabel(item)">
            <Loader2 v-if="item.runtimeState === 'AI_RUNNING'" class="w-3.5 h-3.5 spin" />
            <TriangleAlert v-else-if="item.runtimeState === 'AI_HITL_SUSPENDED'" class="w-3.5 h-3.5 breathe" />
            <Check v-else-if="item.runtimeState === 'AI_RUN_FINISHED'" class="w-3.5 h-3.5" />
            <OctagonPause v-else-if="item.runtimeState === 'AI_RUN_INTERRUPTED'" class="w-3.5 h-3.5" />
            <XCircle v-else class="w-3.5 h-3.5" />
          </div>
          <UserAvatar v-else-if="item.kind === 'message' && item.role === 'user' && (item.creatorName || item.creatorAvatarUrl || item.creatorAvatarSvg)"
            class="pill-avatar" :display-name="item.creatorName" :avatar-svg="item.creatorAvatarSvg" :avatar-url="item.creatorAvatarUrl" size="xs" />
          <span v-else class="pill-type-dot" :class="tone(item)">{{ item.kind === 'task' ? '会' : item.role === 'user' ? '言' : 'AI' }}</span>
          <div class="pill-info"><span class="pill-ws-name">{{ item.workspaceName }}</span><span class="pill-task-title">{{ item.taskName }}</span></div>
        </template>
        <template #actions>
          <button v-if="item.kind === 'message'" type="button" class="action-icon-btn" :title="copied === item.id ? '已复制' : '复制消息内容'" @click.stop="copy(item)"><Check v-if="copied === item.id" class="w-3.5 h-3.5" /><Copy v-else class="w-3.5 h-3.5" /></button>
          <button type="button" class="action-icon-btn" title="跳转至完整任务页" aria-label="跳转至完整任务页" @click.stop="jump(item)"><ExternalLink class="w-3.5 h-3.5" /></button>
        </template>
        <div v-if="stateLabel(item)" class="runtime-notice" :class="tone(item)" role="status">{{ stateLabel(item) }}<span v-if="item.runtimeSummary"> · {{ item.runtimeSummary }}</span></div>
        <SessionContextPanel v-if="item.kind === 'task'" :workspace-id="item.workspaceId" :task-id="item.taskId" :task-name="item.taskName" />
        <div v-else class="message-float-content">
          <div class="msg-float-meta"><span class="msg-author"><UserAvatar v-if="item.role === 'user'" :display-name="item.creatorName" :avatar-svg="item.creatorAvatarSvg" :avatar-url="item.creatorAvatarUrl" size="xs" />{{ item.creatorName || label(item) }}</span><span>{{ item.workspaceName }} / {{ item.taskName }}</span></div>
          <div class="msg-float-text">{{ item.snippetText }}</div>
        </div>
      </FloatingDockFrame>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.pinned-floats-container { position: fixed; inset: 0; z-index: 3000; pointer-events: none; }
.panel-badge, .panel-ws-badge { display: inline-flex; padding: 2px 7px; border-radius: 6px; font-size: 10.5px; flex-shrink: 0; color: #0284c7; background: #f0f9ff; border: 1px solid #bae6fd; }
.panel-ws-badge { background: #f8fafc; color: #475569; border-color: #e2e8f0; max-width: 90px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.panel-title { font-size: 12.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pill-type-dot { width: 22px; height: 22px; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: #e0f2fe; color: #0284c7; font-size: 10px; font-weight: 700; flex-shrink: 0; }
.pill-avatar { width: 22px; height: 22px; flex-shrink: 0; }
.pill-info { display: flex; flex-direction: column; min-width: 0; line-height: 1.15; }
.pill-ws-name { font: 600 9.5px monospace; color: #64748b; }
.pill-task-title { font-size: 11px; font-weight: 600; color: #0f172a; }
.pill-ws-name, .pill-task-title { max-width: 112px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.is-waiting { color: #b45309; background: #fffbeb; }
.is-finished { color: #15803d; background: #f0fdf4; }
.is-error { color: #be123c; background: #fff1f2; }
.is-user { color: #d97706; background: #fffbeb; border-color: #fde68a; }
.is-assistant { color: #7c3aed; background: #faf5ff; border-color: #ddd6fe; }
.runtime-notice { padding: 7px 12px; font-size: 11px; max-height: 65px; overflow: auto; }
.action-icon-btn { border: none; background: transparent; color: #64748b; display: inline-flex; padding: 4px; border-radius: 6px; cursor: pointer; }
.action-icon-btn:hover { background: #f1f5f9; color: #0f172a; }
.message-float-content { flex: 1; min-height: 0; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.msg-float-meta { display: flex; justify-content: space-between; gap: 8px; font-size: 11px; color: #64748b; }
.msg-author { display: inline-flex; align-items: center; gap: 6px; }
.msg-float-text { flex: 1; overflow: auto; padding: 10px 12px; border: 1px solid #e2e8f0; border-radius: 8px; white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.6; user-select: text; }
.spin { animation: spin 2s linear infinite; }
.breathe { animation: breathe 1.8s ease-in-out infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes breathe { 50% { opacity: .45; } }
.float-enter-active, .float-leave-active { transition: opacity .25s ease, transform .25s ease; }
.float-enter-from, .float-leave-to { opacity: 0; transform: translateX(20px); }
@media (prefers-reduced-motion: reduce) { .spin, .breathe { animation: none; } .float-enter-active, .float-leave-active { transition: none; } }
</style>
