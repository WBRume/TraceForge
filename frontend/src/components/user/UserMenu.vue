<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRightOnRectangleIcon, ChevronDown, Cog6ToothIcon } from '@/components/icons'
import { useAuthStore } from '@/stores/auth'
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

const router = useRouter()
const authStore = useAuthStore()

const root = ref<HTMLElement | null>(null)
const open = ref(false)

const resolvedName = computed(() => {
  const fallback = props.userId?.trim() ? props.userId.slice(0, 8) : ''
  return props.displayName?.trim() || props.email?.trim() || fallback || '-'
})

const toggle = () => {
  open.value = !open.value
}

const close = () => {
  open.value = false
}

const goToUserSettings = async () => {
  close()
  if (router.currentRoute.value.name === 'userSettings') return
  await router.push({ name: 'userSettings' })
}

const logout = () => {
  close()
  authStore.logout()
}

const onDocumentClick = (event: MouseEvent) => {
  if (!root.value?.contains(event.target as Node)) close()
}

const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') close()
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div ref="root" class="user-menu" :class="{ 'is-open': open }">
    <button
      type="button"
      class="user-menu-trigger"
      :class="`size-${size}`"
      data-testid="user-menu-trigger"
      :aria-expanded="open"
      aria-haspopup="menu"
      @click="toggle"
    >
      <UserAvatar
        :display-name="displayName"
        :email="email"
        :user-id="userId"
        :avatar-svg="avatarSvg"
        :avatar-url="avatarUrl"
        :size="size === 'sm' ? 'sm' : 'md'"
        :title="resolvedName"
      />
      <span class="user-menu-name">{{ resolvedName }}</span>
      <ChevronDown class="user-menu-chevron" />
    </button>

    <Transition name="user-menu-pop">
      <div v-if="open" class="user-menu-panel" role="menu" data-testid="user-menu-panel">
        <div class="user-menu-profile">
          <UserAvatar
            :display-name="displayName"
            :email="email"
            :user-id="userId"
            :avatar-svg="avatarSvg"
            :avatar-url="avatarUrl"
            :size="size === 'sm' ? 'sm' : 'md'"
            :title="resolvedName"
          />
          <div class="user-menu-profile-text">
            <strong>{{ resolvedName }}</strong>
            <span v-if="email">{{ email }}</span>
          </div>
        </div>

        <div class="user-menu-divider"></div>

        <button
          type="button"
          class="user-menu-item"
          role="menuitem"
          data-testid="user-menu-settings"
          @click="goToUserSettings"
        >
          <Cog6ToothIcon class="user-menu-item-icon" />
          <span>{{ $t('settings.user.menu_label') }}</span>
        </button>

        <button
          type="button"
          class="user-menu-item danger"
          role="menuitem"
          data-testid="user-menu-logout"
          @click="logout"
        >
          <ArrowRightOnRectangleIcon class="user-menu-item-icon" />
          <span>{{ $t('common.logout') }}</span>
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.user-menu {
  position: relative;
  display: inline-flex;
}

.user-menu-trigger {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.7rem 0.35rem 0.4rem;
  border-radius: 999px;
  border: 1px solid #bae6fd;
  background: #f0f9ff;
  color: #0369a1;
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
}

.user-menu-trigger:hover,
.user-menu.is-open .user-menu-trigger {
  border-color: #7dd3fc;
  background: #e0f2fe;
  box-shadow: 0 4px 12px -4px rgba(14, 165, 233, 0.35);
}

.user-menu-name {
  font-weight: 600;
  font-size: 0.875rem;
  white-space: nowrap;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.size-md .user-menu-name {
  font-size: 0.95rem;
}

.user-menu-chevron {
  width: 0.9rem;
  height: 0.9rem;
  opacity: 0.7;
  transition: transform 0.2s ease;
}

.user-menu.is-open .user-menu-chevron {
  transform: rotate(180deg);
}

.user-menu-panel {
  position: absolute;
  top: calc(100% + 0.6rem);
  right: 0;
  width: 248px;
  padding: 0.5rem;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 16px;
  box-shadow:
    0 20px 35px -12px rgba(15, 23, 42, 0.22),
    0 4px 12px -4px rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(14px);
  z-index: 240;
}

.user-menu-profile {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.65rem 0.6rem 0.75rem;
}

.user-menu-profile-text {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.user-menu-profile-text strong {
  font-size: 0.9rem;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-menu-profile-text span {
  font-size: 0.75rem;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-menu-divider {
  height: 1px;
  margin: 0.2rem 0.35rem 0.4rem;
  background: #e2e8f0;
}

.user-menu-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.65rem 0.7rem;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: #334155;
  font-size: 0.875rem;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition: background 0.16s ease, color 0.16s ease;
}

.user-menu-item:hover {
  background: #f0f9ff;
  color: #0369a1;
}

.user-menu-item.danger {
  color: #b91c1c;
}

.user-menu-item.danger:hover {
  background: #fef2f2;
  color: #991b1b;
}

.user-menu-item-icon {
  width: 1.1rem;
  height: 1.1rem;
  flex-shrink: 0;
}

.user-menu-pop-enter-active,
.user-menu-pop-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.user-menu-pop-enter-from,
.user-menu-pop-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}

@media (max-width: 640px) {
  .user-menu-name {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .user-menu-trigger,
  .user-menu-chevron,
  .user-menu-pop-enter-active,
  .user-menu-pop-leave-active {
    transition: none;
  }
}
</style>
