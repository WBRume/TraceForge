<script setup lang="ts">
import { computed } from 'vue'
import UserAvatar from '@/components/user/UserAvatar.vue'

const props = defineProps<{
  name: string
  avatarSvg?: string | null
  avatarUrl?: string | null
}>()

const palettes = [
  { background: '#f0f9ff', color: '#0284c7' },
  { background: '#f0fdf4', color: '#16a34a' },
  { background: '#f5f3ff', color: '#7c3aed' },
  { background: '#fdf4ff', color: '#c026d3' },
  { background: '#fffbeb', color: '#d97706' },
  { background: '#f0fdfa', color: '#0d9488' },
]

const fallback = computed(() => {
  const name = props.name.trim()
  const hash = name.split('').reduce((sum, char) => sum + char.charCodeAt(0), 0)
  return { text: name.slice(0, 2).toUpperCase() || 'WS', style: palettes[hash % palettes.length]! }
})
</script>

<template>
  <UserAvatar
    class="workspace-avatar"
    shape="square"
    :display-name="name"
    :avatar-svg="avatarSvg"
    :avatar-url="avatarUrl"
    :style="fallback.style"
  >
    {{ fallback.text }}
  </UserAvatar>
</template>

<style scoped>
.workspace-avatar {
  width: 40px;
  height: 40px;
  font-size: 0.875rem;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}
</style>
