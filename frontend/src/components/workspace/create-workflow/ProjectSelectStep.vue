<!-- Workspace creation workflow: step 2 project selection. -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { FolderKanban, Search } from 'lucide-vue-next'
import type { Project } from '@/types/management'

const props = defineProps<{
  modelValue: string | null
  projects: Project[]
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | null): void
  (e: 'refresh'): void
}>()

const keyword = ref('')

const filtered = computed(() => {
  const normalized = keyword.value.trim().toLowerCase()
  if (!normalized) return props.projects
  return props.projects.filter((item) => {
    return (
      item.name.toLowerCase().includes(normalized)
      || item.code.toLowerCase().includes(normalized)
      || (item.customer || '').toLowerCase().includes(normalized)
    )
  })
})

const select = (projectId: string | null) => {
  emit('update:modelValue', projectId)
}
</script>

<template>
  <div class="wf-step">
    <div class="wf-search-row">
      <div class="mgmt-search-wrap">
        <Search class="w-4 h-4 wf-search-icon" />
        <input
          v-model="keyword"
          type="text"
          class="mgmt-search"
          :placeholder="$t('management.common.search_placeholder')"
        />
      </div>
      <button type="button" class="btn-secondary" @click="emit('refresh')">
        {{ $t('common.refresh') }}
      </button>
    </div>

    <p class="mgmt-hint">{{ $t('workspace_create.project_hint') }}</p>

    <div v-if="loading" class="mgmt-empty">{{ $t('management.common.loading') }}</div>

    <div v-else class="wf-project-grid">
      <button
        type="button"
        class="wf-project-card"
        :class="{ selected: modelValue === null }"
        @click="select(null)"
      >
        <div class="wf-project-title">{{ $t('workspace_create.project_none') }}</div>
        <div class="wf-project-meta">{{ $t('workspace_create.local_empty_hint') }}</div>
      </button>

      <button
        v-for="project in filtered"
        :key="project.id"
        type="button"
        class="wf-project-card"
        :class="{ selected: modelValue === project.id }"
        @click="select(project.id)"
      >
        <div class="wf-project-title-row">
          <FolderKanban class="w-4 h-4 text-primary" />
          <span class="wf-project-title">{{ project.name }}</span>
        </div>
        <div class="wf-project-meta">{{ project.code }}</div>
        <div class="wf-project-meta">{{ project.customer || '-' }} · {{ project.organization || '-' }}</div>
      </button>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>
<style scoped>
.wf-step {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.wf-search-row {
  display: flex;
  gap: 0.5rem;
}

.mgmt-search-wrap {
  position: relative;
  flex: 1;
}

.wf-search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: #94a3b8;
}

.wf-search-row .mgmt-search {
  width: 100%;
  padding-left: 2rem;
}

.wf-project-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  max-height: 300px;
  overflow-y: auto;
}

.wf-project-card {
  text-align: left;
  border: 1.5px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 12px;
  padding: 0.9rem 1rem;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.wf-project-card:hover {
  border-color: #7dd3fc;
  background: #f0f9ff;
}

.wf-project-card.selected {
  border-color: #0ea5e9;
  background: #f0f9ff;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
}

.wf-project-title-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.wf-project-title {
  font-weight: 600;
  color: #0f172a;
  font-size: 0.92rem;
}

.wf-project-meta {
  font-size: 0.78rem;
  color: #64748b;
}

.text-primary {
  color: var(--color-primary-600);
}
</style>
