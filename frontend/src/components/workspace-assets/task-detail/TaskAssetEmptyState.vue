<script setup lang="ts">
import { Inbox } from 'lucide-vue-next'

defineProps<{
  title: string
  message: string
  boundary?: string
}>()
</script>

<template>
  <section class="task-asset-empty">
    <div class="icon-wrapper">
      <Inbox class="empty-icon" />
    </div>
    <div class="text-content">
      <strong class="empty-title">{{ title }}</strong>
      <p class="empty-message">{{ message }}</p>
    </div>
    <span v-if="boundary" class="empty-boundary">{{ boundary }}</span>
    <div v-if="$slots.action" class="empty-action">
      <slot name="action" />
    </div>
  </section>
</template>

<style scoped>
.task-asset-empty {
  min-height: 280px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 16px;
  border: 1px dashed #e2e8f0;
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.5);
  color: #64748b;
  text-align: center;
  padding: 40px;
  transition: all 0.3s ease;
}

.task-asset-empty:hover {
  background: rgba(241, 245, 249, 0.8);
  border-color: #cbd5e1;
}

.icon-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  background: white;
  border-radius: 14px;
  box-shadow: 0 4px 10px rgba(15, 23, 42, 0.04);
}

.empty-icon {
  width: 28px;
  height: 28px;
  color: #94a3b8;
}

.text-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.empty-title {
  color: #1e293b;
  font-family: 'Poppins', sans-serif;
  font-size: 1.1rem;
  font-weight: 600;
}

.empty-message {
  max-width: 400px;
  margin: 0;
  color: #64748b;
  font-size: 0.875rem;
  line-height: 1.6;
}

.empty-boundary {
  padding: 4px 12px;
  background: #f0f9ff;
  color: #0369a1;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
}

.empty-action {
  margin-top: 8px;
}
</style>
