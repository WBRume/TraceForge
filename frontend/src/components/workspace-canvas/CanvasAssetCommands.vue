<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { BookMarked, ChevronDown, Plus } from '@/components/icons'
import { sourceIcons, type CanvasCommand } from './model'

const props = defineProps<{
  canCreateRequirement: boolean
  canCreateTask: boolean
  canCreateDocument: boolean
  hasCaseAccess: boolean
}>()
const emit = defineEmits<{ command: [command: CanvasCommand] }>()
const { t } = useI18n()
const items = computed(() => ([
  { value: 'requirement', icon: sourceIcons.requirement, allowed: props.canCreateRequirement },
  { value: 'task', icon: sourceIcons.task, allowed: props.canCreateTask },
  { value: 'case', icon: sourceIcons.case, allowed: props.canCreateTask && props.hasCaseAccess },
  { value: 'document', icon: sourceIcons.document, allowed: props.canCreateDocument },
] as const).filter(item => item.allowed))

function create(command: CanvasCommand) {
  emit('command', command)
}
</script>

<template>
  <div class="canvas-commands">
    <button v-if="hasCaseAccess" class="board-button" type="button" @click="$emit('command', 'playbooks')">
      <BookMarked :size="16" />{{ t('workspace_canvas.actions.case_tools') }}
    </button>
    <el-dropdown v-if="items.length" trigger="click" placement="bottom-end" @command="create">
      <button class="board-button primary" type="button">
        <Plus :size="17" />{{ t('workspace_canvas.actions.create') }}<ChevronDown :size="14" />
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item v-for="item in items" :key="item.value" :command="item.value"
            :icon="item.icon">{{ t(`workspace_canvas.actions.create_${item.value}`) }}</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<style scoped>
.canvas-commands { display: flex; align-items: center; gap: 6px; }
.board-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  color: #365375;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  white-space: nowrap;
  cursor: pointer;
}
.board-button:hover { border-color: #93c5fd; background: #f0f9ff; }
.board-button.primary { border-color: #0284c7; background: #0284c7; color: #fff; }
.board-button.primary:hover { border-color: #0369a1; background: #0369a1; }
</style>
