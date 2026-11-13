<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import UserAvatar from '@/components/user/UserAvatar.vue'
import type { CollaborationState } from '@/types/collaboration'

defineProps<{
  agentActive: boolean
  connecting: boolean
  driverId?: string
  profile?: CollaborationState['driver_profile']
  ownHost: boolean
}>()

const { t } = useI18n()
</script>

<template>
  <div v-if="agentActive || connecting || driverId" class="closeout-availability" role="status">
    <p v-if="agentActive">{{ t('chat.closeout.availability.agent_active') }}</p>
    <p v-if="connecting">{{ t('chat.closeout.availability.connecting') }}</p>
    <p v-if="driverId && ownHost">{{ t('chat.closeout.availability.own_host') }}</p>
    <template v-else-if="driverId">
      <p>{{ t('chat.closeout.availability.other_host') }}</p>
      <div class="host">
        <UserAvatar :user-id="driverId" :display-name="profile?.display_name"
          :avatar-url="profile?.avatar_url" :avatar-svg="profile?.avatar_svg" size="sm" />
        <div class="identity">
          <strong v-if="profile?.display_name">{{ profile.display_name }}</strong>
          <span>{{ t('chat.closeout.availability.host_id', { id: driverId }) }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.closeout-availability {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1.25rem;
  font-size: 0.8125rem;
  line-height: 1.5;
  color: #475569;
}

.closeout-availability p {
  margin: 0;
}

.host {
  display: flex;
  align-items: center;
  gap: 0.625rem;
}

.identity {
  display: flex;
  flex-direction: column;
  overflow-wrap: anywhere;
}

.identity strong {
  color: #334155;
}
</style>
