<script setup lang="ts">
import { proxyRefs } from 'vue'
import { Check, Languages } from 'lucide-vue-next'
import type { SettingsViewModel } from '@/composables/useSettingsViewModel'

const props = defineProps<{ vm: SettingsViewModel }>()
const vm = proxyRefs(props.vm)
</script>

<template>
  <section class="settings-section">
    <div class="section-header">
      <div class="icon-circle">
        <Languages class="w-6 h-6" />
      </div>
      <div class="section-title-group">
        <h2>{{ $t('settings.language') }}</h2>
        <p>{{ $t('settings.language_desc') }}</p>
      </div>
    </div>

    <div class="language-options">
      <div class="lang-card" :class="{ selected: vm.currentLang === 'zh' }" @click="vm.changeLanguage('zh')">
        <div class="lang-info">
          <span class="lang-name">{{ $t('settings.zh_label') }}</span>
          <span class="lang-native">{{ $t('settings.zh_native') }}</span>
        </div>
        <div class="select-indicator">
          <Check v-if="vm.currentLang === 'zh'" class="w-4 h-4" />
        </div>
      </div>

      <div class="lang-card" :class="{ selected: vm.currentLang === 'en' }" @click="vm.changeLanguage('en')">
        <div class="lang-info">
          <span class="lang-name">{{ $t('settings.en_label') }}</span>
          <span class="lang-native">{{ $t('settings.en_native') }}</span>
        </div>
        <div class="select-indicator">
          <Check v-if="vm.currentLang === 'en'" class="w-4 h-4" />
        </div>
      </div>
    </div>

    <div class="footer-note">
      <p>{{ $t('settings.applied_instantly') }}</p>
    </div>
  </section>
</template>

<style scoped src="@/styles/settings/settings-view-shared.css"></style>


