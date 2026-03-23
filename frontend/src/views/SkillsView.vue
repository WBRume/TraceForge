<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeft,
  Plus,
  Wrench,
  Globe,
  FolderOpen,
  Pencil,
  Trash2,
  Loader2,
  Sparkles,
} from 'lucide-vue-next'
import api from '@/utils/api'
import { useWorkspaceStore } from '@/stores/workspace'

type SkillDimension = 'GLOBAL' | 'WORKSPACE'

const route = useRoute()
const router = useRouter()
const wsStore = useWorkspaceStore()
const { t } = useI18n()

const loading = ref(false)
const deletingSkillId = ref('')
const activeScope = ref<'all' | 'global' | 'workspace'>('all')
const skills = ref<any[]>([])

const selectedWorkspaceId = ref((route.query.wsId as string) || '')

const scopeOptions = computed(() => [
  { key: 'all', label: t('skills.list.scope_all') },
  { key: 'global', label: t('skills.list.scope_global') },
  { key: 'workspace', label: t('skills.list.scope_workspace') },
])

const loadSkills = async () => {
  if (!selectedWorkspaceId.value) {
    skills.value = []
    return
  }

  loading.value = true
  try {
    const res = await api.get(`/workspaces/${selectedWorkspaceId.value}/skills`, {
      params: { scope: activeScope.value },
    })
    skills.value = res.data.items || []
  } catch (e) {
    console.error('Failed to load skills', e)
    skills.value = []
  } finally {
    loading.value = false
  }
}

const goBack = () => {
  router.push('/workspaces')
}

const goCreate = () => {
  if (!selectedWorkspaceId.value) return
  router.push({
    name: 'skillsCreate',
    query: { wsId: selectedWorkspaceId.value },
  })
}

const goEdit = (skill: any) => {
  if (!selectedWorkspaceId.value) return
  router.push({
    name: 'skillsEdit',
    params: { skillId: skill.id },
    query: { wsId: selectedWorkspaceId.value },
  })
}

const deleteSkill = async (skill: any) => {
  if (!selectedWorkspaceId.value) return
  const ok = window.confirm(t('skills.list.confirm_delete', { name: skill.name }))
  if (!ok) return

  deletingSkillId.value = skill.id
  try {
    await api.delete(`/workspaces/${selectedWorkspaceId.value}/skills/${skill.id}`)
    await loadSkills()
  } catch (e) {
    console.error('Failed to delete skill', e)
  } finally {
    deletingSkillId.value = ''
  }
}

const dimensionLabel = (dimension: SkillDimension) =>
  dimension === 'GLOBAL' ? t('skills.list.scope_global') : t('skills.list.scope_workspace')

watch(activeScope, () => {
  loadSkills()
})

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
      path: '/skills',
      query: { wsId: selectedWorkspaceId.value },
    })
  }

  await loadSkills()
})
</script>

<template>
  <div class="skills-page">
    <header class="skills-header glass-panel">
      <div class="header-left">
        <button class="icon-btn" @click="goBack">
          <ArrowLeft class="w-4 h-4" />
          <span>{{ $t('skills.list.back_to_workspaces') }}</span>
        </button>
        <div>
          <h1 class="title-gradient">{{ $t('skills.list.title') }}</h1>
          <p class="subtitle">{{ $t('skills.list.subtitle') }}</p>
        </div>
      </div>

      <button class="btn-primary create-btn" :disabled="!selectedWorkspaceId" @click="goCreate">
        <Plus class="w-4 h-4" />
        {{ $t('skills.list.new_skill') }}
      </button>
    </header>

    <section class="toolbar glass-panel">
      <div class="scope-tabs">
        <button
          v-for="opt in scopeOptions"
          :key="opt.key"
          class="scope-btn"
          :class="{ active: activeScope === opt.key }"
          @click="activeScope = opt.key as 'all' | 'global' | 'workspace'"
        >
          {{ opt.label }}
        </button>
      </div>
    </section>

    <section class="skills-list glass-panel">
      <div v-if="loading" class="list-state">
        <Loader2 class="w-5 h-5 spin text-primary" />
        <span>{{ $t('skills.list.loading') }}</span>
      </div>

      <div v-else-if="skills.length === 0" class="list-state empty">
        <Sparkles class="w-5 h-5 text-primary" />
        <span>{{ $t('skills.list.empty') }}</span>
      </div>

      <div v-else class="skill-grid">
        <article v-for="skill in skills" :key="skill.id" class="skill-card">
          <div class="skill-card-top">
            <div class="skill-title-wrap">
              <h3>{{ skill.name }}</h3>
              <p class="skill-desc">{{ skill.description || $t('skills.list.no_description') }}</p>
            </div>
            <span class="dimension-badge" :class="skill.dimension === 'GLOBAL' ? 'is-global' : 'is-workspace'">
              <Globe v-if="skill.dimension === 'GLOBAL'" class="w-3 h-3" />
              <FolderOpen v-else class="w-3 h-3" />
              {{ dimensionLabel(skill.dimension) }}
            </span>
          </div>

          <div class="skill-meta">
            <span class="meta-item">
              <Wrench class="w-3 h-3" />
              {{ skill.can_manage ? $t('skills.list.manage') : $t('skills.list.read_only') }}
            </span>
            <span class="meta-item">{{ $t('skills.list.creator') }}: {{ skill.creator_id.slice(0, 8) }}</span>
          </div>

          <div class="skill-actions">
            <button class="btn-secondary mini" :disabled="!skill.can_manage" @click="goEdit(skill)">
              <Pencil class="w-3 h-3" />
              {{ $t('skills.list.edit') }}
            </button>
            <button
              class="btn-danger mini"
              :disabled="!skill.can_manage || deletingSkillId === skill.id"
              @click="deleteSkill(skill)"
            >
              <Loader2 v-if="deletingSkillId === skill.id" class="w-3 h-3 spin" />
              <Trash2 v-else class="w-3 h-3" />
              {{ $t('skills.list.delete') }}
            </button>
          </div>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.skills-page {
  min-height: 100vh;
  padding: 1.5rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  background: var(--color-bg-base);
}

.skills-header {
  padding: 1rem;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.header-left {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
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

.create-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 1rem;
  padding: 0.75rem;
}

.scope-tabs {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.scope-btn {
  border: none;
  background: transparent;
  color: #475569;
  padding: 0.4rem 0.8rem;
  border-radius: 999px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.scope-btn:hover {
  background: #e0f2fe;
  color: #0369a1;
}

.scope-btn.active {
  background: #0284c7;
  color: #fff;
}

.skills-list {
  padding: 1rem;
  min-height: 220px;
}

.list-state {
  height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  color: #475569;
}

.list-state.empty {
  color: #64748b;
}

.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1rem;
}

.skill-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  transition: all 0.2s;
}

.skill-card:hover {
  border-color: #7dd3fc;
  box-shadow: 0 10px 20px rgba(2, 132, 199, 0.08);
  transform: translateY(-2px);
}

.skill-card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.8rem;
}

.skill-title-wrap h3 {
  margin: 0;
  font-size: 1rem;
  color: #0f172a;
}

.skill-desc {
  margin: 0.3rem 0 0;
  color: #64748b;
  font-size: 0.86rem;
}

.dimension-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.74rem;
  padding: 0.2rem 0.45rem;
  border-radius: 999px;
  font-weight: 700;
  white-space: nowrap;
}

.dimension-badge.is-global {
  background: #dbeafe;
  color: #1d4ed8;
}

.dimension-badge.is-workspace {
  background: #dcfce7;
  color: #166534;
}

.skill-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #64748b;
  font-size: 0.75rem;
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.skill-actions {
  margin-top: auto;
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

.mini {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.3rem 0.6rem;
  font-size: 0.75rem;
}

.btn-danger {
  border: 1px solid #fecaca;
  background: #fff1f2;
  color: #be123c;
  border-radius: 8px;
}

.btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.w-3 {
  width: 0.75rem;
  height: 0.75rem;
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
  .skills-page {
    padding: 1rem;
  }

  .skills-header {
    flex-direction: column;
  }

  .header-left {
    width: 100%;
  }

  .toolbar {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
