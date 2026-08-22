<script setup lang="ts">
import { proxyRefs } from 'vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import SettingsAgentSection from '@/components/settings/SettingsAgentSection.vue'
import SettingsAppearanceSection from '@/components/settings/SettingsAppearanceSection.vue'
import SettingsGeneralSection from '@/components/settings/SettingsGeneralSection.vue'
import SettingsLocalDevSection from '@/components/settings/SettingsLocalDevSection.vue'
import SettingsMembersSection from '@/components/settings/SettingsMembersSection.vue'
import SettingsSidebarNav from '@/components/settings/SettingsSidebarNav.vue'
import { useSettingsViewModel } from '@/composables/useSettingsViewModel'

const rawVm = useSettingsViewModel()
const vm = proxyRefs(rawVm)
</script>

<template>
  <div class="settings-container">
    <header class="settings-header animate-slide-down">
      <div class="header-content">
        <h1 class="title-gradient">{{ $t('settings.title') }}</h1>
        <p class="subtitle">{{ $t('settings.subtitle') }}</p>
      </div>
    </header>

    <div class="settings-content animate-fade-in">
      <div class="settings-layout">
        <SettingsSidebarNav :vm="rawVm" />

        <main class="settings-main glass-panel">
          <transition name="fade-slide" mode="out-in">
            <SettingsGeneralSection v-if="vm.activeSection === 'general'" key="general" :vm="rawVm" />
            <SettingsAppearanceSection v-else-if="vm.activeSection === 'appearance'" key="appearance" :vm="rawVm" />
            <SettingsMembersSection v-else-if="vm.activeSection === 'members'" key="members" :vm="rawVm" />
            <SettingsLocalDevSection v-else-if="vm.activeSection === 'local_dev'" key="local_dev" />
            <SettingsAgentSection v-else-if="vm.activeSection === 'agent'" key="agent" />
          </transition>
        </main>
      </div>
    </div>

    <ConfirmActionModal
      :show="vm.showRemoveConfirm"
      :title="$t('settings.members.remove_member')"
      :message="$t('settings.members.confirm_remove', { name: vm.memberToRemove?.display_name || vm.memberToRemove?.email || '' })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.delete')"
      tone="danger"
      :loading="Boolean(vm.removingMemberId)"
      @cancel="vm.closeRemoveDialog"
      @confirm="vm.confirmRemoveMember"
    />
  </div>
</template>

<style scoped src="@/styles/settings/settings-view-shared.css"></style>
