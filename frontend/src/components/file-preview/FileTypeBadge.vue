<script setup lang="ts">
import { computed } from 'vue'
import { fileType } from './fileTypes'

const props = defineProps<{ path: string }>()
const type = computed(() => fileType(props.path))
</script>

<template>
  <span class="type-badge" :class="type.tone">{{ type.label }}</span>
</template>

<style scoped>
.type-badge { display: inline-grid; place-items: center; flex: none; min-width: 30px; padding: 2px 4px; border-radius: 4px; background: #e9eff5; color: #475569; font: 700 9px/1.4 var(--font-mono, monospace); }
.red { background: #fee2e2; color: #b91c1c; }
.blue { background: #dbeafe; color: #1d4ed8; }
.green { background: #dcfce7; color: #166534; }
.orange { background: #ffedd5; color: #9a3412; }
.violet { background: #ede9fe; color: #6d28d9; }
.sky { background: #e0f2fe; color: #0369a1; }
</style>
