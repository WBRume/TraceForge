<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { FileText, Code2, CheckCircle, Search, Clock } from 'lucide-vue-next'
import api from '@/utils/api'

const route = useRoute()
const assets = ref<any[]>([])
const loading = ref(true)
const searchQuery = ref('')
const activeFilter = ref('ALL')

const filters = [
  { id: 'ALL', label: 'All Assets' },
  { id: 'SPEC', label: 'Specifications' },
  { id: 'PLAN', label: 'Plan Nodes' },
  { id: 'CODE_DIFF', label: 'Code Diffs' },
  { id: 'UT_REPORT', label: 'Test Reports' }
]

const loadAssets = async () => {
  loading.value = true
  try {
    const wsId = route.params.wsId
    const res = await api.get(`/workspaces/${wsId}/assets`)
    // Mock for now if empty
    assets.value = res.data.items || [
      { id: '1', name: 'Authentication Spec', asset_type: 'SPEC', created_at: new Date().toISOString() },
      { id: '2', name: 'User Model Generation', asset_type: 'CODE_DIFF', created_at: new Date().toISOString() },
      { id: '3', name: 'Integration Tests Auth', asset_type: 'UT_REPORT', created_at: new Date().toISOString() },
    ]
  } catch (e) {
    console.warn(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadAssets()
})

const getIconForType = (type: string) => {
  switch (type) {
    case 'SPEC': return FileText
    case 'PLAN': return Clock
    case 'CODE_DIFF': return Code2
    case 'UT_REPORT': return CheckCircle
    default: return FileText
  }
}
</script>

<template>
  <div class="assets-view p-8 max-w-6xl mx-auto">
    <div class="header-section mb-8 relative">
      <h1 class="text-3xl font-bold text-primary-900 mb-2">Workspace Assets</h1>
      <p class="text-slate-500 max-w-2xl">Browse generated code, specification docs, and testing reports for all tasks within this workspace.</p>
      
      <!-- Search Bar -->
      <div class="search-bar glass-panel flex items-center mt-6">
        <Search class="w-5 h-5 text-slate-400 ml-4 border-r pr-4 border-slate-200" />
        <input 
          v-model="searchQuery" 
          type="text" 
          placeholder="Search assets by name or content..." 
          class="flex-1 px-4 py-3 bg-transparent border-none outline-none text-slate-700"
        >
      </div>
      
      <!-- Filters -->
      <div class="filters flex gap-3 mt-6">
        <button 
          v-for="f in filters" :key="f.id"
          class="filter-pill"
          :class="{ active: activeFilter === f.id }"
          @click="activeFilter = f.id"
        >
          {{ f.label }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="text-center py-12 text-slate-500">Loading assets...</div>
    
    <div v-else class="assets-grid grid gap-6 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
      <div v-for="asset in assets" :key="asset.id" class="asset-card glass-panel cursor-pointer group">
        <div class="card-top flex items-start justify-between mb-4">
          <div class="icon-blob bg-primary-50 text-primary-600 p-3 rounded-xl group-hover:bg-primary-600 group-hover:text-white transition-colors duration-300">
            <component :is="getIconForType(asset.asset_type)" class="w-6 h-6" />
          </div>
          <span class="text-xs font-semibold px-2 py-1 bg-slate-100 text-slate-600 rounded-md">
            {{ asset.asset_type }}
          </span>
        </div>
        
        <h3 class="font-bold text-slate-800 text-lg mb-2 group-hover:text-primary-700 transition-colors">
          {{ asset.name }}
        </h3>
        <p class="text-sm text-slate-500 mb-6">Generated artifacts from the automated SDD loop.</p>
        
        <div class="card-bottom pt-4 border-t border-slate-100 flex justify-between items-center text-xs text-slate-400">
          <span>{{ new Date(asset.created_at).toLocaleDateString() }}</span>
          <span class="font-medium text-primary-600 opacity-0 group-hover:opacity-100 transition-opacity">View Details &rarr;</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Utility mimicking Tailwind */
.p-8 { padding: 2rem; }
.mb-8 { margin-bottom: 2rem; }
.mb-2 { margin-bottom: 0.5rem; }
.mb-4 { margin-bottom: 1rem; }
.mb-6 { margin-bottom: 1.5rem; }
.mt-6 { margin-top: 1.5rem; }
.py-3 { padding-top: 0.75rem; padding-bottom: 0.75rem; }
.py-12 { padding-top: 3rem; padding-bottom: 3rem; }
.px-4 { padding-left: 1rem; padding-right: 1rem; }
.pt-4 { padding-top: 1rem; }
.max-w-6xl { max-width: 72rem; }
.max-w-2xl { max-width: 42rem; }
.mx-auto { margin-left: auto; margin-right: auto; }
.text-3xl { font-size: 1.875rem; line-height: 2.25rem; }
.text-lg { font-size: 1.125rem; line-height: 1.75rem; }
.text-sm { font-size: 0.875rem; line-height: 1.25rem; }
.text-xs { font-size: 0.75rem; line-height: 1rem; }
.font-bold { font-weight: 700; }
.font-semibold { font-weight: 600; }
.font-medium { font-weight: 500; }
.text-slate-500 { color: #64748b; }
.text-slate-400 { color: #94a3b8; }
.text-slate-600 { color: #475569; }
.text-slate-700 { color: #334155; }
.text-slate-800 { color: #1e293b; }
.text-primary-900 { color: var(--color-primary-900); }
.text-primary-700 { color: var(--color-primary-900); } /* mapped */
.text-primary-600 { color: var(--color-primary-600); }
.text-white { color: #ffffff; }
.bg-transparent { background-color: transparent; }
.bg-primary-50 { background-color: var(--color-primary-50); }
.bg-slate-100 { background-color: #f1f5f9; }
.border-slate-200 { border-color: #e2e8f0; }
.border-slate-100 { border-color: #f1f5f9; }
.block { display: block; }
.flex { display: flex; }
.flex-1 { flex: 1 1 0%; }
.items-center { align-items: center; }
.items-start { align-items: flex-start; }
.justify-between { justify-content: space-between; }
.gap-3 { gap: 0.75rem; }
.gap-6 { gap: 1.5rem; }
.grid { display: grid; }
.grid-cols-1 { grid-template-columns: repeat(1, minmax(0, 1fr)); }
.ml-4 { margin-left: 1rem; }
.pr-4 { padding-right: 1rem; }
.border-r { border-right-width: 1px; border-right-style: solid; }
.border-t { border-top-width: 1px; border-top-style: solid; }
.rounded-xl { border-radius: 0.75rem; }
.rounded-md { border-radius: 0.375rem; }
.cursor-pointer { cursor: pointer; }
.text-center { text-align: center; }
.outline-none { outline: 2px solid transparent; outline-offset: 2px; }
.transition-colors { transition-property: color, background-color, border-color, text-decoration-color, fill, stroke; transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1); transition-duration: 300ms; }
.transition-opacity { transition-property: opacity; transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1); transition-duration: 300ms; }
.opacity-0 { opacity: 0; }
.opacity-100 { opacity: 1; }

@media (min-width: 768px) {
  .md\:grid-cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (min-width: 1024px) {
  .lg\:grid-cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

/* Custom classes */
.search-bar {
  border-radius: 9999px;
  max-width: 600px;
  box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05);
}

.filter-pill {
  padding: 8px 16px;
  border-radius: 9999px;
  background-color: white;
  border: 1px solid #e2e8f0;
  color: #64748b;
  font-weight: 500;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s;
}

.filter-pill:hover {
  border-color: var(--color-primary-500);
  color: var(--color-primary-600);
}

.filter-pill.active {
  background-color: var(--color-primary-500);
  color: white;
  border-color: var(--color-primary-500);
}

.asset-card {
  transition: transform 0.3s ease, box-shadow 0.3s ease;
  border: 1px solid rgba(255,255,255,0.8);
}

.asset-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 10px 25px -5px rgba(59, 130, 246, 0.15);
  border-color: rgba(59, 130, 246, 0.3);
}

.group:hover .group-hover\:bg-primary-600 { background-color: var(--color-primary-600); }
.group:hover .group-hover\:text-white { color: white; }
.group:hover .group-hover\:text-primary-700 { color: var(--color-primary-900); }
.group:hover .group-hover\:opacity-100 { opacity: 1; }
</style>
