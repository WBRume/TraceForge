<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{
  index: string
  title: string
  icon: Component
  tone?: 'primary' | 'amber' | 'emerald' | 'rose'
}>()
</script>

<template>
  <section class="report-section" :class="`tone-${tone || 'primary'}`">
    <header class="report-section-header">
      <span class="section-index">{{ index }}</span>
      <span class="section-icon">
        <component :is="icon" class="section-icon-svg" />
      </span>
      <h3 class="section-title">{{ title }}</h3>
    </header>
    <div class="report-section-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.report-section {
  background: #ffffff;
  border: 1px solid #e8edf3;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.report-section:hover {
  border-color: #e2e8f0;
  box-shadow: 0 4px 16px -6px rgba(16, 24, 40, 0.08);
}

.report-section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 16px;
  border-bottom: 1px solid #f1f5f9;
  background: #fcfdfe;
}

.section-index {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: #cbd5e1;
  flex-shrink: 0;
  min-width: 18px;
}

.section-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  color: var(--color-primary-600);
  background: var(--color-primary-50);
  flex-shrink: 0;
}

.section-icon-svg {
  width: 16px;
  height: 16px;
}

.section-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: #0f172a;
}

/* 色彩区分仅通过图标小方块（tone 色）表达，无边框条 / 无渐变 */
.report-section.tone-amber .section-icon {
  color: #b45309;
  background: #fef3c7;
}

.report-section.tone-emerald .section-icon {
  color: #047857;
  background: #d1fae5;
}

.report-section.tone-rose .section-icon {
  color: #be123c;
  background: #ffe4e6;
}

.report-section-body {
  padding: 16px;
}

@media (prefers-reduced-motion: reduce) {
  .report-section {
    transition: none;
  }
}
</style>
