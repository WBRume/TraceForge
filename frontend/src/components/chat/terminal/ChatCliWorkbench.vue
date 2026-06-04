<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { useChatTerminalController, type ChatTerminalBridge } from '@/composables/chat-terminal/useChatTerminalController'
import { mergeTerminalTimeline } from '@/utils/chat-terminal/mergeTerminalTimeline'
import TerminalCommandInput from './TerminalCommandInput.vue'
import TerminalTimeline from './TerminalTimeline.vue'

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
  if (!props.vm.hasMore || props.vm.loadingMore || loadingOlderFromScroll.value) return
  loadingOlderFromScroll.value = true
  const previousHeight = container.scrollHeight
  await props.vm.loadOlderMessages()
  await nextTick()
  const delta = container.scrollHeight - previousHeight
  container.scrollTop = delta + container.scrollTop
  loadingOlderFromScroll.value = false
}

const submitHitl = (cardId: string, response: string) => {
  props.vm.submitHitl(cardId, response)
}

const useQuickCommand = (command: string) => {
  controller.inputValue.value = command
  void refocusInput()
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

watch(
  () => timelineEntries.value.length,
  async () => {
    if (props.vm.loadingMore || loadingOlderFromScroll.value) return
    await nextTick()
    if (timelineContainer.value) {
      timelineContainer.value.scrollTop = timelineContainer.value.scrollHeight
    }
    void refocusInput()
  },
)

onMounted(() => {
  void refocusInput()
})
</script>

<template>
  <section class="cli-workbench glass-panel">
    <header class="cli-toolbar">
      <div class="cli-toolbar-left">
        <h3 class="cli-title">{{ vm.t('chat.cli_title') }}</h3>
        <span class="cli-status">{{ vm.currentTask?.status || '-' }}</span>
      </div>
      <div class="cli-shortcuts">
        <button class="chip-btn chip-query" @click="useQuickCommand('/help')">/help</button>
        <button class="chip-btn chip-query" @click="useQuickCommand('/status')">/status</button>
        <button class="chip-btn chip-danger" @click="useQuickCommand('/interrupt')">/interrupt</button>
        <button class="chip-btn chip-local" @click="useQuickCommand('/clear')">/clear</button>
      </div>
    </header>

    <div ref="timelineContainer" class="cli-timeline-shell" @scroll="handleTimelineScroll">
      <TerminalTimeline
        :entries="timelineEntries"
        :loading-more="vm.loadingMore"
        :has-more="vm.hasMore"
        :highlighted-log-id="vm.highlightedTerminalLogId"
        :format-time="vm.formatTime"
        :format-tool-input="vm.formatToolInput"
        :t="vm.t"
        @hitl-submit="submitHitl"
      />
    </div>

    <TerminalCommandInput
      ref="commandInput"
      :model-value="controller.inputValue.value"
      :disabled="!vm.currentTask?.id"
      :busy="controller.commandExecuting.value"
      :placeholder="inputPlaceholder"
      @update:model-value="(value) => { controller.inputValue.value = value }"
      @submit="submitCommand"
      @tab-complete="controller.completeInput"
      @history-prev="controller.browseHistoryPrev"
      @history-next="controller.browseHistoryNext"
    />

    <p class="cli-hint">{{ vm.t('chat.cli_hint') }}</p>
  </section>
</template>

<style scoped>
.cli-workbench {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 12px;
  gap: 10px;
  background: linear-gradient(180deg, #0b1423 0%, #060b15 100%);
  border: 1px solid #1f2c42;
}

.cli-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.cli-toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cli-title {
  margin: 0;
  font-size: 14px;
  color: #d4deea;
}

.cli-status {
  font-size: 12px;
  color: #8ba0bc;
}

.cli-shortcuts {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.chip-btn {
  border: 1px solid #2a3a53;
  border-radius: 999px;
  background: #0d1728;
  color: #a9b8cc;
  font-size: 11px;
  padding: 4px 8px;
  cursor: pointer;
}

.chip-btn.chip-query {
  border-color: #244f82;
  color: #8fc5ff;
}

.chip-btn.chip-danger {
  border-color: #6d3046;
  color: #f39eb5;
}

.chip-btn.chip-local {
  border-color: #7a6022;
  color: #f2c36c;
}

.cli-timeline-shell {
  flex: 1;
  min-height: 0;
  overflow: auto;
  border-radius: 10px;
  border: 1px solid #1f2c42;
  background: rgba(5, 10, 18, 0.8);
  padding: 10px;
}

.cli-hint {
  margin: 0;
  font-size: 12px;
  color: #7f92ac;
}

@media (max-width: 900px) {
  .cli-workbench {
    padding: 10px;
  }
}
</style>
