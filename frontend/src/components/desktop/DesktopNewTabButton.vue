<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { Plus } from '@/components/icons'
import { WORKSPACE_HOME } from '@/types/workspaceWindows'
import { workspaceTabChoices } from './desktopTabLabels'
import { useDesktopTitleMenu } from './useDesktopTitleMenu'

const props = defineProps<{ workspaceId: string; disabled: boolean }>()
const emit = defineEmits<{ open: [path: string] }>()
const { trigger, setVisible } = useDesktopTitleMenu()
const router = useRouter()
const { t } = useI18n()
const choices = computed(() => props.workspaceId ? workspaceTabChoices(props.workspaceId, router, t) : [])

defineExpose({
  open() {
    if (props.disabled) return
    trigger.value?.focus()
    trigger.value?.click()
  },
})
</script>

<template>
  <div class="new-tab-control">
    <el-dropdown v-if="workspaceId" ref="dropdown" trigger="click" placement="bottom-start" :show-arrow="false"
      popper-class="desktop-titlebar-menu desktop-page-menu" :disabled="disabled"
      @visible-change="setVisible" @command="emit('open', String($event))">
      <button ref="trigger" class="new-tab" type="button" :disabled="disabled"
        :aria-label="t('desktop_tabs.new_tab')" :title="t('desktop_tabs.new_tab_shortcut')">
        <Plus aria-hidden="true" />
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item v-for="(choice, index) in choices" :key="choice.path" :command="choice.path"
            :divided="index === choices.length - 1">
            <div class="desktop-menu-row">
              <span class="desktop-menu-row-icon"><component :is="choice.icon" aria-hidden="true" /></span>
              <span class="desktop-menu-row-label">{{ choice.label }}</span>
            </div>
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
    <button v-else ref="trigger" class="new-tab" type="button" :disabled="disabled"
      :aria-label="t('desktop_tabs.new_tab')" :title="t('desktop_tabs.new_tab_shortcut')" @click="emit('open', WORKSPACE_HOME)">
      <Plus aria-hidden="true" />
    </button>
  </div>
</template>

<style scoped>
.new-tab-control { position: relative; display: flex; align-items: center; flex: none; }
.new-tab { width: 28px; height: 29px; display: grid; place-items: center; border: 0; border-radius: 6px; background: transparent; color: #526176; padding: 0; }
.new-tab:hover, .new-tab[aria-expanded='true'] { background: #dfe8f3; color: #075985; }
.new-tab:disabled { opacity: .45; cursor: default; }
.new-tab svg { width: 16px; height: 16px; }
</style>
