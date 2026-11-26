<script setup lang="ts">
import { shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { LayoutGrid } from '@/components/icons'
import { shapeDecoration, shapeOutline } from './diagramGeometry'
import { shapeLibraries, type Library, type Shape } from './diagramModel'

defineProps<{ pending: Shape | null }>()
const emit = defineEmits<{ choose: [shape: Shape]; templates: [] }>()
const { t } = useI18n()
const current = shallowRef<Library>('flow')
const libraries: Library[] = ['flow', 'uml', 'architecture', 'basic']

function drag(event: DragEvent, shape: Shape) {
  if (!event.dataTransfer) return
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData('application/x-traceforge-shape', shape)
}
</script>

<template>
  <aside class="diagram-library">
    <div class="library-title">
      <strong>{{ t('diagram.library.title') }}</strong>
      <button class="template-control" type="button" @click="emit('templates')">
        <LayoutGrid :size="15" />{{ t('diagram.templates.label') }}
      </button>
    </div>
    <nav class="library-tabs" :aria-label="t('diagram.library.title')">
      <button v-for="library in libraries" :key="library" type="button"
        :aria-pressed="current === library" @click="current = library">{{ t('diagram.library.' + library) }}</button>
    </nav>
    <div class="shape-grid">
      <button v-for="shape in shapeLibraries[current]" :key="shape" type="button" class="shape-button"
        :data-shape-option="shape" :aria-pressed="pending === shape" :title="t('diagram.shapes.' + shape)"
        draggable="true" @click="emit('choose', shape)" @dragstart="drag($event, shape)">
        <svg viewBox="0 0 50 35" aria-hidden="true">
          <g transform="translate(4 3)" stroke="#4c6c91" stroke-width="1.45" stroke-linecap="round" stroke-linejoin="round">
            <path v-if="shape === 'text'" d="M13 4 H29 M21 4 V24 M16 24 H26" fill="none" />
            <template v-else-if="shape === 'actor'">
              <circle cx="21" cy="6.4" r="3.5" fill="none" />
              <path :d="shapeDecoration(shape, 42, 32)" fill="none" />
            </template>
            <template v-else-if="shape === 'initial' || shape === 'final'">
              <circle cx="21" cy="14" r="8" :fill="shape === 'initial' ? '#4c6c91' : 'none'" />
              <circle v-if="shape === 'final'" cx="21" cy="14" r="4.5" fill="#4c6c91" stroke="none" />
            </template>
            <template v-else>
              <path :d="shapeOutline(shape, 42, 28)" :fill="shape === 'note' ? '#fff2bc' : '#eff6fd'"
                :stroke-dasharray="shape === 'frame' ? '4 3' : undefined" />
              <path v-if="shapeDecoration(shape, 42, 28)" :d="shapeDecoration(shape, 42, 28)" fill="none" />
              <path v-if="shape === 'class' || shape === 'interface'" d="M 0 9 H 42 M 0 18 H 42" fill="none" />
              <path v-if="shape === 'entity'" d="M 0 9 H 42 M 6 16 H 29 M 6 22 H 25" fill="none" />
              <path v-if="shape === 'lifeline'" d="M 21 10 V 29" stroke-dasharray="3 2" fill="none" />
            </template>
          </g>
        </svg>
        <span>{{ t('diagram.shapes.' + shape) }}</span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.diagram-library { min-width: 0; overflow: auto; border-right: 1px solid #dfe7f0; background: #fbfdff; padding: 14px 11px; }
.library-title { display: flex; align-items: center; justify-content: space-between; gap: 5px; margin: 0 3px 13px; }
.library-title strong { font-size: 13px; color: #243b56; }
.template-control { display: inline-flex; align-items: center; justify-content: center; gap: 5px; padding: 4px 6px; border: 0; border-radius: 5px; background: transparent; color: #126489; cursor: pointer; font-size: 12px; }
.template-control:hover { background: #e9f5fc; }
.library-tabs { display: flex; padding: 3px; border-radius: 7px; background: #edf2f7; gap: 2px; margin-bottom: 10px; }
.library-tabs button { flex: 1; min-width: 0; padding: 6px 2px; border: 0; border-radius: 5px; background: transparent; color: #536b84; cursor: pointer; font-size: 12px; }
.library-tabs button[aria-pressed="true"] { background: white; color: #096b99; box-shadow: 0 1px 3px #25466514; font-weight: 650; }
.shape-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px; }
.shape-button { display: grid; place-items: center; width: 100%; min-height: 67px; padding: 7px 2px 6px; gap: 3px; border: 1px solid transparent; border-radius: 7px; color: #344a64; background: transparent; cursor: grab; font-size: 11px; }
.shape-button svg { width: 46px; height: 32px; }
.shape-button span { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.shape-button:hover, .shape-button[aria-pressed="true"] { background: #edf7fd; border-color: #c7e6f9; color: #075985; }
</style>
