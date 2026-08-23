<!--
RepoPickerDialog: pick a repository with search and type filter chips.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Search } from 'lucide-vue-next'
import { listRepositories } from '@/services/managementApi'
import type { Repository, RepositoryType } from '@/types/management'

const props = withDefaults(defineProps<{
  show: boolean
  excludeIds?: string[]
}>(), {
  excludeIds: () => [],
})

const emit = defineEmits<{
  (e: 'pick', repository: Repository): void
  (e: 'close'): void
}>()

const items = ref<Repository[]>([])
const loading = ref(false)
const keyword = ref('')
const typeFilter = ref<'ALL' | RepositoryType>('ALL')

const typeChips = computed(() => [
  { key: 'ALL' as const, label: 'management.common.type' },
  { key: 'OOTB' as const, label: 'management.repository.type_ootb' },
  { key: 'CUSTOM' as const, label: 'management.repository.type_custom' },
])

const filtered = computed(() => items.value.filter((repo) => {
  if (typeFilter.value !== 'ALL' && repo.repo_type !== typeFilter.value) return false
  if (props.excludeIds.includes(repo.id)) return false
  return true
}))

const load = async () => {
  loading.value = true
  try {
    const res = await listRepositories({
      keyword: keyword.value || undefined,
      repo_type: typeFilter.value === 'ALL' ? '' : typeFilter.value,
      page_size: 100,
    })
    items.value = res.items
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

watch(() => props.show, (visible) => {
  if (!visible) return
  keyword.value = ''
  typeFilter.value = 'ALL'
  load()
})

const pick = (repo: Repository) => {
  emit('pick', repo)
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div v-if="show" class="mgmt-modal-overlay" @pointerdown.self="emit('close')">
      <div class="mgmt-modal glass-panel">
        <h3>{{ $t('management.product.binding_repo') }}</h3>

        <div class="mgmt-toolbar">
          <div class="mgmt-repo-search">
            <Search class="mgmt-repo-search-icon" />
            <input
              v-model="keyword"
              class="mgmt-search"
              type="text"
              :placeholder="$t('management.common.search_placeholder')"
              @keyup.enter="load"
            />
          </div>
          <button class="btn-secondary" @click="load">{{ $t('common.refresh') }}</button>
        </div>

        <div class="mgmt-chips">
          <button
            v-for="chip in typeChips"
            :key="chip.key"
            class="mgmt-chip"
            :class="{ active: typeFilter === chip.key }"
            @click="typeFilter = chip.key; load()"
          >
            {{ chip.key === 'ALL' ? $t('chat.session_filter_all') : $t(chip.label) }}
          </button>
        </div>

        <div v-if="loading" class="mgmt-empty">{{ $t('management.common.loading') }}</div>
        <div v-else-if="filtered.length === 0" class="mgmt-empty">{{ $t('management.common.empty') }}</div>
        <table v-else class="mgmt-table">
          <thead>
            <tr>
              <th>{{ $t('management.common.name') }}</th>
              <th>{{ $t('management.repository.git_url') }}</th>
              <th>{{ $t('management.common.type') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="repo in filtered" :key="repo.id" class="mgmt-repo-row" @click="pick(repo)">
              <td>{{ repo.name }}</td>
              <td>{{ repo.git_url }}</td>
              <td>
                <span class="mgmt-tag" :class="repo.repo_type === 'OOTB' ? 'ootb' : 'custom'">
                  {{ repo.repo_type === 'OOTB'
                    ? $t('management.repository.type_ootb')
                    : $t('management.repository.type_custom') }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </Teleport>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-repo-search {
  position: relative;
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 220px;
}

.mgmt-repo-search-icon {
  position: absolute;
  left: 12px;
  width: 1rem;
  height: 1rem;
  color: #94a3b8;
}

.mgmt-repo-search .mgmt-search {
  padding-left: 2.2rem;
  width: 100%;
}

.mgmt-chips {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}

.mgmt-chip {
  padding: 0.3rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.8);
  color: #475569;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
}

.mgmt-chip:hover {
  border-color: var(--color-primary-500);
  color: var(--color-primary-600);
}

.mgmt-chip.active {
  background: var(--color-primary-100);
  border-color: var(--color-primary-500);
  color: var(--color-primary-600);
  font-weight: 600;
}

.mgmt-repo-row {
  cursor: pointer;
}
</style>
