<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCircle2, RotateCcw } from 'lucide-vue-next'
import WorkflowStatusPill from './WorkflowStatusPill.vue'

const props = defineProps<{
  status: string
  canResolve: boolean
  saving: boolean
}>()

const emit = defineEmits<{
  confirm: []
  reopen: []
}>()

const { t } = useI18n()
const canConfirmResolution = computed(() => props.canResolve && props.status === 'ANSWERED')
const canReopen = computed(() => props.canResolve && props.status === 'ACCEPTED')
</script>

<template>
  <div class="conversation-state-actions">
    <WorkflowStatusPill :status="status" />
    <el-button
      v-if="canConfirmResolution"
      :disabled="saving"
      :loading="saving"
      type="primary"
      plain
      @click="emit('confirm')"
    >
      <CheckCircle2 class="button-icon" />
      {{ t('workspace_assets.task_detail.final_workflow.clarification.confirm_resolution') }}
    </el-button>
    <el-button
      v-if="canReopen"
      :disabled="saving"
      plain
      @click="emit('reopen')"
    >
      <RotateCcw class="button-icon" />
      {{ t('workspace_assets.task_detail.final_workflow.clarification.reopen') }}
    </el-button>
  </div>
</template>

<style scoped>
.conversation-state-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.button-icon {
  width: 15px;
  height: 15px;
  margin-right: 6px;
}
</style>
