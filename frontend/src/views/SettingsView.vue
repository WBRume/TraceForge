<script setup lang="ts">
import { computed, proxyRefs } from 'vue'
import { useI18n } from 'vue-i18n'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import LocalServiceForm from '@/components/local-resource/LocalServiceForm.vue'
import SettingsAgentSection from '@/components/settings/SettingsAgentSection.vue'
import SettingsLocalDevSection from '@/components/settings/SettingsLocalDevSection.vue'
import SettingsMembersSection from '@/components/settings/SettingsMembersSection.vue'
import SettingsPlanDocsSection from '@/components/settings/SettingsPlanDocsSection.vue'
import SettingsSidebarNav from '@/components/settings/SettingsSidebarNav.vue'
import WebhookSettingsSection from '@/components/settings/WebhookSettingsSection.vue'
import { useSettingsViewModel } from '@/composables/useSettingsViewModel'

const WORKSPACE_SECTION_IDS = ['local_dev', 'local_service', 'members', 'agent', 'plan_docs', 'webhook_workspace']

const rawVm = useSettingsViewModel({
  sectionIds: WORKSPACE_SECTION_IDS,
  defaultSection: 'members',
})
const vm = proxyRefs(rawVm)
const { t } = useI18n()

const groups = computed(() => [
  { title: t('settings.nav.local'), ids: ['local_dev', 'local_service'] },
  { title: t('settings.nav.workspace'), ids: ['members', 'agent', 'plan_docs', 'webhook_workspace'] },
])
</script>

<template>
  <div class="settings-container">
    <header class="settings-header animate-slide-down">
      <div class="header-content">
        <h1 class="title-gradient">{{ $t('settings.workspace_title') }}</h1>
        <p class="subtitle">{{ $t('settings.workspace_subtitle') }}</p>
      </div>
    </header>

    <div class="settings-content animate-fade-in">
      <div class="settings-layout">
        <SettingsSidebarNav :vm="rawVm" :groups="groups" />

        <main class="settings-main glass-panel">
          <transition name="fade-slide" mode="out-in">
            <SettingsLocalDevSection v-if="vm.activeSection === 'local_dev'" key="local_dev" />
            <LocalServiceForm v-else-if="vm.activeSection === 'local_service'" key="local_service" :workspace-id="vm.workspaceId" />
            <SettingsMembersSection v-else-if="vm.activeSection === 'members'" key="members" :vm="rawVm" />
            <SettingsAgentSection v-else-if="vm.activeSection === 'agent'" key="agent" />
            <SettingsPlanDocsSection v-else-if="vm.activeSection === 'plan_docs'" key="plan_docs" :workspace-id="vm.workspaceId" />
            <WebhookSettingsSection v-else-if="vm.activeSection === 'webhook_workspace'" key="webhook_workspace" scope="workspace" :workspace-id="vm.workspaceId" />
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

    <ConfirmActionModal
      :show="vm.showBatchRemoveConfirm"
      :title="$t('settings.members.batch_remove')"
      :message="$t('settings.members.confirm_batch_remove', { count: vm.selectedMembers.length })"
      :cancel-text="$t('common.cancel')"
      :confirm-text="$t('common.delete')"
      tone="danger"
      :loading="Boolean(vm.batchRemoving)"
      @cancel="vm.closeBatchRemoveDialog"
      @confirm="vm.confirmRemoveSelectedMembers"
    />
  </div>
</template>

<style scoped src="@/styles/settings/shell.css"></style>
