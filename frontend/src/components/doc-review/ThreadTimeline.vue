<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  messages: Array<{
    id: string
    role: 'user' | 'ai' | 'system'
    content: string
    creator_display_name?: string | null
    created_at: string
  }>
}>()

const { t } = useI18n()

const roleLabel = (role: string) => {
  if (role === 'ai') return 'AI'
  if (role === 'system') return t('doc_review.role_system')
  return t('doc_review.role_member')
}
</script>

<template>
  <div class="timeline custom-scrollbar">
    <div v-for="message in props.messages" :key="message.id" class="timeline-item" :class="`role-${message.role}`">
      <div class="timeline-meta">
        <strong>{{ roleLabel(message.role) }}</strong>
        <span v-if="message.creator_display_name">· {{ message.creator_display_name }}</span>
        <time>{{ new Date(message.created_at).toLocaleString() }}</time>
      </div>
      <p class="timeline-content">{{ message.content }}</p>
    </div>
  </div>
</template>

<style scoped>
.timeline {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 360px;
  overflow-y: auto;
  padding: 8px 12px 24px 12px;
  margin: -8px -12px 0 -12px;
}

.timeline-item {
  position: relative;
  z-index: 1;
  border-radius: var(--radius-lg);
  padding: 0.75rem;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.6);
  box-shadow: 0 4px 12px -2px rgba(0, 0, 0, 0.03);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.timeline-item:hover {
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 8px 16px -4px rgba(0, 0, 0, 0.08);
  transform: translateY(-2px);
  z-index: 2;
}

.timeline-item.role-ai {
  border-color: rgba(14, 165, 233, 0.4);
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 8px 20px -6px rgba(14, 165, 233, 0.4);
}

.timeline-item.role-ai:hover {
  box-shadow: 0 12px 28px -4px rgba(14, 165, 233, 0.5);
}

.timeline-item.role-system {
  border-color: rgba(226, 232, 240, 0.8);
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 8px 20px -6px rgba(148, 163, 184, 0.3);
}

.timeline-item.role-system:hover {
  box-shadow: 0 12px 28px -4px rgba(148, 163, 184, 0.4);
}

.timeline-meta {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-bottom: 6px;
  font-size: 11px;
  color: var(--color-text-muted);
}

.timeline-content {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text-body);
  white-space: pre-wrap;
}
</style>
