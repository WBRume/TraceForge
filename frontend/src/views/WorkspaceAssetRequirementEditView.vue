<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@/components/icons'
import RequirementEditForm from '@/components/workspace-assets/requirements/RequirementEditForm.vue'
import { useRequirementTaskCreation } from '@/composables/useRequirementTaskCreation'
import { useWorkspaceAssets } from '@/composables/useWorkspaceAssets'
import type { RequirementMutationPayload, RequirementSummary } from '@/types/workspaceAssets'
import { isCanvasRoute } from '@/router/workspaceAssetPresentation'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const wsId = computed(() => String(route.params.wsId || ''))
const requirementId = computed(() => String(route.params.requirementId || ''))
const embedded = computed(() => isCanvasRoute(route))
const createChild = computed(() => (route.meta?.assetOperation ?? route.name) === 'workspaceAssetsRequirementChild')
const record = shallowRef<RequirementSummary | null>(null)
const saving = shallowRef(false)
const { loading, error, loadRequirementDetail, createRequirement, updateRequirement } = useWorkspaceAssets()
const { canManageRequirements } = useRequirementTaskCreation(() => wsId.value)
const prefix = 'workspace_assets.requirements.'
const target = computed(() => {
  const detail = { name: 'workspaceAssetsRequirementDetail', params: { wsId: wsId.value, requirementId: requirementId.value } }
  const candidate = route.query.back
  if (typeof candidate !== 'string' || !candidate.startsWith('/') || candidate.startsWith('//')) return detail
  const resolved = router.resolve(candidate)
  if (resolved.params.wsId === wsId.value && (resolved.name === 'workspaceAssetsRequirements'
    || (resolved.name === detail.name && resolved.params.requirementId === requirementId.value))) {
    return resolved.fullPath
  }
  return detail
})

watch([wsId, requirementId], async ([workspaceId, id], _, onCleanup) => {
  let cancelled = false
  onCleanup(() => { cancelled = true })
  record.value = null
  const next = await loadRequirementDetail(workspaceId, id)
  if (!cancelled) record.value = next?.requirement ?? null
}, { immediate: true })

async function save(payload: RequirementMutationPayload) {
  if (saving.value || !record.value || !canManageRequirements.value) return
  const workspaceId = wsId.value
  const id = record.value.id
  const isChild = createChild.value
  saving.value = true
  try {
    const result = isChild
      ? await createRequirement(workspaceId, { ...payload, parent_requirement_id: id })
      : await updateRequirement(workspaceId, id, payload)
    if (!result || record.value?.id !== id || wsId.value !== workspaceId) return
    ElMessage.success(t('workspace_assets.delivery.saved'))
    const destination = isChild
      ? { name: 'workspaceAssetsRequirementDetail', params: { wsId: workspaceId, requirementId: result.requirement.id } }
      : target.value
    await router.replace(destination)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <main class="requirement-editor" :class="{ embedded }">
    <header>
      <div class="editor-heading">
        <RouterLink v-if="!embedded" class="back-link" :to="target">
          <ArrowLeft class="back-icon" aria-hidden="true" />
          <span>{{ t('common.back') }}</span>
        </RouterLink>
        <h1 v-if="!embedded">{{ t(createChild ? prefix + 'table.add_child' : 'workspace_assets.delivery.edit') }}</h1>
      </div>
      <div v-if="record && canManageRequirements" class="actions">
        <el-button @click="router.push(target)">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" native-type="submit" form="requirement-edit-form" :loading="saving">
          {{ t(prefix + 'actions.save') }}
        </el-button>
      </div>
    </header>
    <el-alert v-if="error" type="error" :closable="false" :title="error" />
    <div v-loading="loading && !record">
      <RequirementEditForm v-if="record && canManageRequirements" :key="`${record.id}:${createChild}`"
        :workspace-id="wsId" :requirement="record" :create-child="createChild" @submit="save" />
    </div>
  </main>
</template>

<style scoped src="../components/workspace-assets/asset-back-link.css"></style>
<style scoped>
.requirement-editor { display: grid; gap: 16px; padding: 24px 30px; min-height: 100%; align-content: start; }
.requirement-editor header { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 10px; }
.editor-heading { display: grid; gap: 12px; }
.requirement-editor h1 { margin: 0; font-size: 22px; font-weight: 650; }
.actions { display: flex; align-items: center; }
.requirement-editor.embedded { padding: 16px; background: #f8fafc; }
.requirement-editor.embedded header { justify-content: flex-end; }
@container (max-width: 760px) {
  .requirement-editor.embedded :deep(.form-grid) { grid-template-columns: minmax(0, 1fr); gap: 12px; }
}
@media (max-width: 720px) { .requirement-editor { padding: 14px; } }
</style>
