<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CanvasGraphRelation, CanvasRelationType } from './model'
import { relationStyles } from './relationStyles'

const props = defineProps<{ relations: CanvasGraphRelation[]; active: CanvasRelationType | null }>()
defineEmits<{ choose: [type: CanvasRelationType] }>()
const { t } = useI18n()
const items = computed(() => {
  const types = new Set(props.relations.map(link => link.relation_type))
  return (Object.keys(relationStyles) as CanvasRelationType[]).filter(type => types.has(type))
})
</script>

<template>
  <div v-if="items.length" class="relation-legend" role="group" :aria-label="t('workspace_canvas.relation_legend')" @pointerdown.stop>
    <button v-for="type in items" :key="type" type="button" :aria-pressed="active === type" @click="$emit('choose', type)">
      <svg width="26" height="8" viewBox="0 0 26 8" aria-hidden="true">
        <path d="M 1 4 H 19" :stroke="relationStyles[type].color" :stroke-width="relationStyles[type].width"
          :stroke-dasharray="relationStyles[type].dash" />
        <path d="m 19 1 6 3 -6 3 z" :fill="relationStyles[type].color" />
      </svg>
      {{ t(`workspace_canvas.relations.${type}`) }}
    </button>
  </div>
</template>

<style scoped>
.relation-legend {
  position: absolute;
  z-index: 3;
  inset: auto auto 16px 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 1px 3px;
  max-width: min(760px, calc(100% - 190px));
  padding: 4px;
  background: #fffc;
  border: 1px solid #dce6f0;
  border-radius: 9px;
  box-shadow: 0 4px 12px #263c5d12;
}
.relation-legend button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 5px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: #475569;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}
.relation-legend button:is(:hover, :focus-visible, [aria-pressed='true']) { background: #e0f2fe; color: #1e3a5c; }
@media (max-width: 650px) { .relation-legend { inset: auto auto 10px 6px; } }
</style>
