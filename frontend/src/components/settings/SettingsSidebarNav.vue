<script setup lang="ts">
import { proxyRefs } from 'vue'
import { ChevronRight } from 'lucide-vue-next'
import type { SettingsViewModel } from '@/composables/useSettingsViewModel'

const props = defineProps<{ vm: SettingsViewModel }>()
const vm = proxyRefs(props.vm)
</script>

<template>
  <aside class="settings-sidebar glass-panel">
    <nav class="sidebar-nav">
      <button
        v-for="section in vm.settingsSections"
        :key="section.id"
        class="nav-item"
        :class="{ active: vm.activeSection === section.id, disabled: section.disabled }"
        :disabled="Boolean(section.disabled)"
        @click="vm.activeSection = section.id"
      >
        <div class="nav-item-icon">
          <component :is="section.icon" class="w-5 h-5" />
        </div>
        <div class="nav-item-text">
          <span class="nav-label">{{ $t(section.label) }}</span>
          <span v-if="section.disabled" class="coming-soon">Soon</span>
        </div>
        <ChevronRight v-if="vm.activeSection === section.id" class="w-4 h-4 ml-auto" />
      </button>
    </nav>
  </aside>
</template>

<style scoped src="@/styles/settings/settings-view-shared.css"></style>


