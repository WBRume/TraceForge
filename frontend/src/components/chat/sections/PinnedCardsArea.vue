<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Brain, ChevronDown } from 'lucide-vue-next'
import HitlInteractionCard from './HitlInteractionCard.vue'
import type { HitlCard } from '@/composables/chat/types'

/**
 * 会话置顶卡片区（不随对话滚动）：AI 思考卡与 HITL 交互卡的装配容器。
 * 展开状态与应答提交均上交视图模型，本组件只做编排与思考卡的展示。
 */
const props = defineProps<{
  showThinking: boolean
  thinkingContent: string
  thinkingExpanded: boolean
  engineRunning: boolean
  hitlCards: HitlCard[]
}>()

const emit = defineEmits<{
  (event: 'update:thinkingExpanded', value: boolean): void
  (event: 'submit-hitl', cardId: string, value: string): void
}>()

const { t } = useI18n()

const thinkingBase = computed(() => t('chat.thinking').replace(/\.{3,}$/, ''))

const hasCards = () => (
  props.hitlCards.length > 0 || (props.showThinking && Boolean(props.thinkingContent))
)
</script>

<template>
  <div class="pinned-cards-area" v-if="hasCards()">
    <!-- AI 思考面板 -->
    <div v-if="props.showThinking && props.thinkingContent" class="pinned-card thinking-card">
      <div
        class="card-header thinking-header"
        role="button"
        :aria-expanded="props.thinkingExpanded"
        @click="emit('update:thinkingExpanded', !props.thinkingExpanded)"
      >
        <div class="header-title flex items-center gap-2">
          <Brain class="w-4 h-4 text-primary" />
          <span class="thinking-label">
            {{ thinkingBase }}<span v-if="props.engineRunning" class="thinking-dots" aria-hidden="true"></span><span v-else>...</span>
          </span>
        </div>
        <ChevronDown class="w-4 h-4 toggle-icon transition-transform" :class="{'rotate-180': props.thinkingExpanded}" />
      </div>
      <div v-show="props.thinkingExpanded" class="card-body thinking-body fixed-height">
        <pre>{{ props.thinkingContent }}</pre>
      </div>
    </div>

    <!-- HITL 交互卡片 -->
    <HitlInteractionCard
      v-for="card in props.hitlCards"
      :key="card.id"
      :card="card"
      @submit="(cardId, value) => emit('submit-hitl', cardId, value)"
    />
  </div>
</template>

<style scoped>
.pinned-cards-area {
  padding: var(--space-3) var(--space-6);
  border-bottom: 1px solid rgba(0,0,0,0.05);
  background: #ffffff;
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
.card-body { margin-top: 4px; }

/* Thinking Card */
.thinking-card {
  background: #F1F5F9;
  border: 1px solid #E2E8F0;
}
.thinking-header {
  cursor: pointer;
  user-select: none;
}
.thinking-body.fixed-height {
  height: clamp(96px, 18vh, 160px);
  overflow-y: auto;
  overscroll-behavior: contain;
}
.thinking-body pre {
  margin: 8px 0 0;
  font-family: var(--font-mono);
  font-size: 0.8rem;
  color: #64748B;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.thinking-label {
  display: inline-flex;
  align-items: center;
}

.thinking-dots {
  display: inline-block;
  min-width: 28px;
  text-align: left;
}

.thinking-dots::after {
  content: '.';
  animation: thinking-dots-step 1.5s infinite steps(5, jump-none);
}

@keyframes thinking-dots-step {
  0% { content: '.'; }
  20% { content: '..'; }
  40% { content: '...'; }
  60% { content: '....'; }
  80% { content: '.....'; }
  100% { content: '.'; }
}
</style>
