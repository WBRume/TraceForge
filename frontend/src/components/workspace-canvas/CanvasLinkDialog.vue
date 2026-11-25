<script setup lang="ts">
import { shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RequirementTaskRelation } from '@/types/workspaceAssets'
import type { SourceItem } from './model'

const props = defineProps<{ title: string; label: string; items: SourceItem[]; document: boolean; saving: boolean }>()
const emit = defineEmits<{ close: []; save: [id: string, type: RequirementTaskRelation] }>()
const { t } = useI18n()
const target = shallowRef('')
const type = shallowRef<RequirementTaskRelation>('COVERS')

function save() {
  if (props.items.some(item => item.reference.id === target.value)) emit('save', target.value, type.value)
}
</script>

<template>
  <el-dialog :model-value="true" :title="title" width="min(530px, 95vw)" :close-on-click-modal="false"
    :show-close="!saving" :close-on-press-escape="!saving" append-to-body @close="emit('close')">
    <form class="link-form" @submit.prevent="save">
      <strong>{{ label }}</strong>
      <el-select v-model="target" filterable :disabled="saving" :aria-label="t('workspace_canvas.menu.link_target')"
        :placeholder="t('workspace_canvas.menu.link_target')">
        <el-option v-for="item in items" :key="item.reference.id" :value="item.reference.id" :label="item.details.title" />
      </el-select>
      <el-select v-if="!document" v-model="type" :disabled="saving" :aria-label="t('workspace_canvas.actions.relation_type')">
        <el-option value="COVERS" :label="t('workspace_assets.requirements.relation_types.covers_short')" />
        <el-option value="RELATES_TO" :label="t('workspace_assets.requirements.relation_types.relates_to_short')" />
      </el-select>
      <footer>
        <el-button :disabled="saving" @click="emit('close')">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" native-type="submit" :disabled="!target" :loading="saving">{{ t('common.confirm') }}</el-button>
      </footer>
    </form>
  </el-dialog>
</template>

<style scoped>
.link-form { display: grid; gap: 12px; }
footer { display: flex; justify-content: flex-end; }
</style>
