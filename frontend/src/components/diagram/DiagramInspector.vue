<script setup lang="ts">
import { computed, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import { hasCompartments, hasSubtitle, minNodeSize, relations, routings, CAPTION_LIMIT, CONTENT_LIMIT,
  type DiagramEdge, type DiagramNode, type EdgeEdit, type NodeEdit } from './diagramModel'
import type { InputInstance } from 'element-plus'

const props = defineProps<{ nodes: DiagramNode[]; edge: DiagramEdge | null }>()
const emit = defineEmits<{ updateNode: [patch: NodeEdit]; updateEdge: [patch: EdgeEdit] }>()
const { t } = useI18n()
const node = computed(() => props.nodes.length === 1 ? props.nodes[0] : null)
const nodeLabel = useTemplateRef<InputInstance>('nodeLabel')
const edgeLabel = useTemplateRef<InputInstance>('edgeLabel')
const relationOptions = computed(() => relations.map(value => ({ value, label: t('diagram.edges.' + value) })))
const routeOptions = computed(() => routings.map(value => ({ value, label: t('diagram.routing.' + value) })))
const fields = ['width', 'height'] as const
const colors = ['fill', 'stroke'] as const
const min = computed(() => node.value ? minNodeSize(node.value.shape) : { width: 0, height: 0 })
const labelDraft = shallowRef('')
const detailDraft = shallowRef('')
const operationsDraft = shallowRef('')

watch([
  () => node.value?.id ?? props.edge?.id,
  () => node.value?.label ?? props.edge?.label,
  () => node.value?.detail,
  () => node.value?.operations,
], ([, label, detail, operations]) => {
  labelDraft.value = label ?? ''
  detailDraft.value = detail ?? ''
  operationsDraft.value = operations ?? ''
}, { immediate: true })

function resize(field: typeof fields[number], event: Event) {
  const input = event.target as HTMLInputElement
  const value = input.valueAsNumber
  if (Number.isFinite(value) && node.value) emit('updateNode', { [field]: Math.min(100000, Math.max(min.value[field], Math.round(value))) })
  else if (node.value) input.value = String(node.value[field])
}

function color(event: Event) {
  return (event.target as HTMLInputElement).value
}

function positionMessage(event: Event) {
  const input = event.target as HTMLInputElement
  const offset = Math.min(100000, Math.max(60, Math.round(input.valueAsNumber)))
  if (Number.isFinite(offset)) emit('updateEdge', { offset })
  else if (props.edge?.offset !== undefined) input.value = String(props.edge.offset)
}

function focusLabel() {
  (nodeLabel.value ?? edgeLabel.value)?.focus()
}
defineExpose({ focusLabel })
</script>

<template>
  <aside class="diagram-inspector" :aria-label="t('diagram.fields.title')">
    <strong class="inspector-heading">{{ t('diagram.fields.title') }}</strong>
    <template v-if="node">
      <p class="inspector-subheading">{{ t('diagram.shapes.' + node.shape) }}</p>
      <label v-if="node.shape !== 'initial' && node.shape !== 'final'" class="property">
        <span>{{ t('diagram.fields.label') }}</span>
        <el-input :key="node.id" ref="nodeLabel" v-model="labelDraft" :maxlength="CAPTION_LIMIT"
          :type="node.shape === 'note' || node.shape === 'text' ? 'textarea' : 'text'" :rows="3"
          :aria-label="t('diagram.fields.label')" @change="emit('updateNode', { label: $event })" />
      </label>
      <label v-if="hasCompartments(node.shape)" class="property">
        <span>{{ t(node.shape === 'entity' ? 'diagram.fields.columns' : 'diagram.fields.attributes') }}</span>
        <el-input :key="node.id" v-model="detailDraft" type="textarea" :rows="3" :maxlength="CONTENT_LIMIT"
          :aria-label="t(node.shape === 'entity' ? 'diagram.fields.columns' : 'diagram.fields.attributes')"
          @change="emit('updateNode', { detail: $event })" />
      </label>
      <label v-else-if="hasSubtitle(node.shape)" class="property">
        <span>{{ t(node.shape === 'person' ? 'diagram.fields.role' : 'diagram.fields.subtitle') }}</span>
        <el-input :key="node.id" v-model="detailDraft" :maxlength="CAPTION_LIMIT"
          :aria-label="t(node.shape === 'person' ? 'diagram.fields.role' : 'diagram.fields.subtitle')"
          @change="emit('updateNode', { detail: $event })" />
      </label>
      <label v-if="node.shape === 'class' || node.shape === 'interface'" class="property">
        <span>{{ t('diagram.fields.operations') }}</span>
        <el-input :key="node.id" v-model="operationsDraft" type="textarea" :rows="3" :maxlength="CONTENT_LIMIT"
          :aria-label="t('diagram.fields.operations')" @change="emit('updateNode', { operations: $event })" />
      </label>
      <div class="property-grid">
        <label v-for="field in fields" :key="field" class="property">
          <span>{{ t('diagram.fields.' + field) }}</span>
          <input :value="Math.round(node[field])" type="number" :min="min[field]" max="100000" @change="resize(field, $event)">
        </label>
      </div>
      <div class="property-grid">
        <label v-for="field in colors" :key="field" class="property color-property">
          <span>{{ t('diagram.fields.' + field) }}</span>
          <input :value="node[field]" type="color" @change="emit('updateNode', { [field]: color($event) })">
        </label>
      </div>
    </template>
    <template v-else-if="edge">
      <label class="property">
        <span>{{ t('diagram.fields.label') }}</span>
        <el-input :key="edge.id" ref="edgeLabel" v-model="labelDraft" :maxlength="CAPTION_LIMIT"
          :aria-label="t('diagram.fields.label')" @change="emit('updateEdge', { label: $event })" />
      </label>
      <div class="property">
        <span>{{ t('diagram.fields.relation') }}</span>
        <BaseSelect :model-value="edge.relation" :options="relationOptions" :aria-label="t('diagram.fields.relation')"
          @update:model-value="emit('updateEdge', { relation: $event })" />
      </div>
      <div v-if="edge.offset === undefined" class="property">
        <span>{{ t('diagram.fields.routing') }}</span>
        <BaseSelect :model-value="edge.routing" :options="routeOptions" :aria-label="t('diagram.fields.routing')"
          @update:model-value="emit('updateEdge', { routing: $event })" />
      </div>
      <label v-else class="property">
        <span>{{ t('diagram.fields.offset') }}</span>
        <input :value="Math.round(edge.offset)" type="number" min="60" max="100000" @change="positionMessage">
      </label>
      <label class="property color-property">
        <span>{{ t('diagram.fields.stroke') }}</span>
        <input :value="edge.stroke" type="color" @change="emit('updateEdge', { stroke: color($event) })">
      </label>
    </template>
    <p v-else class="inspector-subheading">{{ nodes.length ? t('diagram.fields.selected', { count: nodes.length }) : t('diagram.fields.noSelection') }}</p>
  </aside>
</template>

<style scoped>
.diagram-inspector { min-width: 0; border-left: 1px solid #dfe7f0; background: #fbfdff; overflow: auto; padding: 15px 13px; color: #243b56; }
.inspector-heading { font-size: 13px; }
.inspector-subheading { margin: 12px 0 0; color: #63788f; font-size: 12px; }
.property { display: grid; gap: 5px; color: #304a65; font-size: 12px; margin-top: 13px; }
.property-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.property input[type="number"] { width: 100%; min-width: 0; padding: 6px 4px 6px 8px; border: 1px solid #d9e3ee; border-radius: 6px; background: white; color: #243b56; font: inherit; }
.color-property input { width: 100%; height: 32px; padding: 3px; border: 1px solid #d9e3ee; border-radius: 6px; background: white; cursor: pointer; }
</style>
