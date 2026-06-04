<script setup lang="ts">
defineProps<{
  title: string
  description: string
}>()
</script>

<template>
  <section class="task-asset-panel">
    <header class="panel-head">
      <h3>{{ title }}</h3>
      <p>{{ description }}</p>
    </header>
    <slot />
  </section>
</template>

<style scoped>
.task-asset-panel {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.panel-head h3 {
  margin: 0;
  color: #0f172a;
  font-family: 'Poppins', var(--font-heading);
  font-size: 0.98rem;
  letter-spacing: 0;
}

.panel-head p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 0.82rem;
  line-height: 1.48;
}
</style>
