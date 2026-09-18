<!-- NewTaskModal: 新建任务弹窗入口。
     只负责遮罩层、“按住拖出”关闭手势与对话框的按需挂载：
     show=true 时挂载 TaskCreateDialog（状态全新开始），
     show=false 时整体销毁——无需任何复位 / 重载协调。 -->
<script setup lang="ts">
import TaskCreateDialog from './TaskCreateDialog.vue'
import { useOverlayCloseGesture } from './composables/useOverlayCloseGesture'
import type { TaskCreatedEvent } from './types'

defineProps<{
  show: boolean
  wsId: string
}>()

const emit = defineEmits<{
  close: []
  created: [event: TaskCreatedEvent]
}>()

const gesture = useOverlayCloseGesture(() => emit('close'))
</script>

<template>
  <div v-if="show" class="modal-overlay" v-on="gesture.handlers">
    <TaskCreateDialog :ws-id="wsId" @close="emit('close')" @created="emit('created', $event)" />
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: var(--space-4);
}
</style>
