<script setup lang="ts">
import { Hammer } from '@/components/icons'

defineProps<{
  badge: string
  title: string
  description: string
}>()
</script>

<template>
  <div class="construction-panel">
    <div class="construction-icon">
      <Hammer class="construction-svg" />
    </div>
    <span class="construction-badge">{{ badge }}</span>
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
  </div>
</template>

<style scoped>
.construction-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 0.75rem;
  min-height: 420px;
  padding: 3rem 2rem;
  background: rgba(255, 255, 255, 0.8);
  border: 1px dashed #bae6fd;
  border-radius: 2rem;
  box-shadow: 0 20px 25px -5px rgba(14, 165, 233, 0.08);
  font-family: 'Open Sans', sans-serif;
}

.construction-icon {
  width: 72px;
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 1.5rem;
  background: linear-gradient(135deg, #0ea5e9, #3b82f6);
  color: #ffffff;
  box-shadow: 0 15px 25px -5px rgba(14, 165, 233, 0.35);
  margin-bottom: 0.5rem;
}

.construction-svg {
  width: 36px;
  height: 36px;
}

.construction-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.9rem;
  border-radius: 999px;
  background: #f0f9ff;
  border: 1px solid rgba(14, 165, 233, 0.2);
  color: #0284c7;
  font-size: 0.8125rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.construction-panel h3 {
  margin: 0;
  font-family: 'Poppins', sans-serif;
  font-size: 1.5rem;
  font-weight: 800;
  color: #1e3a8a;
  letter-spacing: -0.02em;
}

.construction-panel p {
  margin: 0;
  max-width: 560px;
  color: #64748b;
  line-height: 1.7;
  font-size: 0.9375rem;
}
</style>
