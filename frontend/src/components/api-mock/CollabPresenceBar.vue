<script setup lang="ts">
import UserAvatar from '@/components/user/UserAvatar.vue'

type PresenceUser = {
  id: string
  displayName: string
  email?: string | null
  avatarSvg?: string | null
  avatarUrl?: string | null
}

defineProps<{
  users: PresenceUser[]
  connected: boolean
}>()

const titleForUser = (user: PresenceUser) => {
  if (user.email) {
    return `${user.displayName} (${user.email})`
  }
  return user.displayName
}
</script>

<template>
  <section class="presence-bar glass-panel">
    <div class="presence-left">
      <span class="dot" :class="{ online: connected }"></span>
      <span class="label">{{ connected ? $t('api_mock.collab_connected') : $t('api_mock.collab_disconnected') }}</span>
    </div>
    <div class="users">
      <span class="count">{{ $t('api_mock.online_users', { count: users.length }) }}</span>
      <div class="avatars">
        <span
          v-for="user in users.slice(0, 5)"
          :key="user.id"
          class="avatar"
        >
          <UserAvatar
            :display-name="user.displayName"
            :email="user.email || ''"
            :user-id="user.id"
            :avatar-svg="user.avatarSvg || ''"
            :avatar-url="user.avatarUrl || ''"
            size="sm"
            :title="titleForUser(user)"
          />
        </span>
        <span v-if="users.length > 5" class="more">+{{ users.length - 5 }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.presence-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
}

.presence-left {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  color: #334155;
  font-size: 0.85rem;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: #cbd5e1;
}

.dot.online {
  background: #10b981;
  box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.18);
}

.users {
  display: inline-flex;
  align-items: center;
  gap: 0.6rem;
}

.count {
  font-size: 0.78rem;
  color: #64748b;
}

.avatars {
  display: inline-flex;
  align-items: center;
}

.avatar {
  margin-left: -4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.more {
  margin-left: 0.35rem;
  font-size: 0.72rem;
  color: #0c4a6e;
}
</style>
