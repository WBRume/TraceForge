<script setup lang="ts">
import { computed } from 'vue'
import UserAvatar from './UserAvatar.vue'

type BadgeSize = 'sm' | 'md'

const props = withDefaults(defineProps<{
  displayName?: string | null
  email?: string | null
  userId?: string | null
  avatarSvg?: string | null
  avatarUrl?: string | null
  size?: BadgeSize
}>(), {
  displayName: '',
  email: '',
  userId: '',
  avatarSvg: '',
  avatarUrl: '',
  size: 'sm',
})

const resolvedName = computed(() => {
  const fallback = props.userId?.trim() ? props.userId.slice(0, 8) : ''
  return props.displayName?.trim() || props.email?.trim() || fallback || '-'
})
</script>

<template>
  <div class="user-identity-badge" :class="`size-${size}`">
    <UserAvatar
      :display-name="displayName"
      :email="email"
      :user-id="userId"
      :avatar-svg="avatarSvg"
      :avatar-url="avatarUrl"
      :size="size === 'sm' ? 'sm' : 'md'"
      :title="resolvedName"
    />
    <span class="user-name">{{ resolvedName }}</span>
  </div>
</template>

<style scoped>
.user-identity-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.7rem 0.35rem 0.4rem;
  border-radius: 999px;
  border: 1px solid #bae6fd;
  background: #f0f9ff;
}

.user-name {
  font-weight: 600;
  color: #0369a1;
  white-space: nowrap;
}

.size-sm .user-name {
  font-size: 0.875rem;
}

.size-md .user-name {
  font-size: 0.95rem;
}
</style>
