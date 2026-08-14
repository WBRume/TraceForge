<!--
AdminGuard: renders default slot only when current user is an admin.
When showHint is true, non-admins see a readonly banner instead.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { Info } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'

const props = withDefaults(defineProps<{
  showHint?: boolean
}>(), {
  showHint: false,
})

const authStore = useAuthStore()
const isAdmin = computed(() => Boolean(authStore.user?.is_admin))
</script>

<template>
  <slot v-if="isAdmin" />
  <div v-else-if="props.showHint" class="mgmt-readonly-banner">
    <Info class="w-4 h-4" />
    <span>{{ $t('management.common.admin_required') }}</span>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
