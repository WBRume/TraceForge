<script setup lang="ts">
import { proxyRefs } from 'vue'
import { Users } from 'lucide-vue-next'
import SettingsMembersAddPanel from '@/components/settings/SettingsMembersAddPanel.vue'
import SettingsMembersListPanel from '@/components/settings/SettingsMembersListPanel.vue'
import type { SettingsViewModel } from '@/composables/useSettingsViewModel'

const props = defineProps<{ vm: SettingsViewModel }>()
const rawVm = props.vm
const vm = proxyRefs(rawVm)
</script>

<template>
  <section class="settings-section members-section">
    <div class="section-header">
      <div class="icon-circle">
        <Users class="w-6 h-6" />
      </div>
      <div class="section-title-group">
        <h2>{{ $t('settings.members.title') }}</h2>
        <p>{{ $t('settings.members.subtitle') }}</p>
      </div>
    </div>

    <div class="member-summary">
      <div class="summary-card">
        <span class="summary-label">{{ $t('settings.members.my_role') }}</span>
        <strong>{{ vm.roleTag(vm.myPermissionPayload?.role || 'VIEWER') }}</strong>
      </div>
      <div class="summary-card">
        <span class="summary-label">{{ $t('settings.members.member_count') }}</span>
        <strong>{{ vm.totalMemberCount }}</strong>
      </div>
      <div class="summary-card">
        <span class="summary-label">{{ $t('settings.members.delete_workspace_right') }}</span>
        <strong>{{ vm.myPermissionPayload?.can_delete_workspace ? $t('settings.members.yes') : $t('settings.members.no') }}</strong>
      </div>
    </div>

    <div v-if="vm.membersError" class="error-banner">{{ vm.membersError }}</div>

    <div class="member-workspace">
      <SettingsMembersAddPanel :vm="rawVm" />
      <SettingsMembersListPanel :vm="rawVm" />
    </div>
  </section>
</template>

<style scoped src="@/styles/settings/settings-view-shared.css"></style>


