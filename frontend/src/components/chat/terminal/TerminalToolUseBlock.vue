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

type ToolTone =
  | 'skill'
  | 'script'
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

const isScriptCommand = (commandText: string): boolean => {
  return hasAny(commandText, [
    'python ',
    'python3 ',
    'python.exe',
    '\\python',
    '/python',
    'node ',
    'node.exe',
    'ruby ',
    'perl ',
    'php ',
    'pwsh ',
    'powershell ',
    '.venv\\scripts\\python',
    '.venv/scripts/python',
  ])
}

const resolveToolTone = (): ToolTone => {
  const toolName = String(props.entry.toolName || '').toLowerCase()
  const commandField = readable.value.fields.find((field) => field.key === 'command')
  const commandText = String(commandField?.value || '').toLowerCase()

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

  if (hasAny(toolName, ['bash', 'shell', 'terminal', 'command'])) {
    if (hasAny(commandText, [' rm ', 'remove-item', 'del ', 'delete ', 'rmdir ', 'drop '])) {
      return 'danger'
    }

    if (hasAny(commandText, ['curl ', 'wget ', 'invoke-webrequest', 'requests.', 'axios', 'fetch('])) {
      return 'network'
    }

    if (hasAny(commandText, ['pytest', 'vitest', 'jest', 'npm test', 'pnpm test', 'ruff', 'mypy', 'eslint', 'compileall', 'build'])) {
      return 'validate'
    }

    if (hasAny(commandText, ['cat ', 'type ', 'rg ', 'grep ', 'select-string', 'get-content', 'ls ', 'dir '])) {
      return 'read'
    }

    if (hasAny(commandText, ['echo ', 'set-content', 'out-file', '>>', '> ', 'apply_patch'])) {
      return 'write'
    }

    if (isScriptCommand(commandText)) {
      return 'script'
    }

    return 'execute'
  }

  if (hasAny(toolName, ['run', 'exec'])) {
    return 'execute'
  }

  return 'state'
}

const toolTone = computed(() => resolveToolTone())
</script>

<template>
  <div class="line-block kind-tool" :class="`tone-${toolTone}`">
    <div class="line-meta">
      <span class="meta-title">tool_use · {{ props.entry.toolName }}</span>
      <span class="meta-time">{{ props.formatTime(props.entry.createdAt) }}</span>
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
  margin-bottom: 6px;
}

.meta-title {
  color: #d4deea;
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
  color: #8ba0bc;
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

.line-block.kind-tool.tone-skill .meta-title,
.line-block.kind-tool.tone-skill .field-label {
  color: #ffb86b;
}

.line-block.kind-tool.tone-script .meta-title,
.line-block.kind-tool.tone-script .field-label {
  color: #6af2d4;
}

.line-block.kind-tool.tone-read .meta-title,
.line-block.kind-tool.tone-read .field-label {
  color: #7fb6ff;
}

.line-block.kind-tool.tone-search .meta-title,
.line-block.kind-tool.tone-search .field-label {
  color: #5fd7ff;
}

.line-block.kind-tool.tone-write .meta-title,
.line-block.kind-tool.tone-write .field-label {
  color: #79e2b0;
}

.line-block.kind-tool.tone-execute .meta-title,
.line-block.kind-tool.tone-execute .field-label {
  color: #c8d4e8;
}

.line-block.kind-tool.tone-network .meta-title,
.line-block.kind-tool.tone-network .field-label {
  color: #7fb6ff;
}

.line-block.kind-tool.tone-validate .meta-title,
.line-block.kind-tool.tone-validate .field-label {
  color: #b8e986;
}

.line-block.kind-tool.tone-danger .meta-title,
.line-block.kind-tool.tone-danger .field-label {
  color: #f39eb5;
}

.line-block.kind-tool.tone-state .meta-title,
.line-block.kind-tool.tone-state .field-label {
  color: #f2c36c;
}
</style>
