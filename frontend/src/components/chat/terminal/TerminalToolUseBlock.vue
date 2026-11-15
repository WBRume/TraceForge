<script setup lang="ts">
import { computed } from 'vue'

import { formatToolUsePayload } from '@/utils/chat-terminal/formatToolUsePayload'
import type { TerminalToolUseEntry } from '@/utils/chat-terminal/timeline-types'

const props = defineProps<{
  entry: TerminalToolUseEntry
  formatTime: (value: string) => string
  formatToolInput: (value: unknown) => string
  t: (key: string, values?: Record<string, unknown>) => string
}>()

const readable = computed(() => formatToolUsePayload(props.entry.toolInput, props.formatToolInput))
const activity = computed(() => props.entry.activity)

type ToolTone =
  | 'mcp'
  | 'skill'
  | 'web-search'
  | 'web-fetch'
  | 'read'
  | 'search'
  | 'write'
  | 'execute'
  | 'network'
  | 'validate'
  | 'danger'
  | 'state'

const hasAny = (source: string, tokens: string[]): boolean => {
  return tokens.some((token) => source.includes(token))
}

const toolTone = computed<ToolTone>(() => {
  if (activity.value?.kind === 'mcp') return 'mcp'
  if (activity.value?.kind === 'skill') return 'skill'
  if (activity.value?.kind === 'web_search') return 'web-search'
  if (activity.value?.kind === 'web_fetch') return 'web-fetch'

  const toolName = props.entry.toolName.toLowerCase()
  if (toolName.startsWith('mcp__')) return 'mcp'
  if (toolName === 'websearch' || toolName === 'web_search') return 'web-search'
  if (toolName === 'webfetch' || toolName === 'web_fetch') return 'web-fetch'
  if (hasAny(toolName, ['bash', 'shell', 'terminal', 'command'])) return 'execute'

  if (hasAny(toolName, ['skill'])) {
    return 'skill'
  }

  if (hasAny(toolName, ['read'])) {
    return 'read'
  }

  if (hasAny(toolName, ['grep', 'search', 'find', 'query'])) {
    return 'search'
  }

  if (hasAny(toolName, ['write', 'edit', 'create', 'update', 'patch'])) {
    return 'write'
  }

  if (hasAny(toolName, ['fetch', 'download', 'request', 'http', 'api'])) {
    return 'network'
  }

  if (hasAny(toolName, ['check', 'status', 'lint', 'test', 'verify', 'validate'])) {
    return 'validate'
  }

  if (hasAny(toolName, ['delete', 'remove', 'interrupt', 'clear', 'kill'])) {
    return 'danger'
  }

  if (hasAny(toolName, ['run', 'exec'])) {
    return 'execute'
  }

  return 'state'
})
</script>

<template>
  <div class="line-block kind-tool" :class="`tone-${toolTone}`">
    <div class="line-meta">
      <span class="meta-title">
        tool_use · {{ props.entry.toolName }}
        <template v-if="activity"> · {{ activity.agent }} · {{ activity.kind }}</template>
        <template v-if="activity?.mcp_server"> · {{ activity.mcp_server }}</template>
      </span>
      <time class="meta-time" :datetime="props.entry.createdAt" :title="activity?.occurred_at || props.entry.createdAt">
        {{ props.formatTime(props.entry.createdAt) }}
      </time>
    </div>

    <div v-if="readable.fields.length > 0" class="tool-fields">
      <div v-for="field in readable.fields" :key="field.key" class="tool-field">
        <span class="field-label">{{ field.label }}</span>
        <pre class="field-value" :class="{ monospace: field.monospace, multiline: field.multiline }">{{ field.value }}</pre>
      </div>
    </div>

    <details v-if="readable.raw" class="raw-details">
      <summary>{{ props.t('chat.cli_tool_raw_payload') }}</summary>
      <pre class="raw-content">{{ readable.raw }}</pre>
    </details>
  </div>
</template>

<style scoped>
.line-block.kind-tool {
  border: 1px solid #243044;
  border-inline-start: 3px solid var(--tool-accent);
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
  margin-bottom: 6px;
}

.meta-title {
  color: var(--tool-accent);
}

.meta-time {
  color: #8ba0bc;
}

.tool-fields {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tool-field {
  border: 1px solid #203049;
  background: #09101d;
  border-radius: 8px;
  padding: 6px 8px;
}

.field-label {
  display: inline-block;
  font-size: 11px;
  color: var(--tool-accent);
  margin-bottom: 4px;
}

.field-value {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  color: #d4deea;
}

.field-value.monospace {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}

.field-value.multiline {
  line-height: 1.45;
}

.raw-details {
  margin-top: 8px;
  border-top: 1px dashed #243044;
  padding-top: 6px;
}

.raw-details summary {
  cursor: pointer;
  color: #7f92ac;
  font-size: 12px;
}

.raw-content {
  margin-top: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 11px;
  color: #afc0d8;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
}

.tone-mcp {
  --tool-accent: #c7adff;
}

.tone-skill {
  --tool-accent: #ffb86b;
}

.tone-web-search {
  --tool-accent: #5fd7ff;
}

.tone-web-fetch {
  --tool-accent: #6af2d4;
}

.tone-read {
  --tool-accent: #7fb6ff;
}

.tone-search {
  --tool-accent: #e6c875;
}

.tone-write {
  --tool-accent: #e9a9e8;
}

.tone-execute {
  --tool-accent: #c8d4e8;
}

.tone-network {
  --tool-accent: #a5c6c8;
}

.tone-validate {
  --tool-accent: #d9e582;
}

.tone-danger {
  --tool-accent: #ffada0;
}

.tone-state {
  --tool-accent: #a7b4c8;
}
</style>
