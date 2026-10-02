<script setup lang="ts">
import NewTaskModal from '@/components/task-create/NewTaskModal.vue'
import { useProvisioningStore } from '@/stores/provisioning'
import type { RequirementOption } from '@/types/taskRail'
import type { TaskCreatedEvent } from '@/components/task-create/types'

defineProps<{ workspaceId: string; requirement: RequirementOption | null }>()
const emit = defineEmits<{ close: []; created: [event: TaskCreatedEvent] }>()
const provisioning = useProvisioningStore()
function created(event: TaskCreatedEvent) {
  provisioning.startWatching({ jobId:event.jobId, taskId:event.taskId, workspaceId:event.workspaceId })
  emit('created', event)
  emit('close')
}
</script>

<template>
  <NewTaskModal :show="Boolean(requirement)" :ws-id="workspaceId" :initial-requirement="requirement" @close="emit('close')" @created="created" />
</template>
