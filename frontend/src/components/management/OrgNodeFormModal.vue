<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import BaseSelect from '@/components/BaseSelect.vue'
import { createOrgNode, getOrgTree, updateOrgNode } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { OrgTreeNode } from '@/types/management'

const props = withDefaults(defineProps<{
  show: boolean;
  node?: OrgTreeNode | null;
  parentId?: string | null;
}>(), {
  node: null,
  parentId: null,
})

const emit = defineEmits<{
  (e: 'saved'): void;
  (e: 'cancel'): void;
}>()

const { t } = useI18n()

const isEditing = computed(() => Boolean(props.node?.id))

const form = reactive<{
  name: string;
  node_type: string;
  parent_id: string | null;
}>({
  name: '',
  node_type: 'PRODUCT_LINE',
  parent_id: null,
})

const saving = ref(false)

const orgTree = ref<OrgTreeNode[]>([])

const nodeTypeOptions = computed(() => [
  { label: t('management.org.type_product_line'), value: 'PRODUCT_LINE' },
  { label: t('management.org.type_project_group'), value: 'PROJECT_GROUP' },
])

// 可选的上级节点：根节点 + 所有产品线节点
const parentOptions = computed(() => {
  const options: { label: string; value: string | null }[] = [
    { label: t('management.org.root'), value: null },
  ]
  const collect = (nodes: OrgTreeNode[]) => {
    for (const node of nodes) {
      if (node.node_type === 'PRODUCT_LINE' && node.id) {
        options.push({ label: node.name, value: node.id })
      }
      if (node.children && node.children.length) {
        collect(node.children)
      }
    }
  }
  collect(orgTree.value)
  return options
})

const resetForm = () => {
  form.name = props.node?.name ?? ''
  form.node_type = props.node?.node_type === 'PROJECT_GROUP' ? 'PROJECT_GROUP' : 'PRODUCT_LINE'
  form.parent_id = isEditing.value ? (props.node?.parent_id ?? null) : (props.parentId ?? null)
}

const loadTree = async () => {
  try {
    const res = await getOrgTree()
    orgTree.value = res.items ?? []
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  }
}

watch(() => props.show, (visible) => {
  if (visible) {
    resetForm()
    if (!isEditing.value) {
      void loadTree()
    }
  }
})

const canSubmit = computed(() => form.name.trim().length > 0 && !saving.value)

// 新建项目组时可选择上级产品线
const showParentSelect = computed(() => {
  if (isEditing.value) {
    return props.node?.node_type === 'PROJECT_GROUP'
  }
  return form.node_type === 'PROJECT_GROUP'
})

const handleSave = async () => {
  if (!canSubmit.value) {
    ElMessage.error(t('management.common.required'))
    return
  }
  saving.value = true
  try {
    if (isEditing.value) {
      const nodeId = props.node!.id!
      const payload: { name?: string; parent_id?: string | null; order_index?: number } = {
        name: form.name.trim(),
      }
      if (props.node!.node_type === 'PROJECT_GROUP') {
        payload.parent_id = form.parent_id
      }
      await updateOrgNode(nodeId, payload)
    } else {
      await createOrgNode({
        name: form.name.trim(),
        node_type: form.node_type,
        parent_id: form.node_type === 'PROJECT_GROUP' ? form.parent_id : null,
      })
    }
    emit('saved')
    ElMessage.success(t('common.success'))
  } catch (err) {
    ElMessage.error(formatApiError(err, t('management.common.operation_failed'), t))
  } finally {
    saving.value = false
  }
}

const handleCancel = () => {
  if (saving.value) return
  emit('cancel')
}
</script>

<template>
  <div v-if="show" class="mgmt-modal-overlay" @click.self="handleCancel">
    <div class="mgmt-modal glass-panel">
      <h3>{{ isEditing ? $t('management.org.edit_node') : $t('management.common.add') }}</h3>

      <div class="mgmt-form-grid">
        <div class="mgmt-field full">
          <label>{{ $t('management.org.node_name') }}</label>
          <input v-model="form.name" class="mgmt-input" type="text" />
        </div>

        <div class="mgmt-field" :class="{ full: !showParentSelect }">
          <label>{{ $t('management.org.node_type') }}</label>
          <BaseSelect
            v-model="form.node_type"
            :options="nodeTypeOptions"
            :disabled="isEditing"
          />
        </div>

        <div v-if="showParentSelect" class="mgmt-field">
          <label>{{ $t('management.org.parent') }}</label>
          <BaseSelect v-model="form.parent_id" :options="parentOptions" />
        </div>
      </div>

      <div class="mgmt-modal-actions">
        <button class="btn-secondary" :disabled="saving" @click="handleCancel">
          {{ $t('common.cancel') }}
        </button>
        <button class="btn-primary" :disabled="!canSubmit" @click="handleSave">
          {{ saving ? $t('common.saving') : $t('common.save') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>