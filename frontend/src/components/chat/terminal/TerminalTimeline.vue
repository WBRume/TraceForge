<script setup lang="ts">
import type { TerminalTimelineEntry } from '@/utils/chat-terminal/timeline-types'
import TerminalStatusBlock from './TerminalStatusBlock.vue'
import TerminalToolUseBlock from './TerminalToolUseBlock.vue'

const props = defineProps<{
  entries: TerminalTimelineEntry[]
  loadingMore: boolean
  hasMore: boolean
  highlightedLogId?: string | null
  formatTime: (value: string) => string
  formatToolInput: (value: unknown) => string
  t: (key: string, values?: Record<string, unknown>) => string
}>()

const emit = defineEmits<{
  (e: 'hitl-submit', cardId: string, response: string): void
}>()

const resolveInlineClasses = (entry: TerminalTimelineEntry): string[] => {
  const classes = [`kind-${entry.kind}`]
  if (entry.kind === 'command' && entry.tone) {
    classes.push(`tone-${entry.tone}`)
  }
  return classes
}

const resolveMessageClasses = (entry: Extract<TerminalTimelineEntry, { kind: 'message' }>): string[] => {
  const role = String(entry.role || 'system').toLowerCase()
  const messageType = String(entry.messageType || 'text').toLowerCase()
  return [
    'line-block',
    'kind-message',
    `role-${role}`,
    `msgtype-${messageType}`,
  ]
}

const isHighlightedLog = (entry: TerminalTimelineEntry): boolean => (
  Boolean(entry.sourceLogId && props.highlightedLogId && entry.sourceLogId === props.highlightedLogId)
)
</script>

<template>
  <div class="terminal-timeline">
    <div v-if="props.loadingMore" class="timeline-tip">{{ props.t('common.loading') }}</div>
    <div v-else-if="props.hasMore" class="timeline-tip">{{ props.t('common.load_more') }}</div>

    <template v-for="entry in props.entries" :key="entry.id">
      <TerminalStatusBlock
        v-if="entry.kind === 'status' || entry.kind === 'hitl' || entry.kind === 'result'"
        :entry="entry"
        :format-time="props.formatTime"
        :t="props.t"
        @hitl-submit="(cardId, response) => emit('hitl-submit', cardId, response)"
      />

      <div v-else-if="entry.kind === 'message'" :class="resolveMessageClasses(entry)">
        <div class="line-meta">
          <span class="meta-title message-role">{{ entry.role }}</span>
          <span class="meta-time">{{ props.formatTime(entry.createdAt) }}</span>
        </div>
        <pre class="line-content">{{ entry.content }}</pre>
      </div>

      <TerminalToolUseBlock
        v-else-if="entry.kind === 'tool_use'"
        :entry="entry"
        :data-log-id="entry.sourceLogId || undefined"
        :class="{ 'highlighted-log': isHighlightedLog(entry) }"
        :format-time="props.formatTime"
        :format-tool-input="props.formatToolInput"
        :t="props.t"
      />

      <div
        v-else-if="entry.kind === 'tool_result'"
        class="line-block"
        :class="[entry.isError ? 'tool-result-error' : 'tool-result-success', { 'highlighted-log': isHighlightedLog(entry) }]"
        :data-log-id="entry.sourceLogId || undefined"
      >
        <div class="line-meta">
          <span class="meta-title">tool_result</span>
          <span class="meta-time">{{ props.formatTime(entry.createdAt) }}</span>
        </div>
        <pre class="line-content">{{ entry.output }}</pre>
      </div>

      <div
        v-else-if="entry.kind === 'log'"
        class="line-block kind-log"
        :class="{ 'highlighted-log': isHighlightedLog(entry) }"
        :data-log-id="entry.sourceLogId || undefined"
      >
        <div class="line-meta">
          <span class="meta-title">log</span>
          <span class="meta-time">{{ props.formatTime(entry.createdAt) }}</span>
        </div>
        <pre class="line-content">{{ entry.content }}</pre>
      </div>

      <div v-else class="line-inline" :class="resolveInlineClasses(entry)">
        <span class="inline-time">{{ props.formatTime(entry.createdAt) }}</span>
        <span class="inline-content">{{ entry.content }}</span>
      </div>
    </template>

    <div v-if="props.entries.length === 0" class="timeline-empty">
      {{ props.t('chat.cli_timeline_empty') }}
    </div>
  </div>
</template>

<style scoped>
.terminal-timeline {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.timeline-tip {
  font-size: 12px;
  color: #8093ad;
  text-align: center;
}

.timeline-empty {
  border: 1px dashed #2a3a53;
  border-radius: 10px;
  padding: 14px;
  text-align: center;
  color: #7d8fa8;
  font-size: 12px;
}

.line-block {
  border: 1px solid #243044;
  border-radius: 10px;
  background: #0d1523;
  padding: 8px;
}

.line-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: #8ba0bc;
  margin-bottom: 4px;
}

.meta-title {
  color: #d4deea;
}

.meta-time {
  color: #8ba0bc;
}

.line-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: #d4deea;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
}

.line-inline {
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  display: flex;
  gap: 8px;
  color: #c3cedd;
}

.line-block.kind-message.role-user .message-role {
  color: #8fc5ff;
}

.line-block.kind-message.role-user .line-content {
  color: #b9dcff;
}

.line-block.kind-message.role-assistant .message-role {
  color: #79e2b0;
}

.line-block.kind-message.role-assistant .line-content {
  color: #bbf2dd;
}

.line-block.kind-message.role-system .message-role {
  color: #f2c36c;
}

.line-block.kind-message.role-system .line-content {
  color: #f8ddb0;
}

.line-block.kind-message.msgtype-init_reason .line-content {
  color: #f4d295;
}

.line-block.highlighted-log,
:deep(.highlighted-log) {
  border-color: #38bdf8;
  box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.5), 0 0 18px rgba(56, 189, 248, 0.22);
}

.line-block.tool-result-success .meta-title {
  color: #79e2b0;
}

.line-block.tool-result-error .meta-title {
  color: #f39eb5;
}

.line-block.tool-result-error .line-content {
  color: #f6c4d1;
}

.line-inline.kind-command {
  color: #79e2b0;
}

.line-inline.kind-command.tone-query {
  color: #8fc5ff;
}

.line-inline.kind-command.tone-operate {
  color: #79e2b0;
}

.line-inline.kind-command.tone-state {
  color: #b8c6db;
}

.line-inline.kind-command.tone-danger {
  color: #f39eb5;
}

.line-inline.kind-command.tone-local {
  color: #f2c36c;
}

.line-inline.kind-success {
  color: #79e2b0;
}

.line-inline.kind-warning {
  color: #f2c36c;
}

.line-inline.kind-error {
  color: #f39eb5;
}

.inline-time {
  color: #70839d;
  flex-shrink: 0;
}

.inline-content {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
