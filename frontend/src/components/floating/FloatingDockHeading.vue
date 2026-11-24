<script setup lang="ts">
defineProps<{ label: string; workspaceName?: string; title: string; tone?: string }>()
</script>

<template>
  <span class="panel-badge" :class="tone">{{ label }}</span>
  <span v-if="workspaceName" class="panel-ws-badge" :title="workspaceName">{{ workspaceName }}</span>
  <span class="panel-title" :title="title">{{ title }}</span>
</template>

<style scoped>
.panel-badge, .panel-ws-badge { display: inline-block; padding: 2px 7px; border-radius: 6px; font-size: 10.5px; flex-shrink: 0; color: #0284c7; background: #f0f9ff; border: 1px solid #bae6fd; }
.panel-ws-badge { background: #f8fafc; color: #475569; border-color: #e2e8f0; max-width: 90px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.panel-title { font-size: 12.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.is-waiting { color: #b45309; background: #fffbeb; }
.is-finished { color: #15803d; background: #f0fdf4; }
.is-error { color: #be123c; background: #fff1f2; }
.is-user { color: #d97706; background: #fffbeb; border-color: #fde68a; }
.is-assistant { color: #7c3aed; background: #faf5ff; border-color: #ddd6fe; }
</style>
