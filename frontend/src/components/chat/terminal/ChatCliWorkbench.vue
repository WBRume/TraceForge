<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { useChatTerminalController, type ChatTerminalBridge } from '@/composables/chat-terminal/useChatTerminalController'
import { mergeTerminalTimeline } from '@/utils/chat-terminal/mergeTerminalTimeline'
import TerminalCommandInput from './TerminalCommandInput.vue'
import TerminalTimeline from './TerminalTimeline.vue'
import AnnotationTray from '../annotations/AnnotationTray.vue'

const props = defineProps<{
  vm: ChatTerminalBridge
}>()

const timelineContainer = ref<HTMLElement | null>(null)
const commandInput = ref<InstanceType<typeof TerminalCommandInput> | null>(null)
const loadingOlderFromScroll = ref(false)

const controller = useChatTerminalController(props.vm)

const refocusInput = async () => {
  await commandInput.value?.focusInput()
}

const timelineEntries = computed(() => {
  const merged = mergeTerminalTimeline({
    messages: props.vm.messages,
    terminalLogs: props.vm.terminalLogs,
    localEchoes: controller.localEchoes.value,
    statusCards: props.vm.statusCards,
    hitlCards: props.vm.activeHitlCards,
    resultHistory: Array.isArray(props.vm.resultsSummary?.history) ? props.vm.resultsSummary.history : [],
  })
  const clearSince = controller.clearSinceMs.value
  if (clearSince === null) return merged
  return merged.filter((entry) => entry.createdMs >= clearSince)
})

const inputPlaceholder = computed(() => {
  if (!props.vm.currentTask?.id) return props.vm.t('chat.empty_hint')
  return props.vm.t('chat.cli_input_placeholder')
})

const handleTimelineScroll = async () => {
  const container = timelineContainer.value
  if (!container) return
  if (container.scrollTop > 48) return
  if (!(props.vm.hasMore || props.vm.hasMoreTerminalLogs) || props.vm.loadingMore || loadingOlderFromScroll.value) return
  const taskId = props.vm.currentTask?.id
  loadingOlderFromScroll.value = true
  const previousHeight = container.scrollHeight
  try {
    if (props.vm.hasMore) await props.vm.loadOlderMessages()
    if (props.vm.currentTask?.id !== taskId) return
    if (props.vm.hasMoreTerminalLogs) await props.vm.loadOlderTerminalLogs()
    await nextTick()
    if (props.vm.currentTask?.id === taskId) container.scrollTop += container.scrollHeight - previousHeight
  } finally {
    loadingOlderFromScroll.value = false
  }
}

const submitHitl = (cardId: string, response: string) => {
  props.vm.submitHitl(cardId, response)
}

const submitCommand = async () => {
  await controller.submitInput()
  await refocusInput()
}

watch(
  () => props.vm.currentTask?.id || '',
  () => {
    controller.resetForTaskChange()
    void refocusInput()
  },
)

onMounted(() => {
  props.vm.setTerminalContainer(timelineContainer.value)
  void refocusInput()
})

onBeforeUnmount(() => {
  props.vm.setTerminalContainer(null)
})
</script>

<template>
  <section class="cli-workbench">
    <div ref="timelineContainer" class="cli-timeline-shell" @scroll="handleTimelineScroll">
      <TerminalTimeline
        :entries="timelineEntries"
        :loading-more="vm.loadingMore || loadingOlderFromScroll"
        :has-more="vm.hasMore || vm.hasMoreTerminalLogs"
        :highlighted-log-id="vm.highlightedTerminalLogId"
        :format-time="vm.formatTime"
        :format-tool-input="vm.formatToolInput"
        :t="vm.t"
        @hitl-submit="submitHitl"
      />
    </div>

    <div v-if="vm.annotations?.items.value.length" class="cli-annotations"><AnnotationTray :disabled="controller.commandExecuting.value" /></div>
    <TerminalCommandInput
      ref="commandInput"
      :model-value="controller.inputValue.value"
      :disabled="!vm.currentTask?.id || Boolean(vm.initializingTask)"
      :busy="controller.commandExecuting.value"
      :submit-blocked="controller.submitBlocked.value"
      :has-context="Boolean(vm.annotations?.items.value.length)"
      :placeholder="inputPlaceholder"
      @update:model-value="(value) => { controller.inputValue.value = value }"
      @submit="submitCommand"
      @tab-complete="controller.completeInput"
      @history-prev="controller.browseHistoryPrev"
      @history-next="controller.browseHistoryNext"
    />

    <p class="cli-hint"><slot name="hint">{{ vm.t('chat.cli_hint') }}</slot></p>
  </section>
</template>

<style scoped>
.cli-annotations { background: #fff; border-radius: 10px; padding: 6px 10px; }
.cli-workbench {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
  padding: 0 var(--space-4) var(--space-4);
  gap: 10px;
}

.cli-timeline-shell {
  flex: 1;
  min-height: 0;
  overflow: auto;
  --timeline-top: var(--cli-timeline-inset, calc(var(--chat-header-bottom, 0px) + var(--space-2)));
  padding-block-start: var(--timeline-top);
  scroll-padding-block-start: var(--timeline-top);
  scrollbar-color: #33445f transparent;
}

.cli-hint {
  margin: 0;
  font-size: 12px;
  color: #7f92ac;
}
</style>
