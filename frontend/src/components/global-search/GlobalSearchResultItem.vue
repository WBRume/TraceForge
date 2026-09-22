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
import UserAvatar from '@/components/user/UserAvatar.vue'
import type { SearchItem } from '@/types/search'
import { formatTime } from '@/utils/chatFormatters'

const props = defineProps<{ item: SearchItem; active: boolean }>()
const emit = defineEmits<{ select: [] }>()

const pinnedStore = usePinnedFloatsStore()
const isPinned = computed(() => pinnedStore.isPinned(props.item.entity_key))
const copied = ref(false)
const createdTime = computed(() => {
  const value = props.item.created_at
  return value && !Number.isNaN(Date.parse(value)) ? formatTime(value) : ''
})
const timeLabel = computed(() => props.item.kind === 'message' ? '发送于' : '创建于')

// 用户发言：展示真实用户头像与用户名（与聊天消息一致的身份标识）
const isUserMessage = computed(() => props.item.kind === 'message' && props.item.role === 'user')
const hasCreatorIdentity = computed(() =>
  Boolean(props.item.creator_avatar_svg || props.item.creator_avatar_url || props.item.creator_display_name)
)

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
    <!-- 头部信息行：方案 D3 极简微圆点纯排版设计，无廉价堆叠 icon -->
    <div class="result-header">
      <div class="header-badges">
        <!-- 用户发言：真实用户头像（与聊天气泡一致）；其余类型保留 6px 实体微圆点 -->
        <UserAvatar
          v-if="isUserMessage && hasCreatorIdentity"
          class="type-avatar"
          :display-name="item.creator_display_name"
          :user-id="item.creator_id"
          :avatar-svg="item.creator_avatar_svg"
          :avatar-url="item.creator_avatar_url"
          size="xs"
        />
        <span
          v-else
          class="type-dot"
          :class="{
            'dot-task': item.kind === 'task',
            'dot-user': item.kind === 'message' && item.role === 'user',
            'dot-assistant': item.kind === 'message' && item.role !== 'user',
          }"
        />

        <!-- 类型文字标签 -->
        <span class="type-label">
          {{ item.kind === 'task' ? '任务' : item.kind === 'case' ? '案例' : item.kind === 'playbook' ? '诊断规程' : (item.role === 'user' ? '用户发言' : 'AI 回复') }}
        </span>

        <!-- 具体用户名 -->
        <template v-if="isUserMessage && item.creator_display_name">
          <span class="dot-sep">·</span>
          <span class="creator-name" :title="item.creator_display_name">{{ item.creator_display_name }}</span>
        </template>

        <span class="dot-sep">·</span>

        <!-- 所属工作区与任务路径：层次分明 -->
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
          v-if="item.kind === 'task' || item.kind === 'message'"
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

    <div class="result-footer">
      <time v-if="createdTime" class="result-time" :datetime="item.created_at" :title="`${timeLabel} ${createdTime}`">
        {{ timeLabel }} {{ createdTime }}
      </time>
      <span v-else class="result-time">时间未知</span>
      <span v-if="item.snippet_basis === 'semantic'" class="semantic-hint">语义匹配</span>
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
  gap: 6px;
  min-width: 0;
  flex: 1;
}

/* 方案 D3：极简微圆点指示器 */
.type-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* 用户发言真实头像（与聊天消息同款 UserAvatar） */
.type-avatar.user-avatar {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.type-dot.dot-task {
  background-color: #0ea5e9;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.15);
}

.type-dot.dot-user {
  background-color: #f59e0b;
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.15);
}

.type-dot.dot-assistant {
  background-color: #8b5cf6;
  box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.15);
}

/* 类型纯文字标签 */
.type-label {
  font-size: 11.5px;
  font-weight: 600;
  color: #334155;
  flex-shrink: 0;
  line-height: 1;
}

/* 具体用户名：沿用用户发言的琥珀色身份色 */
.creator-name {
  font-size: 11.5px;
  font-weight: 700;
  color: #b45309;
  flex-shrink: 0;
  line-height: 1;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dot-sep {
  color: #cbd5e1;
  font-size: 11px;
  user-select: none;
}

.result-path {
  font-size: 12px;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: flex;
  align-items: center;
}

.ws-name {
  color: #475569;
  font-weight: 500;
  background: #f8fafc;
  padding: 1px 4px;
  border-radius: 3px;
  border: 1px solid #f1f5f9;
}

.path-sep {
  margin: 0 4px;
  color: #cbd5e1;
}

.tk-name {
  font-weight: 600;
  color: #0f172a;
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
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
  margin-top: 2px;
}

.result-time {
  font-size: 11px;
  color: #64748b;
  font-variant-numeric: tabular-nums;
}

.semantic-hint {
  font-size: 10.5px;
  color: #b45309;
}
</style>
