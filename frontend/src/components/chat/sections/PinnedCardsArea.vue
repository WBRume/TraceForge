<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Brain, ChevronDown } from '@/components/icons'
import HitlInteractionCard from './HitlInteractionCard.vue'
import type { HitlCard } from '@/composables/chat/types'

/**
 * 会话置顶卡片区（不随对话滚动）：AI 思考卡与 HITL 交互卡的装配容器。
 * 展开状态与应答提交均上交视图模型，本组件只做编排与思考卡的展示。
 */
const props = withDefaults(defineProps<{
  showThinking: boolean
  thinkingContent: string
  thinkingExpanded: boolean
  engineRunning: boolean
  hitlCards?: HitlCard[]
}>(), {
  hitlCards: () => [],
})

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
    <div
      v-if="props.showThinking && props.thinkingContent"
      class="pinned-card thinking-card"
      :class="{ 'is-running': props.engineRunning, 'is-expanded': props.thinkingExpanded }"
    >
      <div
        class="card-header thinking-header"
        role="button"
        tabindex="0"
        :aria-expanded="props.thinkingExpanded"
        @click="emit('update:thinkingExpanded', !props.thinkingExpanded)"
        @keydown.enter.prevent="emit('update:thinkingExpanded', !props.thinkingExpanded)"
        @keydown.space.prevent="emit('update:thinkingExpanded', !props.thinkingExpanded)"
      >
        <div class="header-title flex items-center gap-2">
          <span class="thinking-icon" aria-hidden="true">
            <Brain class="w-4 h-4" />
          </span>
          <span class="thinking-label">
            {{ thinkingBase }}<span v-if="props.engineRunning" class="thinking-dots" aria-hidden="true"></span><span v-else>...</span>
          </span>
        </div>
        <span class="thinking-toggle" aria-hidden="true">
          <ChevronDown class="w-4 h-4 toggle-icon transition-transform" :class="{ 'rotate-180': props.thinkingExpanded }" />
        </span>
      </div>
      <Transition name="thinking-fold">
        <div v-show="props.thinkingExpanded" class="card-body thinking-body">
          <pre>{{ props.thinkingContent }}</pre>
        </div>
      </Transition>
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
  /* 与悬浮的会话工具栏之间留出呼吸间距，避免卡片像贴在工具栏下沿 */
  padding: 28px 16px 8px;
  /* 悬浮卡片自带边界，容器不再用横线与底色切出第二条“带子” */
  background: transparent;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
  max-height: 300px;
  overflow-y: auto;
}

.pinned-card {
  border-radius: 18px;
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

/* ── Thinking Card：纯白圆角卡片，靠描边与轻阴影融入悬浮岛体系 ── */
.thinking-card {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.06);
  background: var(--color-surface-white, #FFFFFF);
  box-shadow:
    0 8px 24px -14px rgba(15, 23, 42, 0.14),
    0 1px 2px rgba(15, 23, 42, 0.04);
  transition: border-color 200ms ease, box-shadow 200ms ease;
}

.thinking-card.is-running {
  border-color: rgba(14, 165, 233, 0.26);
  box-shadow:
    0 10px 26px -14px rgba(14, 165, 233, 0.18),
    0 1px 2px rgba(15, 23, 42, 0.04);
}

/* 收起时收成一枚状态胶囊，避免在悬浮工具栏下方再叠一条“全宽横条” */
.thinking-card:not(.is-expanded) {
  width: fit-content;
  max-width: 100%;
  border-radius: 999px;
}

.thinking-card:not(.is-expanded) .thinking-header {
  border-radius: 999px;
  padding-right: 6px;
}

.thinking-header {
  min-height: 44px;
  box-sizing: border-box;
  padding: 7px 10px;
  border-radius: 17px;
  cursor: pointer;
  user-select: none;
  transition: background-color 160ms ease;
}

.thinking-header:hover {
  background: rgba(14, 165, 233, 0.045);
}

.thinking-header:focus-visible {
  outline: 2px solid var(--color-primary-500, #0EA5E9);
  outline-offset: -2px;
}

.header-title {
  min-width: 0;
}

/* 图标做成柔和的品牌色小方块，替代裸图标 */
.thinking-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  flex: 0 0 auto;
  border-radius: 8px;
  color: var(--color-primary-600, #0284C7);
  background: #F0F9FF;
  box-shadow: inset 0 0 0 1px #E0F2FE;
}

.thinking-card.is-running .thinking-icon {
  animation: thinking-icon-breathe 2.4s ease-in-out infinite;
}

@keyframes thinking-icon-breathe {
  0%, 100% {
    box-shadow: inset 0 0 0 1px rgba(14, 165, 233, 0.16), 0 0 0 0 rgba(14, 165, 233, 0.20);
  }
  50% {
    box-shadow: inset 0 0 0 1px rgba(14, 165, 233, 0.26), 0 0 0 4px rgba(14, 165, 233, 0);
  }
}

.thinking-label {
  display: inline-flex;
  align-items: center;
  font-size: 0.8rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: #334155;
  white-space: nowrap;
}

.thinking-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  margin-left: auto;
  flex: 0 0 auto;
  border-radius: 50%;
  color: #94A3B8;
  transition: background-color 160ms ease, color 160ms ease;
}

.thinking-header:hover .thinking-toggle {
  background: rgba(15, 23, 42, 0.05);
  color: #475569;
}

.thinking-body {
  max-height: clamp(96px, 18vh, 160px);
  overflow-y: auto;
  overscroll-behavior: contain;
  margin: 2px 10px 10px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid rgba(15, 23, 42, 0.05);
  background: #F8FAFC;
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.03);
}

.thinking-fold-enter-active,
.thinking-fold-leave-active {
  transition: opacity 160ms ease, transform 160ms ease;
}

.thinking-fold-enter-from,
.thinking-fold-leave-to {
  opacity: 0;
  transform: translateY(-3px);
}

.thinking-body pre {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 0.78rem;
  line-height: 1.7;
  color: #64748B;
  white-space: pre-wrap;
  word-wrap: break-word;
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

@media (prefers-reduced-motion: reduce) {
  .thinking-card,
  .thinking-header,
  .thinking-icon,
  .thinking-toggle {
    transition: none;
  }

  .thinking-card.is-running .thinking-icon {
    animation: none;
  }

  .thinking-fold-enter-active,
  .thinking-fold-leave-active {
    transition: none;
  }

  .thinking-dots::after {
    animation: none;
    content: '...';
  }
}
</style>
