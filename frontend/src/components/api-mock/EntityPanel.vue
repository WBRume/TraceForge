<script setup lang="ts">
import { computed, reactive, ref, provide } from 'vue'
import { Database, Globe, Link, Pencil, Trash2, Save, X } from 'lucide-vue-next'
import ApiMockSchemaNode from './ApiMockSchemaNode.vue'
import type { ApiMockEndpoint, ApiMockEntity } from '@/types/apiMock'

const props = withDefaults(defineProps<{
  entities: ApiMockEntity[]
  endpoint: ApiMockEndpoint | null
  canManage: boolean
  hideGlobalAction?: boolean
}>(), { hideGlobalAction: false })

const emit = defineEmits<{
  (e: 'create-entity', payload: { name: string; description: string | null; schema_json: Record<string, unknown>; endpoint_id: string | null }): void
  (e: 'update-entity', payload: { id: string; row_version: number; name: string; description: string | null; schema_json: Record<string, unknown>; endpoint_id: string | null }): void
  (e: 'delete-entity', entityId: string): void
}>()

provide('availableEntities', computed(() => props.entities))

const globalEntities = computed(() => props.entities.filter((e) => !e.endpoint_id))
const endpointEntities = computed(() =>
  props.endpoint
    ? props.entities.filter((e) => e.endpoint_id === props.endpoint?.id)
    : [],
)

const showCreateForm = ref(false)
const createScope = ref<'global' | 'endpoint'>('global')
const editingEntityId = ref<string | null>(null)
const expandedEntityId = ref<string | null>(null)

const createForm = reactive({
  name: '',
  description: '',
  schemaObj: { type: 'object', properties: {} } as Record<string, unknown>,
})

const editForm = reactive({
  name: '',
  description: '',
  schemaObj: {} as Record<string, unknown>,
  rowVersion: 1,
  endpointId: null as string | null,
})

const openCreateForm = (scope: 'global' | 'endpoint') => {
  createScope.value = scope
  createForm.name = ''
  createForm.description = ''
  createForm.schemaObj = { type: 'object', properties: {} }
  showCreateForm.value = true
}

const submitCreate = () => {
  if (!createForm.name.trim()) return
  emit('create-entity', {
    name: createForm.name.trim(),
    description: createForm.description || null,
    schema_json: JSON.parse(JSON.stringify(createForm.schemaObj)),
    endpoint_id: createScope.value === 'endpoint' && props.endpoint ? props.endpoint.id : null,
  })
  showCreateForm.value = false
}

const startEdit = (entity: ApiMockEntity) => {
  editingEntityId.value = entity.id
  editForm.name = entity.name
  editForm.description = entity.description || ''
  editForm.schemaObj = JSON.parse(JSON.stringify(entity.schema_json || {}))
  editForm.rowVersion = entity.row_version
  editForm.endpointId = entity.endpoint_id
}

const cancelEdit = () => {
  editingEntityId.value = null
}

const submitEdit = (entity: ApiMockEntity) => {
  if (!editForm.name.trim()) return
  emit('update-entity', {
    id: entity.id,
    row_version: editForm.rowVersion,
    name: editForm.name.trim(),
    description: editForm.description || null,
    schema_json: JSON.parse(JSON.stringify(editForm.schemaObj)),
    endpoint_id: editForm.endpointId,
  })
  editingEntityId.value = null
}

const toggleExpand = (entityId: string) => {
  expandedEntityId.value = expandedEntityId.value === entityId ? null : entityId
}

defineExpose({ openCreateForm })
</script>

<template>
  <section class="entity-panel glass-panel">
    <header class="panel-head">
      <div class="head-left">
        <Database class="w-4 h-4 head-icon" />
        <h3>{{ $t('api_mock.tab_entities') }}</h3>
      </div>
      <div v-if="canManage" class="head-actions">
        <button v-if="!hideGlobalAction" type="button" class="add-btn" @click="openCreateForm('global')">
          <Globe class="w-3 h-3" /> {{ $t('api_mock.add_global_entity') }}
        </button>
        <button v-if="endpoint" type="button" class="add-btn endpoint-scope" @click="openCreateForm('endpoint')">
          <Link class="w-3 h-3" /> {{ $t('api_mock.add_endpoint_entity') }}
        </button>
      </div>
    </header>

    <!-- Create form -->
    <div v-if="showCreateForm" class="create-form">
      <div class="create-header">
        <span class="scope-badge" :class="createScope">
          <Globe v-if="createScope === 'global'" class="w-3 h-3" />
          <Link v-else class="w-3 h-3" />
          {{ createScope === 'global' ? $t('api_mock.scope_global') : $t('api_mock.scope_endpoint') }}
        </span>
        <button type="button" class="close-btn" @click="showCreateForm = false">
          <X class="w-3 h-3" />
        </button>
      </div>
      <label class="field">
        <span>{{ $t('api_mock.entity_name') }}</span>
        <input v-model="createForm.name" class="input-field" :placeholder="$t('api_mock.entity_name_placeholder')">
      </label>
      <label class="field">
        <span>{{ $t('api_mock.entity_description') }}</span>
        <input v-model="createForm.description" class="input-field">
      </label>
      <div class="field">
        <span>{{ $t('api_mock.structure_map') }}</span>
        <div class="pm-table schema-table-wrapper" style="margin-top: 0.3rem">
          <div class="pm-row pm-header">
            <div class="pm-col" style="flex: 2">{{ $t('api_mock.col_key_field') }}</div>
            <div class="pm-col" style="flex: 1.2">{{ $t('api_mock.col_type') }}</div>
            <div class="pm-col pm-check" style="flex: 0.4">{{ $t('api_mock.col_req') }}</div>
            <div class="pm-col" style="flex: 1.5">{{ $t('api_mock.col_description') }}</div>
            <div class="pm-col-auto" style="width: 3.5rem"></div>
          </div>
          <ApiMockSchemaNode v-model="createForm.schemaObj" :isRoot="true" />
        </div>
      </div>
      <div class="form-actions">
        <button type="button" class="pm-btn secondary" @click="showCreateForm = false">{{ $t('common.cancel') || 'Cancel' }}</button>
        <button type="button" class="pm-btn primary" @click="submitCreate">
          <Save class="w-3.5 h-3.5" /> {{ $t('api_mock.create_entity') }}
        </button>
      </div>
    </div>

    <!-- Global entities -->
    <div class="entity-group">
      <div class="group-header">
        <Globe class="w-3 h-3" />
        <span>{{ $t('api_mock.global_entities') }}</span>
        <span class="count-badge">{{ globalEntities.length }}</span>
      </div>
      <div v-if="globalEntities.length === 0" class="empty-hint">{{ $t('api_mock.no_entity') }}</div>
      <div v-for="entity in globalEntities" :key="entity.id" class="entity-card">
        <template v-if="editingEntityId === entity.id">
          <label class="field">
            <span>{{ $t('api_mock.entity_name') }}</span>
            <input v-model="editForm.name" class="input-field">
          </label>
          <label class="field">
            <span>{{ $t('api_mock.entity_description') }}</span>
            <input v-model="editForm.description" class="input-field">
          </label>
          <div class="field">
            <span>{{ $t('api_mock.structure_map') }}</span>
            <div class="pm-table schema-table-wrapper" style="margin-top: 0.3rem">
              <div class="pm-row pm-header">
                <div class="pm-col" style="flex: 2">KEY (Field)</div>
                <div class="pm-col" style="flex: 1.2">TYPE</div>
                <div class="pm-col pm-check" style="flex: 0.4">REQ</div>
                <div class="pm-col" style="flex: 1.5">DESCRIPTION</div>
                <div class="pm-col-auto" style="width: 3.5rem"></div>
              </div>
              <ApiMockSchemaNode v-model="editForm.schemaObj" :isRoot="true" />
            </div>
          </div>
          <div class="form-actions">
            <button type="button" class="pm-btn secondary" @click="cancelEdit">{{ $t('common.cancel') }}</button>
            <button type="button" class="pm-btn primary" @click="submitEdit(entity)">
              <Save class="w-3.5 h-3.5" /> {{ $t('common.save') }}
            </button>
          </div>
        </template>
        <template v-else>
          <div class="entity-header" @click="toggleExpand(entity.id)">
            <span class="entity-name">{{ entity.name }}</span>
            <span v-if="entity.description" class="entity-desc">{{ entity.description }}</span>
            <span class="entity-props">{{ $t('api_mock.props_count', { count: Object.keys((entity.schema_json as Record<string, unknown>)?.properties || {}).length }) }}</span>
            <div v-if="canManage" class="entity-actions" @click.stop>
              <button type="button" class="icon-btn" @click="startEdit(entity)"><Pencil class="w-3 h-3" /></button>
              <button type="button" class="icon-btn danger" @click="emit('delete-entity', entity.id)"><Trash2 class="w-3 h-3" /></button>
            </div>
          </div>
          <pre v-if="expandedEntityId === entity.id" class="entity-schema">{{ JSON.stringify(entity.schema_json, null, 2) }}</pre>
        </template>
      </div>
    </div>

    <!-- Per-endpoint entities -->
    <div v-if="endpoint" class="entity-group">
      <div class="group-header endpoint">
        <Link class="w-3 h-3" />
        <span>{{ $t('api_mock.endpoint_entities') }}</span>
        <span class="count-badge">{{ endpointEntities.length }}</span>
      </div>
      <div v-if="endpointEntities.length === 0" class="empty-hint">{{ $t('api_mock.no_entity') }}</div>
      <div v-for="entity in endpointEntities" :key="entity.id" class="entity-card">
        <template v-if="editingEntityId === entity.id">
          <label class="field">
            <span>{{ $t('api_mock.entity_name') }}</span>
            <input v-model="editForm.name" class="input-field">
          </label>
          <label class="field">
            <span>{{ $t('api_mock.entity_description') }}</span>
            <input v-model="editForm.description" class="input-field">
          </label>
          <div class="field">
            <span>{{ $t('api_mock.structure_map') }}</span>
            <div class="pm-table schema-table-wrapper" style="margin-top: 0.3rem">
              <div class="pm-row pm-header">
                <div class="pm-col" style="flex: 2">KEY (Field)</div>
                <div class="pm-col" style="flex: 1.2">TYPE</div>
                <div class="pm-col pm-check" style="flex: 0.4">REQ</div>
                <div class="pm-col" style="flex: 1.5">DESCRIPTION</div>
                <div class="pm-col-auto" style="width: 3.5rem"></div>
              </div>
              <ApiMockSchemaNode v-model="editForm.schemaObj" :isRoot="true" />
            </div>
          </div>
          <div class="form-actions">
            <button type="button" class="pm-btn secondary" @click="cancelEdit">{{ $t('common.cancel') }}</button>
            <button type="button" class="pm-btn primary" @click="submitEdit(entity)">
              <Save class="w-3.5 h-3.5" /> {{ $t('common.save') }}
            </button>
          </div>
        </template>
        <template v-else>
          <div class="entity-header" @click="toggleExpand(entity.id)">
            <span class="entity-name">{{ entity.name }}</span>
            <span v-if="entity.description" class="entity-desc">{{ entity.description }}</span>
            <span class="entity-props">{{ $t('api_mock.props_count', { count: Object.keys((entity.schema_json as Record<string, unknown>)?.properties || {}).length }) }}</span>
            <div v-if="canManage" class="entity-actions" @click.stop>
              <button type="button" class="icon-btn" @click="startEdit(entity)"><Pencil class="w-3 h-3" /></button>
              <button type="button" class="icon-btn danger" @click="emit('delete-entity', entity.id)"><Trash2 class="w-3 h-3" /></button>
            </div>
          </div>
          <pre v-if="expandedEntityId === entity.id" class="entity-schema">{{ JSON.stringify(entity.schema_json, null, 2) }}</pre>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.entity-panel {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1rem;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.6rem;
}

.head-left {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.head-left h3 {
  margin: 0;
  font-size: 0.95rem;
  color: #0f172a;
}

.head-icon {
  color: #0369a1;
}

.head-actions {
  display: flex;
  gap: 0.4rem;
}

.add-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.32rem 0.6rem;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  background: #eff6ff;
  color: #0369a1;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
}

.add-btn:hover {
  background: #dbeafe;
}

.add-btn.endpoint-scope {
  border-color: #c7d2fe;
  background: #eef2ff;
  color: #4338ca;
}

.add-btn.endpoint-scope:hover {
  background: #e0e7ff;
}

/* ---- Create form ---- */
.create-form {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  padding: 1.25rem;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  box-shadow: 0 4px 12px rgba(0,0,0,0.03);
}

.create-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.2rem;
}

.scope-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.18rem 0.55rem;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.scope-badge.global {
  background: #f1f5f9;
  color: #334155;
  border: 1px solid #e2e8f0;
}

.scope-badge.endpoint {
  background: #eef2ff;
  color: #4f46e5;
  border: 1px solid #c7d2fe;
}

.close-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.6rem;
  height: 1.6rem;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.2s;
}

.close-btn:hover {
  background: #f1f5f9;
  color: #334155;
}

/* ---- Entity groups ---- */
.entity-group {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  color: #0369a1;
  font-weight: 700;
  font-size: 0.78rem;
  padding-bottom: 0.25rem;
  border-bottom: 1px solid #e2e8f0;
}

.group-header.endpoint {
  color: #4338ca;
}

.count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.4rem;
  height: 1.2rem;
  padding: 0 0.35rem;
  border-radius: 999px;
  background: #e2e8f0;
  color: #475569;
  font-size: 0.66rem;
  font-weight: 700;
}

.empty-hint {
  color: #94a3b8;
  font-size: 0.78rem;
  padding: 0.6rem 0;
  text-align: center;
}

/* ---- Entity card ---- */
.entity-card {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.8rem 1rem;
  background: white;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.entity-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 6px rgba(0,0,0,0.02);
}

.entity-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}

.entity-name {
  font-weight: 700;
  color: #0f172a;
  font-size: 0.84rem;
}

.entity-desc {
  color: #64748b;
  font-size: 0.72rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.entity-props {
  flex-shrink: 0;
  font-size: 0.68rem;
  color: #94a3b8;
  font-weight: 600;
}

.entity-actions {
  display: flex;
  gap: 0.25rem;
  margin-left: auto;
  flex-shrink: 0;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.6rem;
  height: 1.6rem;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  cursor: pointer;
}

.icon-btn:hover {
  background: #eff6ff;
  color: #0369a1;
}

.icon-btn.danger:hover {
  background: #fef2f2;
  color: #dc2626;
  border-color: #fecaca;
}

.entity-schema {
  margin: 0.5rem 0 0;
  padding: 0.6rem;
  border-radius: 10px;
  background: #f1f5f9;
  font-size: 0.72rem;
  line-height: 1.6;
  overflow: auto;
  max-height: 200px;
  color: #334155;
}

/* ---- Edit form inside card ---- */
.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.8rem;
  padding-top: 0.8rem;
  border-top: 1px solid #f1f5f9;
}

.pm-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.45rem 1rem;
  font-size: 0.8rem;
  font-weight: 600;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.pm-btn.primary {
  background: #0ea5e9;
  color: white;
  border: 1px solid #0284c7;
}

.pm-btn.primary:hover {
  background: #0284c7;
}

.pm-btn.secondary {
  background: white;
  color: #475569;
  border: 1px solid #e2e8f0;
}

.pm-btn.secondary:hover {
  background: #f8fafc;
  color: #0f172a;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-top: 0.4rem;
}

.field span {
  color: #64748b;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.input-field {
  width: 100%;
  padding: 0.45rem 0.6rem;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #ffffff;
  font-size: 0.8rem;
  color: #1e293b;
  outline: none;
  transition: all 0.15s ease;
}

.input-field:focus {
  border-color: #38bdf8;
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.1);
}

.min-h-table {
  min-height: 100px;
}

.w-4 { width: 1rem; height: 1rem; }
.w-3 { width: 0.75rem; height: 0.75rem; }
</style>
