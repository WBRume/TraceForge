<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Loader2, Save } from 'lucide-vue-next'
import api from '@/utils/api'
import { useWorkspaceStore } from '@/stores/workspace'

type SkillDimension = 'GLOBAL' | 'WORKSPACE'

const route = useRoute()
const router = useRouter()
const wsStore = useWorkspaceStore()
const { t } = useI18n()

const saving = ref(false)
const loading = ref(false)
const selectedWorkspaceId = ref((route.query.wsId as string) || '')

const skillId = computed(() => route.params.skillId as string | undefined)
const isEdit = computed(() => !!skillId.value)

const form = ref({
  name: '',
  description: '',
  content: '',
  dimension: 'WORKSPACE' as SkillDimension,
  workspaceId: selectedWorkspaceId.value || '',
})

const pageTitle = computed(() =>
  isEdit.value ? t('skills.editor.page_title_edit') : t('skills.editor.page_title_new'),
)
const workspaceOptions = computed(() => wsStore.workspaces || [])

const goBack = () => {
  router.push({
    path: '/skills',
    query: { wsId: selectedWorkspaceId.value || undefined },
  })
}

const loadDetail = async () => {
  if (!isEdit.value || !skillId.value || !selectedWorkspaceId.value) return
  loading.value = true
  try {
    const res = await api.get(`/workspaces/${selectedWorkspaceId.value}/skills/${skillId.value}`)
    form.value = {
      name: res.data.name || '',
      description: res.data.description || '',
      content: res.data.content || '',
      dimension: (res.data.dimension || 'WORKSPACE') as SkillDimension,
      workspaceId: res.data.workspace_id || selectedWorkspaceId.value,
    }
  } catch (e) {
    console.error('Failed to load skill detail', e)
  } finally {
    loading.value = false
  }
}

const saveSkill = async () => {
  if (!selectedWorkspaceId.value) return
  if (!form.value.name.trim() || !form.value.content.trim()) return
  if (form.value.dimension === 'WORKSPACE' && !form.value.workspaceId) return

  saving.value = true
  const payload = {
    name: form.value.name.trim(),
    description: form.value.description.trim(),
    content: form.value.content,
    dimension: form.value.dimension,
    workspace_id: form.value.dimension === 'WORKSPACE' ? form.value.workspaceId : null,
  }

  try {
    if (isEdit.value && skillId.value) {
      await api.put(`/workspaces/${selectedWorkspaceId.value}/skills/${skillId.value}`, payload)
    } else {
      await api.post(`/workspaces/${selectedWorkspaceId.value}/skills`, payload)
    }
    goBack()
  } catch (e) {
    console.error('Failed to save skill', e)
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await wsStore.fetchWorkspaces()
  if (
    (!selectedWorkspaceId.value || !wsStore.workspaces.some((ws) => ws.id === selectedWorkspaceId.value))
    && wsStore.workspaces.length > 0
  ) {
    selectedWorkspaceId.value = wsStore.workspaces[0].id
  }
  if (selectedWorkspaceId.value) {
    router.replace({
      path: route.path,
      query: { wsId: selectedWorkspaceId.value },
    })
  }
  if (!form.value.workspaceId && selectedWorkspaceId.value) {
    form.value.workspaceId = selectedWorkspaceId.value
  }
  await loadDetail()
})
</script>

<template>
  <div class="editor-page">
    <header class="editor-header glass-panel">
      <div class="left">
        <button class="icon-btn" @click="goBack">
          <ArrowLeft class="w-4 h-4" />
          <span>{{ $t('skills.editor.back_to_skills') }}</span>
        </button>
        <div>
          <h1 class="title-gradient">{{ pageTitle }}</h1>
          <p class="subtitle">{{ $t('skills.editor.subtitle') }}</p>
        </div>
      </div>

      <button
        class="btn-primary save-btn"
        :disabled="!selectedWorkspaceId || saving || loading || !form.name.trim() || !form.content.trim() || (form.dimension === 'WORKSPACE' && !form.workspaceId)"
        @click="saveSkill"
      >
        <Loader2 v-if="saving" class="w-4 h-4 spin" />
        <Save v-else class="w-4 h-4" />
        <span>{{ saving ? $t('skills.editor.saving') : $t('skills.editor.save') }}</span>
      </button>
    </header>

    <main class="editor-body glass-panel">
      <div v-if="loading" class="loading-state">
        <Loader2 class="w-5 h-5 spin text-primary" />
        <span>{{ $t('skills.editor.loading') }}</span>
      </div>

      <template v-else>
        <div class="form-grid">
          <div class="form-group">
            <label>{{ $t('skills.editor.dimension') }}</label>
            <select v-model="form.dimension" class="input-field">
              <option value="GLOBAL">{{ $t('skills.editor.dimension_global') }}</option>
              <option value="WORKSPACE">{{ $t('skills.editor.dimension_workspace') }}</option>
            </select>
          </div>

          <div v-if="form.dimension === 'WORKSPACE'" class="form-group">
            <label>{{ $t('skills.editor.target_workspace') }}</label>
            <select v-model="form.workspaceId" class="input-field">
              <option v-for="ws in workspaceOptions" :key="ws.id" :value="ws.id">{{ ws.name }}</option>
            </select>
          </div>
        </div>

        <div class="form-group mt">
          <label>{{ $t('skills.editor.name') }}</label>
          <input
            v-model="form.name"
            class="input-field"
            type="text"
            :placeholder="$t('skills.editor.name_placeholder')"
          />
        </div>

        <div class="form-group mt">
          <label>{{ $t('skills.editor.description') }}</label>
          <input
            v-model="form.description"
            class="input-field"
            type="text"
            :placeholder="$t('skills.editor.description_placeholder')"
          />
        </div>

        <div class="form-group mt">
          <label>{{ $t('skills.editor.content') }}</label>
          <textarea
            v-model="form.content"
            class="input-field markdown-editor"
            :placeholder="$t('skills.editor.content_placeholder')"
          />
        </div>
      </template>
    </main>
  </div>
</template>

<style scoped>
.editor-page {
  min-height: 100vh;
  background: var(--color-bg-base);
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.editor-header {
  padding: 1rem;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
}

.left {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
}

.icon-btn {
  border: 1px solid #dbeafe;
  background: #eff6ff;
  color: #1d4ed8;
  border-radius: 10px;
  padding: 0.5rem 0.75rem;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  cursor: pointer;
}

.title-gradient {
  margin: 0;
  font-size: 1.8rem;
  font-weight: 800;
  background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  margin: 0.3rem 0 0;
  color: #64748b;
  font-size: 0.9rem;
}

.save-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

.editor-body {
  padding: 1rem;
}

.loading-state {
  min-height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.8rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.form-group label {
  font-size: 0.84rem;
  color: #475569;
  font-weight: 600;
}

.input-field {
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 0.6rem 0.75rem;
  font-size: 0.95rem;
  font-family: inherit;
  background: #fff;
}

.input-field:focus {
  outline: none;
  border-color: #38bdf8;
}

.mt {
  margin-top: 0.8rem;
}

.markdown-editor {
  min-height: 60vh;
  resize: vertical;
  font-family: var(--font-mono);
  line-height: 1.5;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

.w-5 {
  width: 1.25rem;
  height: 1.25rem;
}

.spin {
  animation: spin 1s linear infinite;
}

.text-primary {
  color: var(--color-primary-600);
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 768px) {
  .editor-page {
    padding: 1rem;
  }

  .editor-header {
    flex-direction: column;
  }

  .left {
    width: 100%;
    flex-direction: column;
  }

  .markdown-editor {
    min-height: 52vh;
  }
}
</style>
