<!-- Workspace creation workflow: step 1 basic info. -->
<script setup lang="ts">
export interface WorkspaceBasicInfo {
  name: string
  description: string
  project_path: string
}

const props = defineProps<{
  modelValue: WorkspaceBasicInfo
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: WorkspaceBasicInfo): void
}>()

const update = (patch: Partial<WorkspaceBasicInfo>) => {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}

const onNameInput = (event: Event) => {
  update({ name: (event.target as HTMLInputElement).value })
}

const onDescriptionInput = (event: Event) => {
  update({ description: (event.target as HTMLTextAreaElement).value })
}

const onPathInput = (event: Event) => {
  update({ project_path: (event.target as HTMLInputElement).value })
}
</script>

<template>
  <div class="wf-step">
    <div class="mgmt-field">
      <label>{{ $t('workspace_create.name') }} *</label>
      <input
        :value="modelValue.name"
        type="text"
        class="mgmt-input"
        :placeholder="$t('workspace_create.name_placeholder')"
        @input="onNameInput"
      />
    </div>

    <div class="mgmt-field">
      <label>{{ $t('workspace_create.description') }}</label>
      <textarea
        :value="modelValue.description"
        class="mgmt-input"
        rows="2"
        @input="onDescriptionInput"
      ></textarea>
    </div>

    <div class="mgmt-field">
      <label>{{ $t('workspace_create.root_path') }} *</label>
      <input
        :value="modelValue.project_path"
        type="text"
        class="mgmt-input"
        placeholder="C:\\workspace\\billing-v8r21"
        @input="onPathInput"
      />
      <span class="mgmt-hint">{{ $t('workspace_create.root_path_hint') }}</span>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.wf-step {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
</style>
