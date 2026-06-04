<script setup lang="ts">
import { computed } from 'vue'
import { Braces, FolderTree, Search } from 'lucide-vue-next'
import type { ApiMockEndpoint } from '@/types/apiMock'

const props = defineProps<{
  endpoints: ApiMockEndpoint[]
  selectedEndpointId: string
  keyword: string
  canView: boolean
}>()

const emit = defineEmits<{
  (e: 'select', endpointId: string): void
  (e: 'update:keyword', value: string): void
  (e: 'create-global-entity'): void
}>()

const groupedEndpoints = computed(() => {
  const map = new Map<string, ApiMockEndpoint[]>()
  for (const endpoint of props.endpoints) {
    const tag = (endpoint.tag || 'default').trim() || 'default'
    if (!map.has(tag)) map.set(tag, [])
    map.get(tag)?.push(endpoint)
  }
  return Array.from(map.entries()).map(([tag, items]) => ({
    tag,
    count: items.length,
    items,
  }))
})

const methodClass = (method: string) => `m-${method.toLowerCase()}`
const searchInputId = 'api-mock-catalog-search'

defineExpose({
  focusSearch: () => {
    const input = document.getElementById(searchInputId) as HTMLInputElement | null
    input?.focus()
  },
})
</script>

<template>
  <aside class="catalog glass-panel">
    <div class="catalog-head">
      <div>
        <span class="catalog-kicker">{{ $t('api_mock.endpoint_tree') }}</span>
        <h2>{{ $t('api_mock.endpoint_overview') }}</h2>
      </div>
      <div style="display: flex; gap: 8px; align-items: center">
        <button v-if="canView" type="button" class="btn-primary mini" style="padding: 4px 8px; gap: 4px; border-radius: 8px;" @click="emit('create-global-entity')">
          <FolderTree class="w-3.5 h-3.5" /> {{ $t('api_mock.new_entity') || 'Entity' }}
        </button>
        <span class="count-pill">{{ endpoints.length }}</span>
      </div>
    </div>

    <label class="catalog-search">
      <Search class="w-4 h-4" />
      <input
        :id="searchInputId"
        class="input-field search-input"
        :value="keyword"
        :placeholder="$t('api_mock.search_endpoint')"
        :disabled="!canView"
        @keyup="emit('update:keyword', ($event.target as HTMLInputElement).value)"
      >
    </label>

    <div v-if="groupedEndpoints.length === 0" class="catalog-empty">
      <FolderTree class="w-5 h-5" />
      <strong>{{ $t('api_mock.no_endpoint') }}</strong>
      <p>{{ $t('api_mock.catalog_empty_hint') }}</p>
    </div>

    <div v-else class="catalog-groups custom-scrollbar">
      <section v-for="group in groupedEndpoints" :key="group.tag" class="catalog-group">
        <header class="group-head">
          <span>{{ group.tag }}</span>
          <small>{{ group.count }}</small>
        </header>

        <button
          v-for="endpoint in group.items"
          :key="endpoint.id"
          type="button"
          class="endpoint-card"
          :class="{ active: endpoint.id === selectedEndpointId }"
          @click="emit('select', endpoint.id)"
        >
          <div class="endpoint-topline">
            <span class="method-pill" :class="methodClass(endpoint.method)">{{ endpoint.method }}</span>
            <span class="endpoint-path">{{ endpoint.path }}</span>
          </div>
          <div class="endpoint-meta">
            <span class="operation-id">{{ endpoint.operation_id || 'operationId /' }}</span>
            <span class="summary">
              <Braces class="w-3.5 h-3.5" />
              {{ endpoint.summary || $t('api_mock.summary_empty') }}
            </span>
          </div>
        </button>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.catalog {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  padding: 1rem;
  gap: 0.9rem;
  background:
    #ffffff;
  border: 1px solid #e2e8f0;
}

.catalog-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
}

.catalog-kicker {
  display: inline-flex;
  color: #0369a1;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.catalog-head h2 {
  margin: 0.35rem 0 0;
  font-size: 1.1rem;
}

.catalog-search {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.7rem;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.9);
}

.catalog-search :deep(svg) {
  color: #0284c7;
  flex-shrink: 0;
}

.search-input {
  width: 100%;
  border: none;
  background: transparent;
  box-shadow: none;
  padding: 0;
}

.count-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 2.65rem;
  min-height: 2.65rem;
  border-radius: 999px;
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.14), rgba(59, 130, 246, 0.22));
  color: #0369a1;
  font-weight: 800;
}

.catalog-groups {
  overflow: auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  padding-right: 0.2rem;
}

.catalog-group {
  border-radius: 18px;
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.85);
  padding: 0.78rem;
}

.group-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.6rem;
  color: #0f172a;
  font-weight: 700;
}

.group-head small {
  color: #64748b;
}

.endpoint-card {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 0.38rem;
  margin-bottom: 0.45rem;
  border: 1px solid transparent;
  border-radius: 16px;
  padding: 0.78rem;
  background: rgba(248, 250, 252, 0.9);
  text-align: left;
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

.endpoint-card:last-child {
  margin-bottom: 0;
}

.endpoint-card:hover {
  transform: translateY(-1px);
  border-color: rgba(125, 211, 252, 0.9);
  box-shadow: 0 12px 22px rgba(14, 165, 233, 0.08);
}

.endpoint-card.active {
  border-color: rgba(14, 165, 233, 0.9);
  background: #ffffff;
  box-shadow: 0 18px 28px rgba(14, 165, 233, 0.14);
}

.endpoint-topline {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.method-pill {
  min-width: 3.6rem;
  display: inline-flex;
  justify-content: center;
  align-items: center;
  border-radius: 999px;
  padding: 0.2rem 0.48rem;
  font-size: 0.7rem;
  font-weight: 800;
  color: #fff;
}

.m-get { background: #10b981; }
.m-post { background: #0ea5e9; }
.m-put, .m-patch { background: #f59e0b; }
.m-delete { background: #ef4444; }
.m-head, .m-options { background: #64748b; }

.endpoint-path {
  flex: 1;
  min-width: 0;
  color: #0f172a;
  font-weight: 700;
  line-height: 1.45;
  word-break: break-all;
}

.endpoint-meta {
  display: grid;
  gap: 0.28rem;
  color: #64748b;
  font-size: 0.78rem;
}

.summary {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
}

.catalog-empty {
  min-height: 15rem;
  border-radius: 20px;
  border: 1px dashed #e2e8f0;
  background: rgba(248, 250, 252, 0.86);
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  text-align: center;
}

.catalog-empty strong {
  color: #0f172a;
}

.catalog-empty p {
  margin: 0;
  color: #64748b;
  line-height: 1.6;
}

.w-5 {
  width: 1.25rem;
  height: 1.25rem;
  color: #0ea5e9;
}

.w-3\.5 {
  width: 0.875rem;
  height: 0.875rem;
}
</style>
