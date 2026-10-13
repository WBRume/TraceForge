<script setup lang="ts">
import { computed } from 'vue'
import type { SkillRuntimeEvent } from '@/types/runtimeSkillTrace'

type RuntimeSkillItem = {
  skill_id: string
  name: string
  materialized_dir?: string | null
}

const props = defineProps<{
  skills: RuntimeSkillItem[]
  selectedSkillId: string
  events: SkillRuntimeEvent[]
  loading: boolean
}>()

type TraceRow = {
  event: SkillRuntimeEvent
  skillLabel: string
  materializedDir: string
  title: string
  path: string
}

const skillsById = computed(() => {
  const map = new Map<string, RuntimeSkillItem>()
  for (const skill of props.skills || []) {
    map.set(skill.skill_id, skill)
  }
  return map
})

const skillsByMaterializedDir = computed(() => {
  const map = new Map<string, RuntimeSkillItem>()
  for (const skill of props.skills || []) {
    const materializedDir = String(skill.materialized_dir || '').trim()
    if (materializedDir) map.set(materializedDir, skill)
  }
  return map
})

const traceRows = computed<TraceRow[]>(() => (props.events || []).map((event) => {
  const materializedDir = String(event.materialized_dir || '').trim()
  const skill = (event.skill_id ? skillsById.value.get(event.skill_id) : null)
    || (materializedDir ? skillsByMaterializedDir.value.get(materializedDir) : null)
    || null
  const path = String(event.relative_path || '').trim()
  const toolName = String(event.tool_name || '').trim()
  return {
    event,
    skillLabel: skill?.name || materializedDir || '未归因',
    materializedDir,
    title: toolName || event.event_type,
    path,
  }
}))

const formatTime = (value?: string | null) => {
  if (!value) return '-'
  return new Date(value).toLocaleTimeString()
}
</script>

<template>
  <div class="trace-panel">
    <div v-if="loading" class="trace-state">加载运行证据...</div>
    <div v-else-if="traceRows.length === 0" class="trace-state">暂无可观察到的工具访问证据。</div>
    <div v-else class="trace-timeline">
      <article
        v-for="row in traceRows"
        :key="row.event.id"
        class="trace-event"
      >
        <div class="trace-marker" aria-hidden="true"></div>
        <div class="trace-event-card">
          <div class="trace-event-head">
            <time>{{ formatTime(row.event.created_at) }}</time>
            <strong>{{ row.skillLabel }}</strong>
            <small v-if="row.materializedDir && row.materializedDir !== row.skillLabel">{{ row.materializedDir }}</small>
          </div>
          <div class="trace-event-main">
            <span class="trace-event-type">{{ row.event.event_type }}</span>
            <span class="trace-tool">{{ row.title }}</span>
            <span v-if="row.path" class="trace-path">{{ row.path }}</span>
          </div>
          <div class="trace-event-meta">
            <span>{{ row.event.evidence_level }}</span>
            <span>{{ row.event.status }}</span>
          </div>
          <details v-if="row.event.tool_result_preview" class="trace-result">
            <summary>工具返回结果</summary>
            <pre>{{ row.event.tool_result_preview }}</pre>
          </details>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.trace-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 8px;
  padding: 10px;
  background: #ffffff;
}

.trace-state {
  color: #64748b;
  font-size: 11px;
  line-height: 1.45;
}

.trace-timeline {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.trace-timeline::before {
  position: absolute;
  top: 8px;
  bottom: 8px;
  left: 5px;
  width: 1px;
  background: #e2e8f0;
  content: '';
}

.trace-event {
  position: relative;
  min-width: 0;
  display: flex;
  gap: 9px;
}

.trace-marker {
  position: relative;
  z-index: 1;
  flex: 0 0 auto;
  width: 11px;
  height: 11px;
  margin-top: 11px;
  border: 2px solid #93c5fd;
  border-radius: 999px;
  background: #ffffff;
}

.trace-event-card {
  min-width: 0;
  flex: 1;
  padding: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.trace-event-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
  color: #64748b;
  font-size: 10px;
}

.trace-event-head time {
  font-variant-numeric: tabular-nums;
}

.trace-event-head strong {
  color: #0f172a;
  font-size: 11px;
}

.trace-event-head small {
  min-width: 0;
  color: #94a3b8;
  overflow-wrap: anywhere;
}

.trace-event-main {
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 5px;
  color: #334155;
  font-size: 11px;
}

.trace-event-type {
  color: #0f172a;
  font-weight: 700;
}

.trace-tool,
.trace-path {
  min-width: 0;
  overflow-wrap: anywhere;
}

.trace-path {
  color: #475569;
}

.trace-event-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.trace-event-meta span {
  border: 1px solid rgba(148, 163, 184, 0.32);
  border-radius: 999px;
  padding: 1px 6px;
  color: #64748b;
  background: #fff;
  font-size: 10px;
}

.trace-event-meta {
  margin-top: 5px;
}

.trace-result {
  margin-top: 6px;
  color: #475569;
  font-size: 11px;
}

.trace-result summary {
  cursor: pointer;
}

.trace-result pre {
  max-height: 120px;
  overflow: auto;
  margin: 6px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 11px;
}
</style>
