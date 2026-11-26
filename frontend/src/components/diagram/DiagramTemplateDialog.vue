<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import DiagramEdgeGraphic from './DiagramEdgeGraphic.vue'
import DiagramNodeGraphic from './DiagramNodeGraphic.vue'
import { diagramBounds, diagramDrawings } from './diagramGeometry'
import { isContainer } from './diagramModel'
import { createTemplate, templateNames, type DiagramTemplate } from './diagramTemplates'

const emit = defineEmits<{ close: []; select: [template: DiagramTemplate] }>()
const { t, locale } = useI18n()
const examples = computed(() => templateNames.map(name => {
  const title = t('diagram.templates.' + name)
  const doc = createTemplate(name, title, locale.value === 'zh')
  const drawings = diagramDrawings(doc.nodes, doc.edges)
  const bounds = diagramBounds(doc.nodes, drawings)
  return {
    name, title, drawings, viewBox: [bounds.left, bounds.top, bounds.width, bounds.height].join(' '),
    frames: doc.nodes.filter(node => isContainer(node.shape)), nodes: doc.nodes.filter(node => !isContainer(node.shape)),
  }
}))
</script>

<template>
  <el-dialog :model-value="true" :title="t('diagram.templates.title')" width="min(790px, 94vw)" append-to-body @close="emit('close')">
    <div class="template-grid">
      <button v-for="example in examples" :key="example.name" type="button" class="template-button"
        :data-diagram-template="example.name" @click="emit('select', example.name)">
        <svg :viewBox="example.viewBox" aria-hidden="true" font-family="Inter, 'Segoe UI', 'Microsoft YaHei UI', sans-serif">
          <DiagramNodeGraphic v-for="node in example.frames" :key="node.id" :node="node" />
          <DiagramEdgeGraphic v-for="item in example.drawings" :key="item.edge.id" :edge="item.edge" :geometry="item.geometry" />
          <DiagramNodeGraphic v-for="node in example.nodes" :key="node.id" :node="node" />
        </svg>
        <strong>{{ example.title }}</strong>
      </button>
    </div>
  </el-dialog>
</template>

<style scoped>
.template-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; max-height: 68vh; overflow: auto; padding: 1px; }
.template-button { display: grid; justify-items: stretch; padding: 0; min-width: 0; overflow: hidden; text-align: left; color: #25435f; background: white; border: 1px solid #dbe6f1; border-radius: 8px; cursor: pointer; }
.template-button svg { width: 100%; height: 92px; padding: 8px; background: #f2f7fc; pointer-events: none; }
.template-button strong { padding: 9px 11px; font-size: 13px; }
.template-button:hover { border-color: #4da3cb; background: #f5faff; }
</style>
