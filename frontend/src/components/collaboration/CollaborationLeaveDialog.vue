<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
import type { useCollaborationLeave } from '@/composables/collaboration/useCollaborationLeave'
defineProps<{ controller: LocalCollaboration; guard: ReturnType<typeof useCollaborationLeave> }>()
const { t } = useI18n()
</script>

<template>
  <ConfirmActionModal :show="guard.show.value" tone="warning" :title="t('collaboration.session.leaveTitle')"
    :message="t('collaboration.session.leaveHint')" :cancel-text="t('collaboration.session.stay')"
    :confirm-text="t('collaboration.session.leave')" :loading="controller.busy.value || controller.leaving.value"
    @cancel="guard.cancel" @confirm="guard.confirm">
    <template #content><p v-if="controller.error.value" role="alert">{{ controller.error.value }}</p></template>
  </ConfirmActionModal>
</template>
