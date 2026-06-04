<script setup lang="ts">
import { computed } from 'vue'

type AvatarSize = 'xs' | 'sm' | 'md' | 'lg'

const props = withDefaults(defineProps<{
  displayName?: string | null
  email?: string | null
  userId?: string | null
  avatarSvg?: string | null
  avatarUrl?: string | null
  size?: AvatarSize
  accentColor?: string | null
  title?: string
}>(), {
  displayName: '',
  email: '',
  userId: '',
  avatarSvg: '',
  avatarUrl: '',
  size: 'md',
  accentColor: '',
  title: '',
})

const fallbackName = computed(() => {
  const candidate = props.displayName?.trim() || props.email?.trim() || props.userId?.trim() || '?'
  return candidate
})

const initial = computed(() => fallbackName.value.slice(0, 1).toLocaleUpperCase())
const normalizeSvgMarkup = (value: string) => (
  value
    .replaceAll(/<\s*\/?\s*ns\d+:/g, match => match.replace(/ns\d+:/, ''))
    .replaceAll(/xmlns:ns\d+="http:\/\/www\.w3\.org\/2000\/svg"/g, '')
)
const avatarSvgContent = computed(() => {
  const raw = props.avatarSvg?.trim() || ''
  if (!raw) return ''
  return normalizeSvgMarkup(raw)
})
const avatarUrlContent = computed(() => props.avatarUrl?.trim() || '')
const showFallbackInitial = computed(() => !avatarSvgContent.value && !avatarUrlContent.value)

const avatarStyle = computed(() => {
  if (!showFallbackInitial.value || !props.accentColor) return undefined
  return {
    background: props.accentColor,
    borderColor: props.accentColor,
  }
})
</script>

<template>
  <span
    class="user-avatar"
    :class="`size-${size}`"
    :title="title || fallbackName"
    :style="avatarStyle"
  >
    <span v-if="avatarSvgContent" class="avatar-svg" v-html="avatarSvgContent"></span>
    <img v-else-if="avatarUrlContent" class="avatar-image" :src="avatarUrlContent" :alt="fallbackName">
    <span v-else>{{ initial }}</span>
  </span>
</template>

<style scoped>
.user-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 999px;
  border: 1px solid #93c5fd;
  background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%);
  color: #fff;
  font-weight: 700;
  user-select: none;
  overflow: hidden;
}

.avatar-svg,
.avatar-image {
  width: 100%;
  height: 100%;
  display: block;
}

.avatar-image {
  object-fit: cover;
}

.avatar-svg :deep(svg) {
  width: 100%;
  height: 100%;
  display: block;
  border-radius: inherit;
}

.size-sm {
  width: 1.5rem;
  height: 1.5rem;
  font-size: 0.75rem;
}

.size-xs {
  width: 1.125rem;
  height: 1.125rem;
  font-size: 0.62rem;
}

.size-md {
  width: 1.8rem;
  height: 1.8rem;
  font-size: 0.82rem;
}

.size-lg {
  width: 2.2rem;
  height: 2.2rem;
  font-size: 0.95rem;
}
</style>
