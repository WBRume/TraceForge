<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{
  icon: Component
  title: string
  description: string
}>()
</script>

<template>
  <div class="mgmt-card knowledge-placeholder">
    <component :is="icon" class="w-10 h-10 knowledge-placeholder-icon" />
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.knowledge-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 1rem;
  padding: 3rem 2rem;
  min-height: 320px;
}

.knowledge-placeholder-icon {
  color: var(--color-primary-400);
}

.knowledge-placeholder h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--color-primary-900);
}

.knowledge-placeholder p {
  margin: 0;
  max-width: 520px;
  color: #64748b;
  line-height: 1.6;
}

.w-10 {
  width: 2.5rem;
  height: 2.5rem;
}
</style>
