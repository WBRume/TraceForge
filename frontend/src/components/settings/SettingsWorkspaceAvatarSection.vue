<script setup lang="ts">
import { computed } from 'vue'
import SettingsAppearanceSection from '@/components/settings/SettingsAppearanceSection.vue'
import { useAvatarPreference } from '@/composables/useAvatarPreference'
import { useWorkspaceStore } from '@/stores/workspace'
import type { SavedAvatar } from '@/utils/avatar'

const props = defineProps<{ workspaceId: string }>()
const workspaceStore = useWorkspaceStore()
const workspace = computed(() => {
  const current: (Partial<SavedAvatar> & { id: string; name: string; can_edit_avatar?: boolean }) | null =
    workspaceStore.currentWorkspace
  return current?.id === props.workspaceId ? current : null
})

const preference = useAvatarPreference({
  target: () => {
    const current = workspace.value
    return current && {
      id: current.id,
      display_name: current.name,
      avatar_svg: current.avatar_svg,
      avatar_url: current.avatar_url,
    }
  },
  shape: 'square',
  canEdit: () => workspace.value?.can_edit_avatar === true,
  endpoint: id => `/workspaces/${id}/avatar`,
  onSaved: workspaceStore.setWorkspaceAvatar,
})
</script>

<template>
  <SettingsAppearanceSection :preference="preference" scope="workspace" />
</template>
