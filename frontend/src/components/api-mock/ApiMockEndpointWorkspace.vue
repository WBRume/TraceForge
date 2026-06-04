<script setup lang="ts">
import { computed, nextTick, reactive, ref, shallowRef, watch, provide } from 'vue'
import { VueMonacoEditor } from '@guolao/vue-monaco-editor'
import type * as Monaco from 'monaco-editor'
import {
  Braces, Layers, Database,
  Save, Plus, Trash2, Copy,
  FileCode2,
} from 'lucide-vue-next'
import type {
  ApiMockDocument,
  ApiMockEndpoint,
  ApiMockEntity,
  ApiMockMockCase,
} from '@/types/apiMock'
import { ensureMonacoViteSetup } from '@/utils/monaco'
import api from '@/utils/api'
import ApiMockMockCaseEditor from '@/components/api-mock/ApiMockMockCaseEditor.vue'
import EntityPanel from '@/components/api-mock/EntityPanel.vue'
import ApiMockSchemaNode from '@/components/api-mock/ApiMockSchemaNode.vue'
import BaseSelect from '@/components/BaseSelect.vue'

const props = defineProps<{
  endpoint: ApiMockEndpoint | null
  entities: ApiMockEntity[]
  document: ApiMockDocument | null
  documentLoading: boolean
  canManage: boolean
  canManageMock: boolean
  swaggerMutationLocked: boolean
  projectAutoMockLocked: boolean
  currentEndpointAutoMockLocked: boolean
  autoMockBusy: boolean
  autoMockJob: { id: string; job_type: string; status: string; progress: number; message?: string | null; result_json?: Record<string, unknown> | null } | null
  savingEndpoint: boolean
  savingDocument: boolean
  cases: ApiMockMockCase[]
  selectedCaseId: string
  savingCase: boolean
  deletingCase: boolean
  wsId: string
  taskId: string
}>()

const emit = defineEmits<{
  (e: 'save-endpoint', payload: {
    row_version: number
    method: string
    path: string
    operation_id: string | null
    tag: string | null
    summary: string | null
    parameters_json: Array<Record<string, unknown>> | null
    request_schema_json: Record<string, unknown> | null
    responses_json: Record<string, unknown> | null
    response_schema_json: Record<string, unknown> | null
    entity_refs_json: string[] | null
  }): void
  (e: 'save-document', payload: { content: string }): void
  (e: 'select-case', value: string): void
  (e: 'create-case'): void
  (e: 'start-auto-mock'): void
  (e: 'save-case', payload: {
    id?: string
    row_version?: number
    name: string
    description: string | null
    is_default: boolean
    sort_order?: number
    mode: 'STATIC' | 'MOCKJS' | 'PROXY'
    request_path_params_json?: Record<string, unknown> | null
    request_query_json?: Record<string, unknown> | null
    request_body_json?: unknown
    static_body_json?: Record<string, unknown> | null
    mockjs_template?: string | null
    status_code: number
    headers_json?: Record<string, unknown> | null
    cookies_json?: Array<Record<string, unknown>> | null
    delay_ms: number
    enabled: boolean
  }): void
  (e: 'delete-case', caseId: string): void
  (e: 'create-entity', payload: { name: string; description: string | null; schema_json: Record<string, unknown>; endpoint_id: string | null }): void
  (e: 'update-entity', payload: { id: string; row_version: number; name: string; description: string | null; schema_json: Record<string, unknown>; endpoint_id: string | null }): void
  (e: 'delete-entity', entityId: string): void
}>()

ensureMonacoViteSetup()

provide('availableEntities', computed(() => props.entities))

type WorkspaceTab = 'structure' | 'mock' | 'entities' | 'document'

const activeTab = ref<WorkspaceTab>('structure')

type StructureTab = 'params' | 'headers' | 'body' | 'responses' | 'settings'
const activeStructureTab = ref<StructureTab>('params')

/* ---- Structure form ---- */
const endpointForm = reactive({
  rowVersion: 1,
  method: 'GET',
  path: '/',
  operationId: '',
  tag: '',
  summary: '',
  requestSchemaObj: {} as Record<string, unknown>,
  responseSchemaObj: {} as Record<string, unknown>,
})

type ParamRow = {
  _id?: string
  name: string
  _oldName?: string
  in: string
  _oldIn?: string
  type: string
  required: boolean
  description: string
  refEntity: string
}
const paramRows = ref<ParamRow[]>([])

const addParamRow = (defaultIn: string = 'query') => {
  paramRows.value.push({
    _id: `row-${Date.now()}-${Math.random()}`,
    name: '',
    _oldName: '',
    in: defaultIn,
    _oldIn: defaultIn,
    type: 'string',
    required: false,
    description: '',
    refEntity: '',
  })
}

const removeParamRow = (index: number) => {
  const row = paramRows.value[index]
  if (row && (row.in === 'path' || row._oldIn === 'path')) {
    const n = (row.name || row._oldName || '').trim()
    if (n) {
      endpointForm.path = endpointForm.path.replace(`/{${n}}`, '').replace(`{${n}}`, '')
      if (!endpointForm.path || !endpointForm.path.startsWith('/')) {
        endpointForm.path = '/' + (endpointForm.path || '')
      }
    }
  }
  paramRows.value.splice(index, 1)
}

const methodOptions = ['GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'].map(m => ({ label: m, value: m }))
const paramInOptions = [{ label: 'query', value: 'query' }, { label: 'path', value: 'path' }]
const headerInOptions = [{ label: 'header', value: 'header' }, { label: 'cookie', value: 'cookie' }]
const typeOptions = ['string','integer','number','boolean','array','object'].map(t => ({ label: t, value: t }))
const headerTypeOptions = [{ label: 'string', value: 'string' }, { label: 'integer', value: 'integer' }]

const entityOptions = computed(() => [
  { label: 'Custom', value: '' },
  ...props.entities.map(e => ({ label: e.name, value: e.name }))
])

const documentDraft = ref('')
const monacoEditorRef = shallowRef<Monaco.editor.IStandaloneCodeEditor | null>(null)
const mockCaseEditorRef = ref<InstanceType<typeof ApiMockMockCaseEditor> | null>(null)
const entityPanelRef = ref<InstanceType<typeof EntityPanel> | null>(null)



/* ---- Virtual mock URL ---- */
const mockBaseUrl = computed(() => {
  if (!props.endpoint) return ''
  let origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000'
  if (api.defaults.baseURL) {
    origin = api.defaults.baseURL
    if (origin.endsWith('/api')) {
      origin = origin.slice(0, -4)
    }
  }
  return `${origin}/mock/${props.wsId}/${props.taskId}${props.endpoint.path}`
})

const urlCopied = ref(false)
const copyMockUrl = async () => {
  if (!mockBaseUrl.value) return
  try {
    await navigator.clipboard.writeText(mockBaseUrl.value)
    urlCopied.value = true
    setTimeout(() => { urlCopied.value = false }, 1600)
  } catch { /* ignore */ }
}

/* ---- Watchers ---- */
watch(
  () => props.endpoint,
  (endpoint) => {
    if (!endpoint) {
      endpointForm.rowVersion = 1
      endpointForm.method = 'GET'
      endpointForm.path = '/'
      endpointForm.operationId = ''
      endpointForm.tag = ''
      endpointForm.summary = ''
      endpointForm.requestSchemaObj = {}
      endpointForm.responseSchemaObj = {}
      paramRows.value = []
      return
    }
    endpointForm.rowVersion = endpoint.row_version
    endpointForm.method = endpoint.method
    endpointForm.path = endpoint.path
    endpointForm.operationId = endpoint.operation_id || ''
    endpointForm.tag = endpoint.tag || ''
    endpointForm.summary = endpoint.summary || ''
    endpointForm.requestSchemaObj = JSON.parse(JSON.stringify(endpoint.request_schema_json || {}))
    endpointForm.responseSchemaObj = JSON.parse(JSON.stringify(endpoint.response_schema_json || {}))
    // Parse parameters_json into visual rows
    const params = Array.isArray(endpoint.parameters_json) ? endpoint.parameters_json : []
    paramRows.value = params.map((p: Record<string, unknown>) => {
      let typeStr = String((p.schema as Record<string, unknown>)?.type || p.type || 'string')
      let refEnt = ''
      const schemaRef = (p.schema as Record<string, unknown>)?.$ref as string
      if (schemaRef) {
        typeStr = 'object'
        const parts = schemaRef.split('/')
        refEnt = parts[parts.length - 1] || ''
      }
      return {
        _id: `row-${Date.now()}-${Math.random()}`,
        name: String(p.name || ''),
        _oldName: String(p.name || ''),
        in: String(p.in || 'query'),
        _oldIn: String(p.in || 'query'),
        type: typeStr,
        refEntity: refEnt,
        required: Boolean(p.required),
        description: String(p.description || ''),
      }
    })
    if (activeTab.value === 'document') {
      nextTick(() => focusDocumentForEndpoint())
    }
  },
  { immediate: true },
)

watch(
  () => props.document?.source_version_id,
  () => {
    documentDraft.value = props.document?.content || ''
  },
  { immediate: true },
)

watch(
  () => endpointForm.path,
  (newPath) => {
    const matches = [...newPath.matchAll(/\{([^}]+)\}/g)]
    const pathParamNames = matches.map((m) => m[1])

    for (const name of pathParamNames) {
      if (!name) continue
      const exists = paramRows.value.find((r) => r.in === 'path' && r.name === name)
      if (!exists) {
        paramRows.value.push({
          _id: `row-${Date.now()}-${Math.random()}`,
          name,
          _oldName: name,
          in: 'path',
          _oldIn: 'path',
          type: 'string',
          required: true,
          description: '',
          refEntity: '',
        })
      }
    }
  },
)

watch(
  () => paramRows.value,
  (newRows) => {
    let newPath = endpointForm.path
    let changed = false
    
    for (const row of newRows) {
      const name = row.name.trim()
      const oldName = (row._oldName || '').trim()
      const currentIn = row.in
      const oldIn = row._oldIn || 'query'

      if (currentIn === 'path') {
        if (oldIn !== 'path') {
          if (name && !newPath.includes(`{${name}}`)) {
            newPath = newPath.endsWith('/') ? `${newPath}{${name}}` : `${newPath}/{${name}}`
            changed = true
          }
        } else {
          if (name !== oldName) {
            if (oldName && newPath.includes(`{${oldName}}`)) {
              if (name) {
                newPath = newPath.replace(`{${oldName}}`, `{${name}}`)
              } else {
                newPath = newPath.replace(`/{${oldName}}`, '').replace(`{${oldName}}`, '')
              }
              changed = true
            } else if (name && !newPath.includes(`{${name}}`)) {
              newPath = newPath.endsWith('/') ? `${newPath}{${name}}` : `${newPath}/{${name}}`
              changed = true
            }
          }
        }
      } else if (oldIn === 'path') {
        if (oldName && newPath.includes(`{${oldName}}`)) {
          newPath = newPath.replace(`/{${oldName}}`, '').replace(`{${oldName}}`, '')
          changed = true
        } else if (name && newPath.includes(`{${name}}`)) {
          newPath = newPath.replace(`/{${name}}`, '').replace(`{${name}}`, '')
          changed = true
        }
      }

      if (row.name !== row._oldName || row.in !== row._oldIn) {
         row._oldName = row.name
         row._oldIn = row.in
      }
    }
    
    if (changed) {
      if (!newPath || !newPath.startsWith('/')) newPath = '/' + (newPath || '')
      endpointForm.path = newPath
    }
  },
  { deep: true },
)

const documentLanguage = computed(() => {
  const content = (documentDraft.value || '').trimStart()
  if (content.startsWith('{') || content.startsWith('[')) return 'json'
  return 'yaml'
})

const documentDirty = computed(() => documentDraft.value !== (props.document?.content || ''))

const editorOptions = computed<Monaco.editor.IStandaloneEditorConstructionOptions>(() => ({
  readOnly: !props.canManage || props.documentLoading,
  minimap: { enabled: false },
  fontSize: 13,
  lineHeight: 22,
  padding: { top: 14, bottom: 14 },
  scrollBeyondLastLine: false,
  wordWrap: 'on',
  automaticLayout: true,
}))

const handleEditorMount = (
  editor: Monaco.editor.IStandaloneCodeEditor,
  _monaco: typeof import('monaco-editor'),
) => {
  monacoEditorRef.value = editor
  focusDocumentForEndpoint()
}



const focusDocumentForEndpoint = () => {
  const editor = monacoEditorRef.value
  if (!editor || !props.endpoint) return
  const model = editor.getModel()
  if (!model) return
  const matches = model.findMatches(props.endpoint.path, false, false, false, null, true)
  if (matches.length === 0) return
  const first = matches[0].range
  editor.revealRangeInCenter(first)
  editor.setPosition({ lineNumber: first.startLineNumber, column: first.startColumn })
}

/* ---- Submit handlers ---- */
const submitEndpoint = () => {
  if (!props.endpoint) return
  // Build parameters from visual rows
  const parametersJson = paramRows.value
    .filter((row) => row.name.trim())
    .map((row) => ({
      name: row.name.trim(),
      in: row.in,
      required: row.required,
      description: row.description || undefined,
      schema: (row.type === 'object' && row.refEntity) ? { $ref: `#/components/schemas/${row.refEntity}` } : { type: row.type },
    }))
  emit('save-endpoint', {
    row_version: endpointForm.rowVersion,
    method: endpointForm.method,
    path: endpointForm.path,
    operation_id: endpointForm.operationId || null,
    tag: endpointForm.tag || null,
    summary: endpointForm.summary || null,
    parameters_json: parametersJson.length > 0 ? parametersJson : null,
    request_schema_json: Object.keys(endpointForm.requestSchemaObj || {}).length > 0 ? endpointForm.requestSchemaObj : null,
    responses_json: null, // Let backend derive responses_json from response_schema_json
    response_schema_json: Object.keys(endpointForm.responseSchemaObj || {}).length > 0 ? endpointForm.responseSchemaObj : null,
    entity_refs_json: null,
  })
}

const submitDocument = () => {
  if (!props.document) return
  emit('save-document', { content: documentDraft.value })
}

defineExpose({
  triggerPrimarySave: () => {
    if (activeTab.value === 'mock') {
      mockCaseEditorRef.value?.triggerSave()
      return
    }
    if (activeTab.value === 'document') {
      submitDocument()
      return
    }
    submitEndpoint()
  },
  triggerCaseSave: () => {
    mockCaseEditorRef.value?.triggerSave()
  },
  triggerCreateGlobalEntity: () => {
    activeTab.value = 'entities'
    nextTick(() => {
      entityPanelRef.value?.openCreateForm('global')
    })
  },
})
</script>

<template>
  <section class="workspace glass-panel">
    <div v-if="!endpoint" class="workspace-empty">
      <div class="empty-copy">
        <span class="empty-kicker">{{ $t('api_mock.endpoint_editor') }}</span>
        <h2>{{ $t('api_mock.select_endpoint_hint') }}</h2>
        <p>{{ $t('api_mock.workspace_empty_hint') }}</p>
      </div>
    </div>

    <template v-else>
      <!-- Header: endpoint info + tabs -->
      <header class="workspace-head">
        <div class="head-info">
          <div class="endpoint-headline">
            <span class="method-pill">{{ endpoint.method }}</span>
            <h2>{{ endpoint.path }}</h2>
          </div>
          <p>{{ endpoint.summary || $t('api_mock.summary_empty') }}</p>
        </div>

        <!-- Mock URL bar -->
        <div class="mock-url-bar">
          <span class="mock-url-label">Mock URL</span>
          <code class="mock-url-value">{{ mockBaseUrl }}</code>
          <button type="button" class="copy-btn" :title="$t('api_mock.copy_mock_url')" @click="copyMockUrl">
            <Copy class="w-3 h-3" />
            {{ urlCopied ? '✓' : '' }}
          </button>
        </div>
      </header>

      <!-- Tab bar -->
      <nav class="tab-bar">
        <button type="button" class="tab-btn" :class="{ active: activeTab === 'structure' }" @click="activeTab = 'structure'">
          <Braces class="w-4 h-4" />
          {{ $t('api_mock.tab_structure') }}
        </button>
        <button type="button" class="tab-btn" :class="{ active: activeTab === 'mock' }" @click="activeTab = 'mock'">
          <Layers class="w-4 h-4" />
          {{ $t('api_mock.tab_mock_response') }}
        </button>
        <button type="button" class="tab-btn" :class="{ active: activeTab === 'entities' }" @click="activeTab = 'entities'">
          <Database class="w-4 h-4" />
          {{ $t('api_mock.tab_entities') }}
        </button>
        <div class="tab-spacer" />
        <button
          type="button"
          class="tab-btn doc-btn"
          :class="{ active: activeTab === 'document' }"
          @click="activeTab = 'document'; nextTick(() => focusDocumentForEndpoint())"
        >
          <FileCode2 class="w-4 h-4" />
          {{ $t('api_mock.document_tab') }}
        </button>
      </nav>

      <div v-if="swaggerMutationLocked" class="lock-banner">
        {{ $t('api_mock.ai_auto_mock_locked_project_swagger_mutation') }}
      </div>

      <!-- ===== Tab: Structure ===== -->
      <!-- ===== Tab: Structure (Postman Concept) ===== -->
      <section v-if="activeTab === 'structure'" class="tab-content structure-tab-layout">
        
        <!-- URL Bar (High Level Action) -->
        <div class="url-action-bar">
          <div style="display: flex; gap: 0.5rem; align-items: stretch; width: 100%;">
            <div class="url-input-group" style="flex: 1;">
              <BaseSelect v-model="endpointForm.method" :options="methodOptions" :disabled="!canManage" class="method-selector pm-val-select" style="width: 110px;" />
              <div class="path-input-wrapper">
                <input v-model="endpointForm.path" class="path-input" :disabled="!canManage" :placeholder="$t('api_mock.placeholder_url_path')">
              </div>
            </div>
            <button type="button" class="unified-save-btn" :disabled="!canManage || savingEndpoint" @click="submitEndpoint">
              <Save class="w-4 h-4" />
              <span>{{ savingEndpoint ? $t('common.saving') : $t('common.save') }}</span>
            </button>
          </div>
        </div>

        <!-- Inner Structure Tabs -->
        <nav class="inner-tabs-nav">
          <button type="button" :class="['inner-tab-btn', { active: activeStructureTab === 'params' }]" @click="activeStructureTab = 'params'">{{ $t('api_mock.tab_inner_params') }}</button>
          <button type="button" :class="['inner-tab-btn', { active: activeStructureTab === 'headers' }]" @click="activeStructureTab = 'headers'">{{ $t('api_mock.tab_inner_headers') }}</button>
          <button type="button" :class="['inner-tab-btn', { active: activeStructureTab === 'body' }]" @click="activeStructureTab = 'body'">{{ $t('api_mock.tab_inner_body') }}</button>
          <button type="button" :class="['inner-tab-btn', { active: activeStructureTab === 'responses' }]" @click="activeStructureTab = 'responses'">{{ $t('api_mock.tab_inner_response') }}</button>
          <button type="button" :class="['inner-tab-btn', { active: activeStructureTab === 'settings' }]" @click="activeStructureTab = 'settings'">{{ $t('api_mock.tab_inner_settings') }}</button>
        </nav>

        <!-- Inner Content Area -->
        <div class="inner-tab-container">
          
          <!-- PARAMS -->
          <div v-show="activeStructureTab === 'params'" class="config-panel">
            <div class="panel-head">
              <h4>{{ $t('api_mock.query_path_params') }}</h4>
              <button v-if="canManage" type="button" class="btn-secondary mini" @click="addParamRow('query')">
                <Plus class="w-3 h-3" /> {{ $t('api_mock.add_param') }}
              </button>
            </div>
            <div class="pm-table">
              <div class="pm-row pm-header">
                <div class="pm-col">{{ $t('api_mock.col_key') }}</div>
                <div class="pm-col" style="flex: 0.6">{{ $t('api_mock.col_in') }}</div>
                <div class="pm-col" style="flex: 1.2">{{ $t('api_mock.col_type') }}</div>
                <div class="pm-col" style="flex: 0.4">{{ $t('api_mock.col_req') }}</div>
                <div class="pm-col" style="flex: 1.5">{{ $t('api_mock.col_description') }}</div>
                <div class="pm-col-auto" style="width: 2rem"></div>
              </div>
              <div v-for="(row, i) in paramRows" :key="row._id || `param-${i}`" v-show="row.in === 'query' || row.in === 'path'" class="pm-row">
                  <div class="pm-col"><input v-model="row.name" class="pm-inp" :disabled="!canManage" :placeholder="$t('api_mock.placeholder_key')"></div>
                  <div class="pm-col" style="flex: 0.6">
                    <BaseSelect v-model="row.in" :options="paramInOptions" :disabled="!canManage" size="sm" class="pm-val-select" />
                  </div>
                  <div class="pm-col pm-split" style="flex: 1.2">
                    <BaseSelect v-model="row.type" :options="typeOptions" :disabled="!canManage" size="sm" class="pm-val-select" />
                    <BaseSelect v-if="row.type === 'object'" v-model="row.refEntity" :options="entityOptions" :disabled="!canManage" size="sm" class="pm-val-select custom-ref" />
                  </div>
                  <div class="pm-col pm-check" style="flex: 0.4">
                    <input v-model="row.required" type="checkbox" :disabled="!canManage">
                  </div>
                  <div class="pm-col" style="flex: 1.5"><input v-model="row.description" class="pm-inp" :disabled="!canManage" :placeholder="$t('api_mock.placeholder_description')"></div>
                  <div class="pm-col-auto" style="width: 2rem">
                    <button v-if="canManage" class="pm-del-btn" @click="removeParamRow(i)"><Trash2 class="w-3 h-3" /></button>
                  </div>
              </div>
              <div v-if="!paramRows.some(r => r.in === 'query' || r.in === 'path')" class="pm-empty">{{ $t('api_mock.no_params_configured') }}</div>
            </div>
          </div>

          <!-- HEADERS -->
          <div v-show="activeStructureTab === 'headers'" class="config-panel">
            <div class="panel-head">
              <h4>{{ $t('api_mock.headers_cookies') }}</h4>
              <button v-if="canManage" type="button" class="btn-secondary mini" @click="addParamRow('header')">
                <Plus class="w-3 h-3" /> {{ $t('api_mock.add_header') }}
              </button>
            </div>
            <div class="pm-table">
              <div class="pm-row pm-header">
                <div class="pm-col">{{ $t('api_mock.col_key') }}</div>
                <div class="pm-col" style="flex: 0.6">{{ $t('api_mock.col_in') }}</div>
                <div class="pm-col" style="flex: 1.2">{{ $t('api_mock.col_type') }}</div>
                <div class="pm-col" style="flex: 0.4">{{ $t('api_mock.col_req') }}</div>
                <div class="pm-col" style="flex: 1.5">{{ $t('api_mock.col_description') }}</div>
                <div class="pm-col-auto" style="width: 2rem"></div>
              </div>
              <div v-for="(row, i) in paramRows" :key="row._id || `hdr-${i}`" v-show="row.in === 'header' || row.in === 'cookie'" class="pm-row">
                  <div class="pm-col"><input v-model="row.name" class="pm-inp" :disabled="!canManage" :placeholder="$t('api_mock.placeholder_key')"></div>
                  <div class="pm-col" style="flex: 0.6">
                    <BaseSelect v-model="row.in" :options="headerInOptions" :disabled="!canManage" size="sm" class="pm-val-select" />
                  </div>
                  <div class="pm-col pm-split" style="flex: 1.2">
                    <BaseSelect v-model="row.type" :options="headerTypeOptions" :disabled="!canManage" size="sm" class="pm-val-select" />
                  </div>
                  <div class="pm-col pm-check" style="flex: 0.4">
                    <input v-model="row.required" type="checkbox" :disabled="!canManage">
                  </div>
                  <div class="pm-col" style="flex: 1.5"><input v-model="row.description" class="pm-inp" :disabled="!canManage" :placeholder="$t('api_mock.placeholder_description')"></div>
                  <div class="pm-col-auto" style="width: 2rem">
                    <button v-if="canManage" class="pm-del-btn" @click="removeParamRow(i)"><Trash2 class="w-3 h-3" /></button>
                  </div>
              </div>
              <div v-if="!paramRows.some(r => r.in === 'header' || r.in === 'cookie')" class="pm-empty">{{ $t('api_mock.no_headers_configured') }}</div>
            </div>
          </div>

          <!-- BODY -->
          <div v-show="activeStructureTab === 'body'" class="config-panel">
            <div class="panel-head">
              <h4>{{ $t('api_mock.request_body_schema') }}</h4>
            </div>
            <div class="pm-table schema-table-wrapper">
              <div class="pm-row pm-header">
                <div class="pm-col" style="flex: 2">{{ $t('api_mock.col_key_field') }}</div>
                <div class="pm-col" style="flex: 1.2">{{ $t('api_mock.col_type') }}</div>
                <div class="pm-col pm-check" style="flex: 0.4">{{ $t('api_mock.col_req') }}</div>
                <div class="pm-col" style="flex: 1.5">{{ $t('api_mock.col_description') }}</div>
                <div class="pm-col-auto" style="width: 3.5rem"></div>
              </div>
              <ApiMockSchemaNode v-model="endpointForm.requestSchemaObj" :isRoot="true" />
            </div>
          </div>

          <!-- RESPONSE -->
          <div v-show="activeStructureTab === 'responses'" class="config-panel">
            <div class="panel-head">
              <h4>{{ $t('api_mock.response_schema_200') }}</h4>
            </div>
            <div class="pm-table schema-table-wrapper">
              <div class="pm-row pm-header">
                <div class="pm-col" style="flex: 2">{{ $t('api_mock.col_key_field') }}</div>
                <div class="pm-col" style="flex: 1.2">{{ $t('api_mock.col_type') }}</div>
                <div class="pm-col pm-check" style="flex: 0.4">{{ $t('api_mock.col_req') }}</div>
                <div class="pm-col" style="flex: 1.5">{{ $t('api_mock.col_description') }}</div>
                <div class="pm-col-auto" style="width: 3.5rem"></div>
              </div>
              <ApiMockSchemaNode v-model="endpointForm.responseSchemaObj" :isRoot="true" />
            </div>
          </div>

          <!-- SETTINGS -->
          <div v-show="activeStructureTab === 'settings'" class="config-panel">
            <div class="panel-head">
              <h4>{{ $t('api_mock.endpoint_metadata') }}</h4>
            </div>
            <div class="pm-settings-grid">
              <label class="pm-field">
                <span>{{ $t('api_mock.operation_id') }}</span>
                <input v-model="endpointForm.operationId" class="pm-inp" :disabled="!canManage" :placeholder="$t('api_mock.placeholder_operation_id')">
              </label>
              <label class="pm-field">
                <span>{{ $t('api_mock.tag') }}</span>
                <input v-model="endpointForm.tag" class="pm-inp" :disabled="!canManage" :placeholder="$t('api_mock.placeholder_tag')">
              </label>
              <label class="pm-field full-wide">
                <span>{{ $t('api_mock.form_summary') }}</span>
                <input v-model="endpointForm.summary" class="pm-inp" :disabled="!canManage" :placeholder="$t('api_mock.placeholder_summary')">
              </label>
            </div>
          </div>

        </div>
      </section>

      <!-- ===== Tab: Mock Response ===== -->
      <section v-if="activeTab === 'mock'" class="tab-content">
        <ApiMockMockCaseEditor
          ref="mockCaseEditorRef"
          :endpoint="endpoint"
          :cases="cases"
          :selected-case-id="selectedCaseId"
          :can-manage="canManageMock"
          :project-auto-mock-locked="projectAutoMockLocked"
          :current-endpoint-auto-mock-locked="currentEndpointAutoMockLocked"
          :auto-mock-busy="autoMockBusy"
          :auto-mock-job="autoMockJob"
          :saving-case="savingCase"
          :deleting-case="deletingCase"
          :mock-base-url="mockBaseUrl"
          @select-case="emit('select-case', $event)"
          @create-case="emit('create-case')"
          @start-auto-mock="emit('start-auto-mock')"
          @save-case="emit('save-case', $event)"
          @delete-case="emit('delete-case', $event)"
        />
      </section>

      <!-- ===== Tab: Entities ===== -->
      <section v-if="activeTab === 'entities'" class="tab-content">
        <EntityPanel
          ref="entityPanelRef"
          :entities="entities"
          :endpoint="endpoint"
          :can-manage="canManage"
          :hide-global-action="true"

          @create-entity="emit('create-entity', $event)"
          @update-entity="emit('update-entity', $event)"
          @delete-entity="emit('delete-entity', $event)"
        />
      </section>

      <!-- ===== Tab: Document editor ===== -->
      <section v-if="activeTab === 'document'" class="tab-content editor-card" style="display: flex; flex-direction: column;">
        <div class="editor-card-head">
          <div>
            <span>{{ $t('api_mock.document_tab') }}</span>
            <h3>{{ $t('api_mock.document_editor_title') }}</h3>
          </div>
          <div class="doc-actions">
            <span v-if="documentDirty" class="dirty-pill">{{ $t('api_mock.document_dirty') }}</span>
            <button type="button" class="btn-primary mini" :disabled="!canManage || savingDocument || documentLoading" @click="submitDocument">
              <Save class="w-4 h-4" />
              {{ savingDocument ? $t('api_mock.saving') : $t('api_mock.save_document') }}
            </button>
          </div>
        </div>
        <p class="document-hint">{{ $t('api_mock.document_hint') }}</p>
        <div class="monaco-shell" style="flex: 1;">
          <VueMonacoEditor
            v-model:value="documentDraft"
            :language="documentLanguage"
            theme="vs"
            :options="editorOptions"
            width="100%"
            height="100%"
            @mount="handleEditorMount"
          />
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.workspace {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  min-height: 100%;
  padding: 1rem;
  background: #ffffff;
  border: 1px solid #e2e8f0;
}

.workspace-empty {
  flex: 1;
  min-height: 30rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 24px;
  border: 1px dashed #e2e8f0;
  background: rgba(248, 250, 252, 0.78);
  text-align: center;
}

.empty-kicker,
.editor-card-head span {
  color: #0369a1;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.empty-copy h2,
.editor-card-head h3 {
  margin: 0.36rem 0 0;
}

.empty-copy p,
.workspace-head p,
.document-hint {
  margin: 0.45rem 0 0;
  color: #64748b;
  line-height: 1.65;
}

/* ---- Header ---- */
.workspace-head {
  display: flex;
  justify-content: space-between;
  gap: 0.85rem;
  align-items: flex-start;
  flex-wrap: wrap;
}

.head-info {
  flex: 1;
  min-width: 0;
}

.endpoint-headline {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.endpoint-headline h2 {
  margin: 0;
  word-break: break-all;
  font-size: 1.1rem;
}

.method-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 4rem;
  padding: 0.22rem 0.56rem;
  border-radius: 999px;
  background: linear-gradient(135deg, #0ea5e9, #2563eb);
  color: #fff;
  font-size: 0.74rem;
  font-weight: 800;
}

/* ---- Mock URL bar ---- */
.mock-url-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.65rem;
  border-radius: 12px;
  border: 1px solid #dbeafe;
  background: rgba(248, 250, 252, 0.9);
  font-size: 0.76rem;
  max-width: 100%;
  overflow: hidden;
}

.mock-url-label {
  color: #0369a1;
  font-weight: 700;
  flex-shrink: 0;
}

.mock-url-value {
  color: #334155;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1;
}

.copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  padding: 0.2rem 0.45rem;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #eff6ff;
  color: #0369a1;
  cursor: pointer;
  font-size: 0.72rem;
  font-weight: 600;
  flex-shrink: 0;
}

.copy-btn:hover {
  background: #dbeafe;
}

/* ---- Tab bar ---- */
.tab-bar {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.25rem;
  border-radius: 18px;
  background: rgba(241, 245, 249, 0.7);
  border: 1px solid #e2e8f0;
}

.tab-spacer {
  flex: 1;
}

.lock-banner {
  border: 1px solid rgba(251, 146, 60, 0.45);
  background: rgba(255, 247, 237, 0.95);
  color: #9a3412;
  border-radius: 12px;
  padding: 0.62rem 0.78rem;
  font-size: 0.82rem;
  font-weight: 600;
}

.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-height: 2.5rem;
  border-radius: 14px;
  border: 1px solid transparent;
  background: transparent;
  color: #475569;
  padding: 0.5rem 0.85rem;
  font-weight: 600;
  font-size: 0.82rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tab-btn:hover {
  background: rgba(255, 255, 255, 0.9);
}

.tab-btn.active {
  background: linear-gradient(135deg, #0ea5e9, #2563eb);
  color: #fff;
  box-shadow: 0 6px 16px rgba(14, 165, 233, 0.2);
  border-color: transparent;
}

.doc-btn {
  font-size: 0.76rem;
}

.doc-btn.active {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
}

/* ---- Tab content ---- */
.tab-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

/* ---- Editor card ---- */
.editor-card {
  border-radius: 20px;
  border: 1px solid #e2e8f0;
  background: rgba(255, 255, 255, 0.88);
  padding: 1rem;
}

.editor-card-head {
  display: flex;
  justify-content: space-between;
  gap: 0.85rem;
  align-items: flex-start;
  margin-bottom: 0.8rem;
}



.doc-actions {
  display: inline-flex;
  align-items: center;
  gap: 0.6rem;
}

.dirty-pill {
  display: inline-flex;
  padding: 0.22rem 0.56rem;
  border-radius: 999px;
  background: rgba(254, 240, 138, 0.5);
  color: #854d0e;
  font-size: 0.74rem;
  font-weight: 700;
}

/* ---- Postman-style Structure UI ---- */
.structure-tab-layout {
  display: flex;
  flex-direction: column;
  gap: 0;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  overflow: hidden;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

.url-action-bar {
  padding: 0.75rem 1rem;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.url-input-group {
  display: flex;
  align-items: center;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.method-selector {
  border: none;
  background: transparent;
  padding: 0.5rem 0.75rem;
  font-weight: 700;
  color: #0ea5e9;
  font-size: 0.85rem;
  outline: none;
  cursor: pointer;
  appearance: none;
}

.path-input-wrapper {
  flex: 1;
  border-left: 1px solid #e2e8f0;
}

.path-input {
  width: 100%;
  border: none;
  padding: 0.5rem 0.75rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.85rem;
  color: #1e293b;
  outline: none;
  min-height: 100%;
}

.unified-save-btn {
  border: none;
  border-radius: 6px;
  padding: 0 1rem;
  min-height: 2.22rem;
  background: #0ea5e9;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  color: white;
  font-weight: 600;
  font-size: 0.85rem;
  cursor: pointer;
}
.unified-save-btn:hover:not(:disabled) {
  background: #0284c7;
}
.unified-save-btn:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

/* Inner Tabs */
.inner-tabs-nav {
  display: flex;
  gap: 1.5rem;
  padding: 0 1.25rem;
  border-bottom: 1px solid #e2e8f0;
  background: #ffffff;
}

.inner-tab-btn {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 0.6rem 0.2rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: -1px;
}
.inner-tab-btn:hover {
  color: #0f172a;
}
.inner-tab-btn.active {
  color: #0ea5e9;
  border-bottom-color: #0ea5e9;
}

.inner-tab-container {
  flex: 1;
  padding: 1.25rem;
  overflow-y: auto;
  min-height: 20rem;
}

/* PM Config Panels */
.config-panel {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.panel-head h4 {
  margin: 0;
  color: #334155;
  font-size: 0.85rem;
  font-weight: 700;
}

/* pm classes extracted to unscoped style block below */

.pm-empty {
  padding: 1rem;
  font-size: 0.8rem;
  color: #94a3b8;
  text-align: center;
}

.pm-settings-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1.25rem;
}

.pm-field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.pm-field.full-wide {
  grid-column: 1 / -1;
}
.pm-field span {
  font-size: 0.78rem;
  font-weight: 600;
  color: #475569;
}
.pm-field .pm-inp {
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #ffffff;
}
.pm-field .pm-inp:focus {
  border-color: #38bdf8;
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.1);
  background: #ffffff;
}

.pm-sm-select {
  width: auto;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 0.2rem 0.5rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: #0ea5e9;
  background: #f0f9ff;
  cursor: pointer;
}

.schema-wrapper.expanded {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  padding: 0.5rem;
  min-height: 12rem;
}

.monaco-shell {
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
}

/* ---- Utility ---- */
.mini {
  padding: 0.42rem 0.78rem;
  font-size: 0.78rem;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.w-4 { width: 1rem; height: 1rem; }
.w-3 { width: 0.75rem; height: 0.75rem; }

@media (max-width: 1200px) {
  .top-grid,
  .top-grid.triple,
  .columns {
    grid-template-columns: 1fr;
  }
  .param-table-head,
  .param-table-row {
    grid-template-columns: 1fr 0.6fr 0.6fr 0.4fr 1.5fr 2rem;
  }
}

@media (max-width: 900px) {
  .workspace-head,
  .editor-card-head {
    flex-direction: column;
  }
  .tab-bar {
    flex-wrap: wrap;
  }
  .tab-btn {
    flex: 1;
    justify-content: center;
  }
}
</style>

<style>
/* Global PM Table Styles for sub-components to inherit */
.pm-table {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  /* overflow tracking removed to avoid clipping absolute dropdowns */
}

.pm-row {
  display: flex;
  align-items: stretch;
  border-bottom: 1px solid #f1f5f9;
}
.pm-row:last-child {
  border-bottom: none;
}

.pm-header {
  background: #f8fafc;
  font-size: 0.7rem;
  font-weight: 600;
  color: #64748b;
  border-bottom: 1px solid #e2e8f0;
}
.pm-header .pm-col {
  padding: 0.4rem 0.6rem;
}

.pm-col {
  flex: 1;
  border-right: 1px solid #f1f5f9;
  display: flex;
  align-items: center;
}
.pm-col:last-child {
  border-right: none;
}
.pm-col-auto {
  display: flex;
  align-items: center;
  justify-content: center;
}

.pm-inp {
  width: 100%;
  border: none;
  background: transparent;
  padding: 0.45rem 0.6rem;
  font-size: 0.78rem;
  color: #334155;
  outline: none;
}
.pm-inp:focus {
  background: #f8fafc;
}
.pm-inp:disabled {
  color: #94a3b8;
  cursor: not-allowed;
}

.pm-split {
  display: flex;
  gap: 0;
}
.custom-ref {
  border-left: 1px dashed #cbd5e1;
  max-width: 50%;
}

.pm-check {
  display: flex;
  align-items: center;
  justify-content: center;
}

.pm-val-select .select-trigger {
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
  min-height: 100%;
}
.pm-val-select .select-trigger:hover {
  background: #f8fafc !important;
}

.pm-del-btn {
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 0.2rem;
  border-radius: 4px;
}
.pm-del-btn:hover {
  background: #fee2e2;
  color: #ef4444;
}
</style>
