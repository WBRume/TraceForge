<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import BaseSelect from '@/components/BaseSelect.vue'
import { createRepoGroup, updateRepoGroup } from '@/services/managementApi'
import { formatApiError } from '@/utils/error'
import type { RepoGroupTreeNode } from '@/types/management'

const props = withDefaults(defineProps<{
  show: boolean;
  group?: { id: string; name: string; parent_id: string | null } | null;
  parentId?: string | null;
  groups: RepoGroupTreeNode[];
}>(), {
  group: null,
  parentId: null,
  groups: () => [],
})

const emit = defineEmits<{
  (e: 'saved'): void;
  (e: 'cancel'): void;
}>()

const { t } = useI18n()

const isEditing = computed(() => Boolean(props.group))

const form = reactive<{
  name: string;
  parent_id: string | null;
}>({
  name: '',
  parent_id: null,
})

const saving = ref(false)

const flattenedGroups = computed(() => {
  const result: { id: string; name: string }[] = []
  const walk = (nodes: RepoGroupTreeNode[], prefix: string) => {
    for (const node of nodes) {
      if (node.id !== null) {
        result.push({ id: node.id, name: prefix ? prefix + ' / ' + node.name : node.name })
        walk(node.children, node.name)
      }
    }
  }
  walk(props.groups, '')
  return result
})

const parentOptions = computed(() => {
  const options: { label: string; value: string | null }[] = [
    { label: t('management.repo_group.root'), value: null },
  ]
  for (const group of flattenedGroups.value) {
    if (isEditing.value && group.id === props.group?.id) {
      continue
    }
    options.push({ label: group.name, value: group.id })
  }
  return options
})

const resetForm = () => {
  form.name = props.group?.name ?? ''
  form.parent_id = isEditing.value ? (props.group?.parent_id ?? null) : (props.parentId ?? null)
}

watch(() => props.show, (visible) => {
  if (visible) {
    resetForm()
  }
})

const canSubmit = computed(() => form.name.trim().length > 0 && !saving.value)

const handleSave = async () => {
  if (!canSubmit.value) {
    ElMessage.error(t('management.common.required'))
    return
  }
  saving.value = true
  try {
    if (isEditing.value) {
      await updateRepoGroup(props.group!.id, {
        name: form.name.trim(),
        parent_id: form.parent_id,
      })
    } else {
      await createRepoGroup({
        name: form.name.trim(),
        parent_id: form.parent_id,
      })
    }
    emit('saved')
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
  <Teleport to="body">
    <div v-if="show" class="mgmt-modal-overlay" @click.self="handleCancel">
      <div class="mgmt-modal glass-panel">
        <h3>{{ isEditing ? $t('management.repo_group.edit') : $t('management.repo_group.add') }}</h3>

        <div class="mgmt-form-grid">
          <div class="mgmt-field full">
            <label>{{ $t('management.repo_group.name') }}</label>
            <input v-model="form.name" class="mgmt-input" type="text" />
          </div>

          <div class="mgmt-field full">
            <label>{{ $t('management.repo_group.parent') }}</label>
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
  </Teleport>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
