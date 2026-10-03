<script setup lang="ts">
import { usePinnedFloatsStore } from '@/stores/pinnedFloats'
import { Pin } from '@/components/icons'
const props = defineProps<{ taskId: string; taskName: string; workspaceId: string; workspaceName: string }>()
const store = usePinnedFloatsStore()
const pin = () => store.pinTask({ id: props.taskId, name: props.taskName, workspaceId: props.workspaceId, workspaceName: props.workspaceName })
</script>
<template><button type="button" class="btn-micro" title="钉在窗口中" @click="pin"><Pin class="w-4 h-4" /><span>钉在窗口中</span></button></template>
