<script setup lang="ts">
import { computed, proxyRefs } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeftIcon } from '@/components/icons'
import SettingsAppearanceSection from '@/components/settings/SettingsAppearanceSection.vue'
import SettingsConnectedAccountsSection from '@/components/settings/SettingsConnectedAccountsSection.vue'
import SettingsGeneralSection from '@/components/settings/SettingsGeneralSection.vue'
import SettingsSidebarNav from '@/components/settings/SettingsSidebarNav.vue'
import WebhookSettingsSection from '@/components/settings/WebhookSettingsSection.vue'
import { useSettingsViewModel } from '@/composables/useSettingsViewModel'

const USER_SECTION_IDS = ['general', 'connected_accounts', 'appearance', 'webhook_personal']

const rawVm = useSettingsViewModel({
  sectionIds: USER_SECTION_IDS,
  defaultSection: 'general',
})
const vm = proxyRefs(rawVm)
const router = useRouter()
const { t } = useI18n()

const groups = computed(() => [
  { title: t('settings.nav.personal'), ids: USER_SECTION_IDS },
])

const goBack = () => {
  if (window.history.length > 1) {
    router.back()
    return
  }
  router.push('/workspaces')
}
</script>

<template>
  <div class="user-settings-page" data-testid="user-settings-view">
    <div class="user-settings-topbar">
      <button type="button" class="user-settings-back" data-testid="user-settings-back" @click="goBack">
        <ArrowLeftIcon class="w-4 h-4" />
        <span>{{ $t('settings.user.back') }}</span>
      </button>
    </div>

    <div class="settings-container">
      <header class="settings-header animate-slide-down">
        <div class="header-content">
          <h1 class="title-gradient" data-testid="user-settings-title">{{ $t('settings.user.title') }}</h1>
          <p class="subtitle">{{ $t('settings.user.subtitle') }}</p>
        </div>
      </header>

      <div class="settings-content animate-fade-in">
        <div class="settings-layout">
          <SettingsSidebarNav :vm="rawVm" :groups="groups" />

          <main class="settings-main glass-panel">
            <transition name="fade-slide" mode="out-in">
              <SettingsGeneralSection v-if="vm.activeSection === 'general'" key="general" :vm="rawVm" />
              <SettingsConnectedAccountsSection v-else-if="vm.activeSection === 'connected_accounts'" key="connected_accounts" />
              <SettingsAppearanceSection v-else-if="vm.activeSection === 'appearance'" key="appearance" :vm="rawVm" />
              <WebhookSettingsSection v-else-if="vm.activeSection === 'webhook_personal'" key="webhook_personal" scope="personal" />
            </transition>
          </main>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped src="@/styles/settings/shell.css"></style>

<style scoped>
.user-settings-page {
  min-height: 100vh;
  background:
    radial-gradient(circle at 12% 8%, rgba(14, 165, 233, 0.08), transparent 32%),
    radial-gradient(circle at 88% 0%, rgba(37, 99, 235, 0.07), transparent 30%),
    var(--color-bg-base, #f8fafc);
}

.user-settings-topbar {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 1rem;
  max-width: 1440px;
  margin: 0 auto;
  padding: 1.25rem 2.5rem 0;
}

.user-settings-back {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.45rem 0.8rem;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.8);
  color: #475569;
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.user-settings-back:hover {
  border-color: #7dd3fc;
  color: #0369a1;
  background: #f0f9ff;
}

@media (max-width: 640px) {
  .user-settings-topbar {
    padding: 1rem 1rem 0;
  }
}
</style>
