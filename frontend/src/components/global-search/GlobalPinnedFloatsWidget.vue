<script setup lang="ts">
import { ref } from 'vue'
import {
  X,
  Minus,
  Copy,
  Check,
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { usePinnedFloatsStore, type PinnedSearchItem } from '@/stores/pinnedFloats'
import SessionContextPanel from './SessionContextPanel.vue'

const store = usePinnedFloatsStore()

// 复制状态记录：itemId -> boolean (短期显示对勾)
const copiedMap = ref<Record<string, boolean>>({})

const copyText = async (item: PinnedSearchItem) => {
  const text = item.snippetText || ''
  if (!text) {
    ElMessage.warning('暂无消息文本可复制')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    copiedMap.value[item.id] = true
    ElMessage.success('消息内容已复制到剪贴板')
    setTimeout(() => {
      copiedMap.value[item.id] = false
    }, 2000)
  } catch {
    ElMessage.error('复制失败，请手动选择复制')
  }
}

// ---------------- 展开面板：全局拖动 ----------------
let dragActive = false
let dragItem: PinnedSearchItem | null = null
let dragStartX = 0
let dragStartY = 0
let dragOrigX = 0
let dragOrigY = 0

const onPanelHeaderPointerDown = (e: PointerEvent, item: PinnedSearchItem) => {
  // 仅主按键拖拽，且不响应按钮点击
  if (e.button !== 0) return
  if ((e.target as HTMLElement).closest('button')) return

  dragActive = true
  dragItem = item
  dragStartX = e.clientX
  dragStartY = e.clientY
  dragOrigX = item.position.x
  dragOrigY = item.position.y

  ;(e.currentTarget as HTMLElement)?.setPointerCapture?.(e.pointerId)
  window.addEventListener('pointermove', onPanelHeaderPointerMove)
  window.addEventListener('pointerup', onPanelHeaderPointerUp)
}

const onPanelHeaderPointerMove = (e: PointerEvent) => {
  if (!dragActive || !dragItem) return
  const deltaX = e.clientX - dragStartX
  const deltaY = e.clientY - dragStartY

  const panelWidth = dragItem.size.width
  const panelHeight = dragItem.size.height
  const maxW = Math.max(10, window.innerWidth - panelWidth - 10)
  const maxH = Math.max(10, window.innerHeight - panelHeight - 10)

  const newX = Math.max(10, Math.min(maxW, dragOrigX + deltaX))
  const newY = Math.max(10, Math.min(maxH, dragOrigY + deltaY))

  store.updatePosition(dragItem.id, { x: newX, y: newY })
}

const onPanelHeaderPointerUp = () => {
  dragActive = false
  dragItem = null
  window.removeEventListener('pointermove', onPanelHeaderPointerMove)
  window.removeEventListener('pointerup', onPanelHeaderPointerUp)
}

// ---------------- 展开面板：右侧及右下角拖拽缩放 ----------------
let resizeActive = false
let resizeItem: PinnedSearchItem | null = null
let resizeMode: 'right' | 'corner' = 'right'
let resizeStartX = 0
let resizeStartY = 0
let resizeStartW = 0
let resizeStartH = 0

const onResizePointerDown = (e: PointerEvent, item: PinnedSearchItem, mode: 'right' | 'corner') => {
  if (e.button !== 0) return
  e.stopPropagation()
  e.preventDefault()

  resizeActive = true
  resizeItem = item
  resizeMode = mode
  resizeStartX = e.clientX
  resizeStartY = e.clientY
  resizeStartW = item.size.width
  resizeStartH = item.size.height

  ;(e.currentTarget as HTMLElement)?.setPointerCapture?.(e.pointerId)
  window.addEventListener('pointermove', onResizePointerMove)
  window.addEventListener('pointerup', onResizePointerUp)
}

const onResizePointerMove = (e: PointerEvent) => {
  if (!resizeActive || !resizeItem) return
  const deltaX = e.clientX - resizeStartX
  const deltaY = e.clientY - resizeStartY

  const maxWidth = Math.max(320, window.innerWidth - resizeItem.position.x - 10)
  const maxHeight = Math.max(200, window.innerHeight - resizeItem.position.y - 10)

  const newWidth = Math.max(300, Math.min(maxWidth, resizeStartW + deltaX))
  const newHeight = resizeMode === 'corner'
    ? Math.max(200, Math.min(maxHeight, resizeStartH + deltaY))
    : resizeStartH

  store.updateSize(resizeItem.id, { width: newWidth, height: newHeight })
}

const onResizePointerUp = () => {
  resizeActive = false
  resizeItem = null
  window.removeEventListener('pointermove', onResizePointerMove)
  window.removeEventListener('pointerup', onResizePointerUp)
}

// ---------------- 最小化胶囊（Pill）：右侧边缘贴边上下拖拽 ----------------
let pillDragActive = false
let pillItem: PinnedSearchItem | null = null
let pillStartY = 0
let pillStartTop = 0
let pillMovedDistance = 0

const onPillPointerDown = (e: PointerEvent, item: PinnedSearchItem) => {
  if (e.button !== 0) return
  pillDragActive = true
  pillItem = item
  pillStartY = e.clientY
  pillStartTop = item.dockTop || 180
  pillMovedDistance = 0

  ;(e.currentTarget as HTMLElement)?.setPointerCapture?.(e.pointerId)
  window.addEventListener('pointermove', onPillPointerMove)
  window.addEventListener('pointerup', onPillPointerUp)
}

const onPillPointerMove = (e: PointerEvent) => {
  if (!pillDragActive || !pillItem) return
  const deltaY = e.clientY - pillStartY
  pillMovedDistance += Math.abs(e.movementY || deltaY)

  const maxTop = Math.max(60, window.innerHeight - 70)
  const newTop = Math.max(60, Math.min(maxTop, pillStartTop + deltaY))

  store.updateDockTop(pillItem.id, newTop)
}

const onPillPointerUp = () => {
  if (pillDragActive && pillItem) {
    // 若移动位移极小（<= 4px），视为单纯轻点，触发展开浮窗
    if (pillMovedDistance <= 4) {
      store.setMinimized(pillItem.id, false)
    }
  }
  pillDragActive = false
  pillItem = null
  window.removeEventListener('pointermove', onPillPointerMove)
  window.removeEventListener('pointerup', onPillPointerUp)
}
</script>

<template>
  <div class="pinned-floats-container">
    <!-- 遍历所有钉在窗口中的浮窗 -->
    <template v-for="item in store.items" :key="item.id">
      <!-- 1. 展开状态：全局自由拖动面板，支持右侧及角落缩放 -->
      <div
        v-if="!item.minimized"
        class="pinned-panel"
        :style="{
          left: `${item.position.x}px`,
          top: `${item.position.y}px`,
          width: `${item.size.width}px`,
          height: `${item.size.height}px`,
        }"
      >
        <!-- 头部 Header：拖拽把手区 -->
        <header
          class="panel-header"
          @pointerdown="onPanelHeaderPointerDown($event, item)"
        >
          <div class="header-left">
            <span
              class="panel-badge"
              :class="{
                'badge-task': item.kind === 'task',
                'badge-user': item.kind === 'message' && item.role === 'user',
                'badge-assistant': item.kind === 'message' && item.role !== 'user',
              }"
            >
              {{ item.kind === 'task' ? '会话' : (item.role === 'user' ? '用户发言' : 'AI 回复') }}
            </span>
            <span v-if="item.workspaceName" class="panel-ws-badge" :title="`工作区: ${item.workspaceName}`">
              {{ item.workspaceName }}
            </span>
            <span class="panel-title" :title="item.taskName || item.workspaceName">
              {{ item.taskName || item.workspaceName }}
            </span>
          </div>

          <div class="header-actions">
            <!-- 消息类型特有：一键复制 -->
            <button
              v-if="item.kind === 'message'"
              type="button"
              class="action-icon-btn"
              :title="copiedMap[item.id] ? '已复制' : '复制消息内容'"
              @click.stop="copyText(item)"
            >
              <Check v-if="copiedMap[item.id]" class="w-3.5 h-3.5 text-emerald-500" />
              <Copy v-else class="w-3.5 h-3.5" />
            </button>

            <!-- 最小化按钮 -->
            <button
              type="button"
              class="action-icon-btn"
              title="最小化到右侧"
              @click.stop="store.setMinimized(item.id, true)"
            >
              <Minus class="w-3.5 h-3.5" />
            </button>

            <!-- 关闭按钮 -->
            <button
              type="button"
              class="action-icon-btn is-close"
              title="关闭并取消固定"
              @click.stop="store.unpin(item.id)"
            >
              <X class="w-3.5 h-3.5" />
            </button>
          </div>
        </header>

        <!-- 主体区域：会话简易上下文面板 或 消息卡片 -->
        <main class="panel-body">
          <!-- 会话：只读可滚动简易上下文面板 -->
          <SessionContextPanel
            v-if="item.kind === 'task'"
            :workspace-id="item.workspaceId"
            :task-id="item.taskId"
            :task-name="item.taskName"
          />

          <!-- 消息：纯消息卡片（纯文本，无彩色 icon） -->
          <div v-else class="message-float-content">
            <div class="msg-float-meta">
              <span class="msg-meta-role">
                {{ item.role === 'user' ? '用户发言' : 'AI 回复' }}
              </span>
              <span class="msg-meta-path">{{ item.workspaceName }} / {{ item.taskName }}</span>
            </div>
            <div class="msg-float-text">
              {{ item.snippetText }}
            </div>
          </div>
        </main>

        <!-- 缩放拉手：右侧边缘横向拉伸 -->
        <div
          class="resize-handle-right"
          @pointerdown="onResizePointerDown($event, item, 'right')"
        />

        <!-- 缩放拉手：右下角全向缩放 -->
        <div
          class="resize-handle-corner"
          @pointerdown="onResizePointerDown($event, item, 'corner')"
        />
      </div>

      <!-- 2. 最小化状态：方案 1.1 双行高辨识度微卡片胶囊，紧贴在屏幕右侧，支持沿右侧贴边上下拖拽 -->
      <div
        v-else
        class="right-docked-pill"
        :style="{ top: `${item.dockTop || 180}px` }"
        :title="`【${item.kind === 'task' ? '会话' : (item.role === 'user' ? '用户发言' : 'AI 回复')}】${item.workspaceName} / ${item.taskName}（按住上下拖拽，轻点展开）`"
        @pointerdown="onPillPointerDown($event, item)"
      >
        <div class="docked-pill-inner">
          <!-- 类别微标 -->
          <div
            class="pill-type-dot"
            :class="{
              'is-task': item.kind === 'task',
              'is-user': item.kind === 'message' && item.role === 'user',
              'is-assistant': item.kind === 'message' && item.role !== 'user',
            }"
          >
            {{ item.kind === 'task' ? '会' : (item.role === 'user' ? '言' : 'AI') }}
          </div>

          <!-- 双行文本：上行工作区，下行任务标题 -->
          <div class="pill-info">
            <span class="pill-ws-name" :title="item.workspaceName">{{ item.workspaceName }}</span>
            <span class="pill-task-title" :title="item.taskName">{{ item.taskName }}</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.pinned-floats-container {
  position: fixed;
  inset: 0;
  z-index: 3000;
  pointer-events: none; /* 让未覆盖区域透传事件 */
}

/* 展开浮窗面板：100% 纯白实心，绝不变透明 */
.pinned-panel {
  position: fixed;
  display: flex;
  flex-direction: column;
  pointer-events: auto;
  border-radius: 14px;
  background: #ffffff !important;
  background-color: #ffffff !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
  border: 1px solid #e2e8f0;
  box-shadow: 0 20px 35px -5px rgba(15, 23, 42, 0.16), 0 10px 15px -5px rgba(15, 23, 42, 0.08), 0 0 0 1px rgba(15, 23, 42, 0.05);
  overflow: hidden;
  user-select: none;
  transition: box-shadow 0.2s ease;
  z-index: 3000;
}

.pinned-panel:hover {
  background: #ffffff !important;
  background-color: #ffffff !important;
  box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.25), 0 0 0 1px rgba(14, 165, 233, 0.2);
}

/* 头部拖拽区 */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 12px;
  background: #ffffff !important;
  background-color: #ffffff !important;
  border-bottom: 1px solid #f1f5f9;
  cursor: grab;
  touch-action: none;
}

.panel-header:active {
  cursor: grabbing;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.panel-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #e2e8f0;
  line-height: 1.3;
}

.panel-badge.badge-task {
  background: #f0f9ff;
  color: #0284c7;
  border-color: #bae6fd;
}

.panel-badge.badge-user {
  background: #fffbeb;
  color: #b45309;
  border-color: #fde68a;
}

.panel-badge.badge-assistant {
  background: #faf5ff;
  color: #7e22ce;
  border-color: #e9d5ff;
}

.panel-ws-badge {
  display: inline-flex;
  align-items: center;
  padding: 1.5px 5px;
  border-radius: 4px;
  font-size: 10.5px;
  font-family: monospace;
  font-weight: 500;
  background: #f8fafc;
  color: #475569;
  border: 1px solid #e2e8f0;
  flex-shrink: 0;
  max-width: 90px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-title {
  font-size: 12.5px;
  font-weight: 600;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.action-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: #64748b;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.action-icon-btn:hover {
  background: rgba(148, 163, 184, 0.15);
  color: #0f172a;
}

.action-icon-btn.is-close:hover {
  background: rgba(244, 63, 94, 0.1);
  color: #e11d48;
}

/* 主体容器 */
.panel-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff !important;
  overflow: hidden;
}

/* 消息卡片主体 */
.message-float-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 12px;
  gap: 8px;
  min-height: 0;
  background: #ffffff !important;
}

.msg-float-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}

.msg-meta-role {
  display: inline-flex;
  align-items: center;
  font-weight: 600;
  color: #475569;
}

.msg-meta-path {
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 60%;
}

.msg-float-text {
  flex: 1;
  overflow-y: auto;
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
  background: #ffffff !important;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  white-space: pre-wrap;
  word-break: break-word;
  user-select: text;
}

/* 缩放手柄：右边缘 */
.resize-handle-right {
  position: absolute;
  top: 0;
  right: 0;
  width: 7px;
  height: 100%;
  cursor: ew-resize;
  z-index: 10;
  touch-action: none;
}

.resize-handle-right:hover {
  background: rgba(14, 165, 233, 0.2);
}

/* 缩放手柄：右下角 */
.resize-handle-corner {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 14px;
  height: 14px;
  cursor: nwse-resize;
  z-index: 11;
  touch-action: none;
}

.resize-handle-corner::after {
  content: '';
  position: absolute;
  right: 3px;
  bottom: 3px;
  width: 6px;
  height: 6px;
  border-right: 2px solid #94a3b8;
  border-bottom: 2px solid #94a3b8;
  opacity: 0.7;
}

/* ---------------- 最小化贴右悬浮徽章胶囊（Pill）- 方案 1.1 双行微卡片 ---------------- */
.right-docked-pill {
  position: fixed;
  right: 0; /* 紧贴右侧边缘 */
  pointer-events: auto;
  display: flex;
  align-items: center;
  height: 40px;
  max-width: 170px;
  border-radius: 20px 0 0 20px; /* 贴右半圆形态 */
  background: #ffffff !important;
  background-color: #ffffff !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
  border: 1px solid #e2e8f0;
  border-right: none;
  box-shadow: -4px 6px 16px rgba(15, 23, 42, 0.12), 0 0 0 1px rgba(15, 23, 42, 0.05);
  cursor: grab;
  touch-action: none;
  transition: transform 0.18s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.18s ease;
  user-select: none;
  z-index: 3000;
  padding: 3px 6px 3px 8px;
}

.right-docked-pill:active {
  cursor: grabbing;
}

.right-docked-pill:hover {
  transform: translateX(-4px);
  box-shadow: -6px 8px 22px rgba(15, 23, 42, 0.18);
  background: #ffffff !important;
  background-color: #ffffff !important;
}

.docked-pill-inner {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.pill-type-dot {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  flex-shrink: 0;
}

.pill-type-dot.is-task {
  background: #e0f2fe;
  color: #0284c7;
  border: 1px solid #bae6fd;
}

.pill-type-dot.is-user {
  background: #fef3c7;
  color: #b45309;
  border: 1px solid #fde68a;
}

.pill-type-dot.is-assistant {
  background: #f3e8ff;
  color: #7e22ce;
  border: 1px solid #e9d5ff;
}

.pill-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.15;
}

.pill-ws-name {
  font-size: 9.5px;
  font-family: monospace;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 105px;
}

.pill-task-title {
  font-size: 11px;
  font-weight: 600;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 105px;
}
</style>
