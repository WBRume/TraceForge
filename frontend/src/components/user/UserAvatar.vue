<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { getApiServerUrl } from '@/utils/api'
import { scopeAvatarSvgIds, type AvatarShape } from '@/utils/avatar'
import { avatarSvgView } from '@/utils/avatarVector'

type AvatarSize = 'xs' | 'sm' | 'md' | 'lg'

const props = withDefaults(defineProps<{
  displayName?: string | null
  email?: string | null
  userId?: string | null
  avatarSvg?: string | null
  avatarUrl?: string | null
  size?: AvatarSize
  shape?: AvatarShape
  accentColor?: string | null
  title?: string
}>(), {
  displayName: '',
  email: '',
  userId: '',
  avatarSvg: '',
  avatarUrl: '',
  size: 'md',
  shape: 'circle',
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
  return scopeAvatarSvgIds(normalizeSvgMarkup(raw))
})
const rawAvatarUrl = computed(() => props.avatarUrl?.trim() || '')
const isLocalPhoto = computed(() => (
  rawAvatarUrl.value.startsWith('/api/auth/avatars/')
  || /^\/api\/workspaces\/[^/]+\/avatars\//.test(rawAvatarUrl.value)
))
const vectorView = computed(() => isLocalPhoto.value ? avatarSvgView(rawAvatarUrl.value) : null)
const resolvedAvatarUrl = computed(() => (
  isLocalPhoto.value ? `${getApiServerUrl()}${vectorView.value?.src ?? rawAvatarUrl.value}` : rawAvatarUrl.value
))
const failedUrl = shallowRef('')
watch(resolvedAvatarUrl, () => { failedUrl.value = '' })
const imageUrl = computed(() => {
  if (resolvedAvatarUrl.value === failedUrl.value) return ''
  return isLocalPhoto.value || !avatarSvgContent.value ? resolvedAvatarUrl.value : ''
})
const showFallbackInitial = computed(() => !avatarSvgContent.value && !imageUrl.value)

const avatarStyle = computed(() => {
  if (!showFallbackInitial.value || !props.accentColor) return undefined
  return { background: props.accentColor }
})
</script>

<template>
  <span
    class="user-avatar"
    :class="[`size-${size}`, { 'shape-square': shape === 'square' }]"
    :title="title || fallbackName"
    :style="avatarStyle"
  >
    <img
      v-if="imageUrl"
      :key="imageUrl"
      class="avatar-image"
      :class="{ 'avatar-image-cropped': vectorView }"
      :src="imageUrl"
      :style="vectorView?.style"
      :alt="fallbackName"
      @error="failedUrl = imageUrl"
    >
    <span v-else-if="avatarSvgContent" class="avatar-svg" v-html="avatarSvgContent"></span>
    <span v-else><slot>{{ initial }}</slot></span>
  </span>
</template>

<style scoped>
.user-avatar {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 999px;
  background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%);
  color: #fff;
  font-weight: 700;
  user-select: none;
  overflow: hidden;
}

.shape-square {
  border-radius: 12px;
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

.avatar-image-cropped {
  position: absolute;
  max-width: none;
  max-height: none;
  object-fit: fill;
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
