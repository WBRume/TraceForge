<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  Pin,
  PinOff,
  Copy,
  Check,
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { usePinnedFloatsStore } from '@/stores/pinnedFloats'
import type { SearchItem } from '@/types/search'

const props = defineProps<{ item: SearchItem; active: boolean }>()
const emit = defineEmits<{ select: [] }>()

const pinnedStore = usePinnedFloatsStore()
const isPinned = computed(() => pinnedStore.isPinned(props.item.entity_key))
const copied = ref(false)

const handleCopy = async (e: MouseEvent) => {
  e.stopPropagation()
  const text = props.item.snippet ? props.item.snippet.map((s) => s.text).join('') : ''
  if (!text) {
    ElMessage.warning('暂无内容可复制')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    ElMessage.success('消息内容已复制到剪贴板')
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    ElMessage.error('复制失败，请手动选择复制')
  }
}

const handleTogglePin = (e: MouseEvent) => {
  e.stopPropagation()
  pinnedStore.togglePin(props.item)
  if (pinnedStore.isPinned(props.item.entity_key)) {
    ElMessage.success(`已将${props.item.kind === 'task' ? '会话' : '消息'}固定为浮窗`)
  } else {
    ElMessage.info('已取消浮窗固定')
  }
}
</script>

<template>
  <div
    class="search-result-card"
    :class="{ active }"
    role="option"
    :aria-selected="active"
    tabindex="-1"
    @click="emit('select')"
  >
    <!-- 头部信息行：纯净文字标签（无彩色 icon）、路径与右侧操作按钮 -->
    <div class="result-header">
      <div class="header-badges">
        <!-- 纯文本微标签：去除所有彩色 icon，干净自然 -->
        <span v-if="item.kind === 'task'" class="item-tag">任务</span>
        <span v-else-if="item.role === 'user'" class="item-tag">用户消息</span>
        <span v-else class="item-tag">AI 消息</span>

        <!-- 所属工作区与任务路径 -->
        <span class="result-path" :title="`${item.workspace_name} / ${item.task_name}`">
          <span class="ws-name">{{ item.workspace_name }}</span>
          <span class="path-sep">/</span>
          <span class="tk-name">{{ item.task_name }}</span>
        </span>
      </div>

      <!-- 右侧快捷操作：复制与固定浮窗（固定浮窗使用钉子 Pin） -->
      <div class="result-actions" @click.stop>
        <!-- 消息专属：一键复制 -->
        <button
          v-if="item.kind === 'message'"
          type="button"
          class="item-action-btn"
          :class="{ 'is-success': copied }"
          :title="copied ? '已复制' : '复制消息内容'"
          @click="handleCopy"
        >
          <Check v-if="copied" class="w-3.5 h-3.5 text-emerald-600" />
          <Copy v-else class="w-3.5 h-3.5" />
        </button>

        <!-- 固定到窗口浮窗：使用钉子 icon -->
        <button
          type="button"
          class="item-action-btn"
          :class="{ 'is-pinned': isPinned }"
          :title="isPinned ? '取消固定浮窗' : '固定为窗口浮窗'"
          @click="handleTogglePin"
        >
          <PinOff v-if="isPinned" class="w-3.5 h-3.5 text-sky-600" />
          <Pin v-else class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- 匹配片段展示区：无颜色头，纯净排版 -->
    <div class="result-body">
      <template v-for="(segment, i) in item.snippet" :key="i">
        <mark v-if="segment.match" class="match-text">{{ segment.text }}</mark>
        <span v-else>{{ segment.text }}</span>
      </template>
    </div>

    <!-- 底部语义说明（纯文字无彩色 icon） -->
    <div v-if="item.snippet_basis === 'semantic'" class="result-footer">
      <span class="semantic-hint">语义匹配</span>
    </div>
  </div>
</template>

<style scoped>
/* 干净纯粹的卡片设计：无任何彩色边条或彩色头 */
.search-result-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  padding: 10px 14px;
  text-align: left;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  cursor: pointer;
  box-sizing: border-box;
  transition: all 0.18s ease;
  margin-bottom: 8px;
}

.search-result-card.active,
.search-result-card:hover {
  background: #f8fafc;
  border-color: #38bdf8;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
}

.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.header-badges {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

/* 纯文字微标签：无彩色 icon，极简清爽 */
.item-tag {
  display: inline-flex;
  align-items: center;
  padding: 1.5px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  flex-shrink: 0;
  background: #f1f5f9;
  color: #475569;
}

.result-path {
  font-size: 12px;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ws-name {
  color: #64748b;
}

.path-sep {
  margin: 0 4px;
  color: #cbd5e1;
}

.tk-name {
  font-weight: 600;
  color: #1e293b;
}

/* 操作按钮 */
.result-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.item-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s ease;
}

.item-action-btn:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
  color: #0ea5e9;
}

.item-action-btn.is-pinned {
  background: #f0f9ff;
  color: #0284c7;
  border-color: #bae6fd;
}

.item-action-btn.is-success {
  background: #dcfce7;
  color: #15803d;
  border-color: #bbf7d0;
}

/* 片段文本 */
.result-body {
  font-size: 12.5px;
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
  word-break: break-word;
}

.match-text {
  background: #fef08a;
  color: #713f12;
  padding: 0 2px;
  border-radius: 3px;
  font-weight: 600;
}

.result-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}

.semantic-hint {
  font-size: 10.5px;
  color: #b45309;
}
</style>
