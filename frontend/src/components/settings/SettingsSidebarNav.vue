<script setup lang="ts">
import { proxyRefs } from 'vue'
import { ChevronRight } from 'lucide-vue-next'
import type { SettingsViewModel } from '@/composables/useSettingsViewModel'

const props = defineProps<{ vm: SettingsViewModel }>()
const vm = proxyRefs(props.vm)
</script>

<template>
  <aside class="settings-sidebar glass-panel">
    <nav v-for="group in [{ title: '个人设置', ids: ['general', 'connected_accounts', 'appearance', 'local_dev', 'local_service'] }, { title: '工作区设置', ids: ['members', 'agent'] }]" :key="group.title" class="sidebar-nav">
      <h3 class="group-title">{{ group.title }}</h3>
      <button
        v-for="section in vm.settingsSections.filter(item => group.ids.includes(item.id))"
        :key="section.id"
        class="nav-item"
        :class="{ active: vm.activeSection === section.id, disabled: ('disabled' in section && section.disabled) }"
        :disabled="Boolean(('disabled' in section && section.disabled))"
        @click="vm.activeSection = section.id"
      >
        <div class="nav-item-icon">
          <component :is="section.icon" class="w-5 h-5" />
        </div>
        <div class="nav-item-text">
          <span class="nav-label">{{ section.id === 'local_service' ? section.label : $t(section.label) }}</span>
          <span v-if="('disabled' in section && section.disabled)" class="coming-soon">Soon</span>
        </div>
        <ChevronRight v-if="vm.activeSection === section.id" class="w-4 h-4 ml-auto" />
      </button>
    </nav>
  </aside>
</template>

<style scoped src="@/styles/settings/settings-view-shared.css"></style>


