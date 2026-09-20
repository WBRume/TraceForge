<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Loader2 } from 'lucide-vue-next'
import ChatMessageBubble from '@/components/chat/ChatMessageBubble.vue'
import ReadingResumeBanner from '@/components/chat/reading/ReadingResumeBanner.vue'
import type { Ref } from 'vue'
import type { ChatViewVm } from '@/composables/chat/useChatViewModel'

/**
 * 对话历史区：续读提示条、历史锚定提示条、分页加载、初始化分隔线与消息气泡列表。
 * 滚动容器 DOM 与滚动恢复逻辑归视图模型（useChatWorkbenchScroll/useChatHistory），
 * 经 containerRef 注入；消息级动作（撤销）冒泡给视图。
 */
const props = defineProps<{
  vm: ChatViewVm
  containerRef: Ref<HTMLElement | null>
}>()

const emit = defineEmits<{
  (event: 'undo-request', message: Record<string, any>): void
}>()

const { t } = useI18n()
</script>

<template>
  <div class="chat-history-panel-root">
    <ReadingResumeBanner
      v-if="props.vm.currentTask && !props.vm.historyAnchored && props.vm.showResumeBanner"
      :unread-count="props.vm.readingUnreadSnapshot"
      :sync-state="props.vm.readingSyncState"
      @resume="props.vm.resumeFromLastRead"
      @close="props.vm.closeResumeBanner"
      @return-latest="props.vm.returnToLatest"
    />
    <div v-if="props.vm.historyAnchored" class="history-context-bar" role="status">
      <span>{{ props.vm.historyHasNew ? '历史窗口 · 有新消息' : '正在查看历史消息' }}</span>
      <button @click="props.vm.returnToLatest">回到最新</button>
      <button v-if="props.vm.historyHasAfter" :disabled="props.vm.historyContextLoading" @click="props.vm.loadContextDirection('after')">加载后续消息</button>
    </div>
    <div class="chat-history" :ref="props.containerRef" @scroll="props.vm.handleChatScroll">
      <div v-if="props.vm.loadingMore" class="loading-more-hint">
        <Loader2 class="w-4 h-4 spin" />
        <span>{{ t('common.loading') }}</span>
      </div>
      <div v-else-if="props.vm.hasMore" class="load-more-hint" @click="props.vm.loadOlderMessages">
        · {{ t('common.load_more') }}
      </div>
      <template v-for="msg in props.vm.messages" :key="msg.id">
        <!-- 会话分隔线：每次初始化产生 -->
        <div
          v-if="msg.message_type === 'init_reason'"
          class="session-separator"
          :class="{ 'is-highlighted': props.vm.highlightedMessageId === msg.id }"
          :data-message-id="msg.id"
        >
          <div class="separator-line"></div>
          <div class="separator-content">
            <span class="separator-time">{{ props.vm.formatTime(msg.created_at) }}</span>
            <span v-if="msg.content" class="separator-reason">{{ msg.content }}</span>
          </div>
          <div class="separator-line"></div>
        </div>
        <!-- 普通消息气泡 -->
        <ChatMessageBubble
          v-else
          :msg="msg"
          :vm="props.vm"
          @undo-request="emit('undo-request', $event)"
        />
      </template>

      <div v-if="props.vm.messages.length === 0" class="chat-empty-hint">
        <p>{{ t('chat.empty_hint') }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ─── Chat History Panel Root ─── */
.chat-history-panel-root {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}

/* ─── Chat History ─── */
.chat-history {
  flex: 1;
  min-width: 0;
  min-height: 0;
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

/* ─── Session Separator ─── */
.session-separator {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  width: 100%;
  max-width: 100%;
}
.separator-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(to right, transparent, #CBD5E1, transparent);
}
.separator-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}
.separator-time {
  font-size: 0.75rem;
  color: #94A3B8;
  white-space: nowrap;
}
.separator-reason {
  font-size: 0.8rem;
  color: #64748B;
  font-weight: 500;
  max-width: 300px;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-separator.is-highlighted {
  animation: context-reference-pulse 1.3s ease-in-out 2;
}
@keyframes context-reference-pulse {
  0% { filter: drop-shadow(0 0 0 rgba(14, 165, 233, 0)); }
  45% { filter: drop-shadow(0 0 12px rgba(14, 165, 233, 0.45)); }
  100% { filter: drop-shadow(0 0 0 rgba(14, 165, 233, 0)); }
}

.history-context-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 8px 24px 0; padding: 10px 14px; border: 1px solid var(--el-color-primary-light-7); border-radius: 8px; background: var(--el-color-primary-light-9); color: var(--el-text-color-regular); font-size: 13px; }
.history-context-bar span { margin-right: auto; }
.history-context-bar button { cursor: pointer; padding: 4px 9px; background: var(--el-bg-color); color: var(--el-color-primary); border: 1px solid var(--el-border-color); border-radius: 5px; }
.history-context-bar button:disabled { cursor: wait; opacity: .5; }
</style>
