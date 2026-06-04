<script setup lang="ts">
import { computed } from 'vue'
import { Search, Plus } from 'lucide-vue-next'
import type { ApiMockEndpoint } from '@/types/apiMock'

const props = defineProps<{
  endpoints: ApiMockEndpoint[]
  selectedEndpointId: string
  keyword: string
  canManage?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:keyword', value: string): void
  (e: 'select', endpointId: string): void
  (e: 'create-global-entity'): void
}>()

const groupedEndpoints = computed(() => {
  const map = new Map<string, ApiMockEndpoint[]>()
  for (const endpoint of props.endpoints) {
    const tag = endpoint.tag || 'default'
    if (!map.has(tag)) map.set(tag, [])
    map.get(tag)?.push(endpoint)
  }
  return Array.from(map.entries()).map(([tag, items]) => ({ tag, items }))
})

const methodClass = (method: string) => `m-${method.toLowerCase()}`
</script>

<template>
  <section class="panel glass-panel">
    <header class="head">
      <h3>{{ $t('api_mock.endpoint_tree') }}</h3>
      <button v-if="canManage" class="btn-primary mini flex items-center gap-1" @click="emit('create-global-entity')">
        <Plus class="w-3 h-3" /> Entity
      </button>
    </header>
    <div class="search">
      <Search class="w-4 h-4" />
      <input
        class="input-field"
        :placeholder="$t('api_mock.search_endpoint')"
        :value="keyword"
        @input="emit('update:keyword', ($event.target as HTMLInputElement).value)"
      />
    </div>

    <div v-if="groupedEndpoints.length === 0" class="empty">{{ $t('api_mock.no_endpoint') }}</div>

    <div v-else class="groups">
      <article v-for="group in groupedEndpoints" :key="group.tag" class="group">
        <h4>{{ group.tag }}</h4>
        <button
          v-for="endpoint in group.items"
          :key="endpoint.id"
          class="endpoint"
          :class="{ active: endpoint.id === selectedEndpointId }"
          @click="emit('select', endpoint.id)"
        >
          <span class="method" :class="methodClass(endpoint.method)">{{ endpoint.method }}</span>
          <span class="path">{{ endpoint.path }}</span>
        </button>
      </article>
    </div>
  </section>
</template>

<style scoped>
.panel {
  padding: 0.8rem;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  min-height: 0;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.head h3 {
  margin: 0;
  font-size: 0.9rem;
  color: #0f172a;
}

.search {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.search .input-field {
  flex: 1;
}

.groups {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  overflow: auto;
  min-height: 0;
}

.group {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 0.5rem;
  background: #fff;
}

.group h4 {
  margin: 0 0 0.45rem;
  font-size: 0.74rem;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.endpoint {
  width: 100%;
  border: 1px solid transparent;
  border-radius: 8px;
  background: #f8fbff;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  text-align: left;
  padding: 0.38rem 0.45rem;
  margin-bottom: 0.32rem;
}

.endpoint:last-child {
  margin-bottom: 0;
}

.endpoint:hover {
  border-color: #7dd3fc;
}

.endpoint.active {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.12);
  background: #eef9ff;
}

.method {
  min-width: 48px;
  display: inline-flex;
  justify-content: center;
  align-items: center;
  font-size: 0.67rem;
  border-radius: 999px;
  padding: 0.15rem 0.35rem;
  font-weight: 700;
  color: #fff;
}

.m-get { background: #10b981; }
.m-post { background: #0ea5e9; }
.m-put, .m-patch { background: #f59e0b; }
.m-delete { background: #ef4444; }
.m-head, .m-options { background: #64748b; }

.path {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.76rem;
  color: #1e293b;
}

.empty {
  min-height: 120px;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
  font-size: 0.8rem;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}
</style>
