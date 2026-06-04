<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { Plus, Save, Trash2, ArrowLeft, ExternalLink } from 'lucide-vue-next'
import { VueMonacoEditor } from '@guolao/vue-monaco-editor'
import type * as Monaco from 'monaco-editor'
import type { ApiMockEndpoint, ApiMockMockCase } from '@/types/apiMock'
import api from '@/utils/api'

const props = defineProps<{
  endpoint: ApiMockEndpoint | null
  cases: ApiMockMockCase[]
  selectedCaseId: string
  canManage: boolean
  projectAutoMockLocked: boolean
  currentEndpointAutoMockLocked: boolean
  autoMockBusy: boolean
  autoMockJob: { id: string; job_type: string; status: string; progress: number; message?: string | null; result_json?: Record<string, unknown> | null } | null
  savingCase: boolean
  deletingCase: boolean
  mockBaseUrl: string
}>()

const emit = defineEmits<{
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
}>()

const viewMode = ref<'list' | 'detail'>('list')

const currentCase = computed(() => props.cases.find((item) => item.id === props.selectedCaseId) || null)
const isAutoMockRunning = computed(() => props.autoMockBusy || props.projectAutoMockLocked || props.currentEndpointAutoMockLocked)
const autoMockStatusText = computed(() => {
  if (!props.autoMockJob) return ''
  if (props.autoMockJob.status === 'PENDING') return 'api_mock.ai_auto_mock_queued'
  if (props.autoMockJob.status === 'RUNNING') return 'api_mock.ai_auto_mock_running'
  return ''
})

const form = reactive({
  id: '',
  rowVersion: 1,
  name: '',
  description: '',
  isDefault: false,
  sortOrder: 0,
  enableMockjs: true,
  bodyText: '{\n  \n}',
  statusCode: 200,
  headersText: '{\n  \n}',
  cookiesText: '[\n  \n]',
  delayMs: 0,
  enabled: true,
})

type JsonEditorKey = 'body' | 'headers' | 'cookies' | 'requestBodyMatcher'
const jsonEditorDisposables: Partial<Record<JsonEditorKey, Monaco.IDisposable[]>> = {}

const pathMatcherInputs = reactive<Record<string, string>>({})
const queryMatcherInputs = reactive<Record<string, string>>({})
const requestBodyMatcherText = ref('')

const setEditorText = (key: JsonEditorKey, value: string) => {
  if (key === 'body') {
    form.bodyText = value
    return
  }
  if (key === 'headers') {
    form.headersText = value
    return
  }
  if (key === 'cookies') {
    form.cookiesText = value
    return
  }
  requestBodyMatcherText.value = value
}

const formatJsonText = (raw: string): string | null => {
  const text = (raw || '').trim()
  if (!text) return null
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return null
  }
}

const tryFormatEditorJson = (key: JsonEditorKey, editor: Monaco.editor.IStandaloneCodeEditor) => {
  const model = editor.getModel()
  if (!model) return
  const formatted = formatJsonText(model.getValue())
  if (!formatted) return
  if (formatted === model.getValue()) {
    setEditorText(key, formatted)
    return
  }
  editor.executeEdits('json-auto-format', [{
    range: model.getFullModelRange(),
    text: formatted,
    forceMoveMarkers: true,
  }])
  editor.pushUndoStop()
  setEditorText(key, formatted)
}

const disposeEditorBindings = (key: JsonEditorKey) => {
  const disposables = jsonEditorDisposables[key]
  if (!disposables) return
  disposables.forEach((item) => item.dispose())
  jsonEditorDisposables[key] = []
}

const handleJsonEditorMount = (
  key: JsonEditorKey,
  editor: Monaco.editor.IStandaloneCodeEditor,
  _monaco: typeof import('monaco-editor'),
) => {
  disposeEditorBindings(key)
  const disposables: Monaco.IDisposable[] = []

  disposables.push(editor.onDidPaste(() => {
    globalThis.setTimeout(() => {
      tryFormatEditorJson(key, editor)
    }, 0)
  }))
  disposables.push(editor.onDidBlurEditorText(() => {
    tryFormatEditorJson(key, editor)
  }))

  jsonEditorDisposables[key] = disposables

  // Ensure initial text is prettified if backend returned a compact JSON string.
  globalThis.setTimeout(() => {
    tryFormatEditorJson(key, editor)
  }, 0)
}

const mountBodyEditor = (editor: Monaco.editor.IStandaloneCodeEditor, monaco: typeof import('monaco-editor')) => {
  handleJsonEditorMount('body', editor, monaco)
}

const mountHeadersEditor = (editor: Monaco.editor.IStandaloneCodeEditor, monaco: typeof import('monaco-editor')) => {
  handleJsonEditorMount('headers', editor, monaco)
}

const mountCookiesEditor = (editor: Monaco.editor.IStandaloneCodeEditor, monaco: typeof import('monaco-editor')) => {
  handleJsonEditorMount('cookies', editor, monaco)
}

const mountRequestBodyMatcherEditor = (
  editor: Monaco.editor.IStandaloneCodeEditor,
  monaco: typeof import('monaco-editor'),
) => {
  handleJsonEditorMount('requestBodyMatcher', editor, monaco)
}

const parseJson = <T>(raw: string, fallback: T): T => {
  const text = (raw || '').trim()
  if (!text) return fallback
  try {
    return JSON.parse(text) as T
  } catch {
    return fallback
  }
}

const clearRecord = (target: Record<string, string>) => {
  Object.keys(target).forEach((key) => {
    delete target[key]
  })
}

const normalizeInputValue = (value: unknown): string => {
  if (value === null || value === undefined) return ''
  return String(value)
}

const pathParamNames = computed<string[]>(() => {
  const path = String(props.endpoint?.path || '')
  if (!path) return []
  const names = [...path.matchAll(/\{([^}]+)\}/g)]
    .map((match) => String(match[1] || '').trim())
    .filter((name) => name.length > 0)
  return Array.from(new Set(names))
})

const queryParamNames = computed<string[]>(() => {
  const names: string[] = []
  const parameters = Array.isArray(props.endpoint?.parameters_json) ? props.endpoint?.parameters_json : []
  for (const item of parameters) {
    if (!item || typeof item !== 'object') continue
    const inValue = String((item as Record<string, unknown>).in || '').toLowerCase()
    if (inValue !== 'query') continue
    const name = String((item as Record<string, unknown>).name || '').trim()
    if (name) names.push(name)
  }
  return Array.from(new Set(names))
})

const hasPathMatchers = computed(() => pathParamNames.value.length > 0)
const hasQueryMatchers = computed(() => queryParamNames.value.length > 0)
const matcherColumnCount = computed(() => {
  let count = 0
  if (hasPathMatchers.value) count += 1
  if (hasQueryMatchers.value) count += 1
  if (showRequestBodyMatcher.value) count += 1
  return Math.max(count, 1)
})

const hydrateMatcherInputs = () => {
  const existingPath =
    currentCase.value?.request_path_params_json
    && typeof currentCase.value.request_path_params_json === 'object'
    && !Array.isArray(currentCase.value.request_path_params_json)
      ? (currentCase.value.request_path_params_json as Record<string, unknown>)
      : {}

  const existingQuery =
    currentCase.value?.request_query_json
    && typeof currentCase.value.request_query_json === 'object'
    && !Array.isArray(currentCase.value.request_query_json)
      ? (currentCase.value.request_query_json as Record<string, unknown>)
      : {}

  clearRecord(pathMatcherInputs)
  for (const name of pathParamNames.value) {
    pathMatcherInputs[name] = normalizeInputValue(existingPath[name])
  }

  clearRecord(queryMatcherInputs)
  for (const name of queryParamNames.value) {
    queryMatcherInputs[name] = normalizeInputValue(existingQuery[name])
  }

  const existingBody = currentCase.value?.request_body_json
  requestBodyMatcherText.value = existingBody === null || existingBody === undefined
    ? ''
    : (typeof existingBody === 'string' ? existingBody : JSON.stringify(existingBody, null, 2))
}

const buildMatcherRecord = (source: Record<string, string>): Record<string, unknown> | null => {
  const output: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(source)) {
    const normalized = String(value || '').trim()
    if (normalized.length > 0) {
      output[key] = normalized
    }
  }
  return Object.keys(output).length > 0 ? output : null
}

const parseBodyMatcherValue = (): unknown | null => {
  if (!showRequestBodyMatcher.value) return null
  const raw = requestBodyMatcherText.value.trim()
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return raw
  }
}

const resetForm = () => {
  form.id = ''
  form.rowVersion = 1
  form.name = ''
  form.description = ''
  form.isDefault = props.cases.length === 0
  form.sortOrder = props.cases.length
  form.enableMockjs = true
  clearRecord(pathMatcherInputs)
  clearRecord(queryMatcherInputs)
  requestBodyMatcherText.value = ''
  form.bodyText = '{\n  \n}'
  form.statusCode = 200
  form.headersText = '{\n  \n}'
  form.cookiesText = '[\n  \n]'
  form.delayMs = 0
  form.enabled = true
}

watch(
  () => props.selectedCaseId,
  (newId) => {
    if (newId) {
      viewMode.value = 'detail'
    } else if (viewMode.value === 'detail') {
      viewMode.value = 'list'
    }
  }
)

const casesVersionSignature = computed(() =>
  props.cases.map((item) => `${item.id}:${item.row_version}`).join('|'),
)

watch(
  () => [props.selectedCaseId, casesVersionSignature.value],
  () => {
    if (!currentCase.value) {
      if (props.selectedCaseId === '') {
        resetForm()
      }
      return
    }
    form.id = currentCase.value.id
    form.rowVersion = currentCase.value.row_version
    form.name = currentCase.value.name
    form.description = currentCase.value.description || ''
    form.isDefault = currentCase.value.is_default
    form.sortOrder = currentCase.value.sort_order

    const isMockJs = currentCase.value.mode === 'MOCKJS' || !currentCase.value.mode
    form.enableMockjs = isMockJs

    if (isMockJs && currentCase.value.mockjs_template) {
      form.bodyText = currentCase.value.mockjs_template
    } else {
      form.bodyText = JSON.stringify(currentCase.value.static_body_json || {}, null, 2)
    }

    form.statusCode = currentCase.value.status_code || 200
    form.headersText = JSON.stringify(currentCase.value.headers_json || {}, null, 2)
    form.cookiesText = JSON.stringify(currentCase.value.cookies_json || [], null, 2)
    form.delayMs = currentCase.value.delay_ms || 0
    form.enabled = currentCase.value.enabled ?? true
    hydrateMatcherInputs()
  },
  { immediate: true },
)

watch(
  () => [pathParamNames.value.join('|'), queryParamNames.value.join('|'), props.selectedCaseId],
  () => {
    hydrateMatcherInputs()
  },
)

const submit = () => {
  if (!props.endpoint) return
  const isMockjs = form.enableMockjs
  
  emit('save-case', {
    id: form.id || undefined,
    row_version: form.id ? form.rowVersion : undefined,
    name: form.name || 'Default Case',
    description: form.description || null,
    is_default: form.isDefault,
    sort_order: Number(form.sortOrder),
    mode: isMockjs ? 'MOCKJS' : 'STATIC',
    request_path_params_json: hasPathMatchers.value ? buildMatcherRecord(pathMatcherInputs) : null,
    request_query_json: hasQueryMatchers.value ? buildMatcherRecord(queryMatcherInputs) : null,
    request_body_json: parseBodyMatcherValue(),
    static_body_json: isMockjs ? null : parseJson<Record<string, unknown>>(form.bodyText, {}),
    mockjs_template: isMockjs ? form.bodyText : null,
    status_code: Number(form.statusCode),
    headers_json: parseJson<Record<string, unknown>>(form.headersText, {}),
    cookies_json: parseJson<Array<Record<string, unknown>>>(form.cookiesText, []),
    delay_ms: Number(form.delayMs),
    enabled: Boolean(form.enabled),
  })
}

const backToList = () => {
  viewMode.value = 'list'
  emit('select-case', '')
}



const selectCaseLocal = (id: string) => {
  viewMode.value = 'detail'
  emit('select-case', id)
}

const handleAddCase = () => {
  viewMode.value = 'detail'
  emit('create-case')
}

const isBodyMethod = (method: string): boolean => {
  const normalized = String(method || '').toUpperCase()
  return normalized === 'POST' || normalized === 'PUT' || normalized === 'PATCH'
}

const buildBrowseRequest = (): { method: string; url: string; body: string | null; contentType: string | null } | null => {
  if (!props.endpoint || !props.mockBaseUrl) return null

  const method = String(props.endpoint.method || 'GET').trim().toUpperCase()
  const pathRecord = hasPathMatchers.value ? buildMatcherRecord(pathMatcherInputs) : null
  const queryRecord = hasQueryMatchers.value ? buildMatcherRecord(queryMatcherInputs) : null

  let resolvedUrl = String(props.mockBaseUrl || '')
  if (pathRecord) {
    resolvedUrl = resolvedUrl.replace(/\{([^}]+)\}/g, (match, rawName: string) => {
      const key = String(rawName || '').trim()
      const value = pathRecord[key]
      if (value === null || value === undefined || String(value).trim() === '') return match
      return encodeURIComponent(String(value))
    })
  }

  const urlObject = new URL(resolvedUrl, window.location.origin)
  if (queryRecord) {
    for (const [key, value] of Object.entries(queryRecord)) {
      if (!key || value === null || value === undefined) continue
      urlObject.searchParams.set(key, String(value))
    }
  }

  let body: string | null = null
  let contentType: string | null = null
  if (isBodyMethod(method)) {
    const rawBody = parseBodyMatcherValue()
    if (rawBody !== null && rawBody !== undefined) {
      if (typeof rawBody === 'string') {
        const normalized = rawBody.trim()
        body = normalized.length > 0 ? normalized : null
        if (body) {
          contentType = normalized.startsWith('{') || normalized.startsWith('[')
            ? 'application/json'
            : 'text/plain;charset=UTF-8'
        }
      } else {
        body = JSON.stringify(rawBody)
        contentType = 'application/json'
      }
    }
  }

  return {
    method,
    url: urlObject.toString(),
    body,
    contentType,
  }
}

const escapeHtml = (value: unknown): string => {
  const text = String(value ?? '')
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

const renderPreviewPage = (
  popup: Window,
  payload: { method: string; url: string; body: string | null; contentType: string | null },
  result: { statusLabel: string; responseText: string },
) => {
  const requestView = {
    method: payload.method,
    url: payload.url,
    contentType: payload.contentType || null,
    body: payload.body
      ? (() => {
          try {
            return JSON.parse(payload.body)
          } catch {
            return payload.body
          }
        })()
      : null,
  }

  const html = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Mock Request Preview</title>
  <style>
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
      background: #f8fafc;
      color: #0f172a;
      padding: 16px;
    }
    .panel {
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 14px;
      margin-bottom: 12px;
    }
    h1 {
      margin: 0 0 10px;
      font-size: 16px;
      line-height: 1.4;
    }
    .meta {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 4px 8px;
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 999px;
      font-weight: 700;
      color: #1d4ed8;
      margin-bottom: 8px;
      font-size: 12px;
    }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 10px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      font-size: 12px;
      line-height: 1.6;
      max-height: 55vh;
      overflow: auto;
    }
    .status {
      font-size: 12px;
      margin-bottom: 8px;
      color: #475569;
    }
    .err { color: #b91c1c; }
  </style>
</head>
<body>
  <section class="panel">
    <h1>请求信息</h1>
    <div class="meta" id="req-meta"></div>
    <pre id="req-text"></pre>
  </section>
  <section class="panel">
    <h1>响应结果</h1>
    <div class="status">${escapeHtml(result.statusLabel)}</div>
    <pre>${escapeHtml(result.responseText)}</pre>
  </section>
  <script>
    const reqMetaEl = document.getElementById('req-meta');
    const reqTextEl = document.getElementById('req-text');
    reqMetaEl.textContent = ${JSON.stringify(`${payload.method} ${payload.url}`)};
    reqTextEl.textContent = ${JSON.stringify(JSON.stringify(requestView, null, 2))};
  <\/script>
</body>
</html>`

  popup.document.open()
  popup.document.write(html)
  popup.document.close()
}

const browseEndpoint = async () => {
  const payload = buildBrowseRequest()
  if (!payload) return

  const desktopOpenExternal = window.sddDesktop?.system?.openExternal
  if (desktopOpenExternal) {
    try {
      await desktopOpenExternal(payload.url)
      return
    } catch {
      // Fallback to in-app preview flow below when desktop bridge fails.
    }
  }

  const popup = window.open('', '_blank')
  if (!popup) return

  const loadingHtml = `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8" /><title>Mock Request Preview</title></head><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif; padding: 16px; color: #334155;">请求执行中...</body></html>`
  popup.document.open()
  popup.document.write(loadingHtml)
  popup.document.close()

  const headers: Record<string, string> = {}
  if (payload.contentType) {
    headers['Content-Type'] = payload.contentType
  }

  const shouldSendBody = payload.body !== null && payload.body !== undefined && isBodyMethod(payload.method)

  try {
    const response = await api.request({
      url: payload.url,
      method: payload.method,
      headers,
      data: shouldSendBody ? payload.body : undefined,
      validateStatus: () => true,
      transformResponse: [(data) => data],
    })

    let responseText = ''
    if (typeof response.data === 'string') {
      const raw = response.data
      try {
        responseText = JSON.stringify(JSON.parse(raw), null, 2)
      } catch {
        responseText = raw
      }
    } else {
      responseText = JSON.stringify(response.data, null, 2)
    }

    renderPreviewPage(popup, payload, {
      statusLabel: `HTTP ${response.status} ${response.statusText || ''}`.trim(),
      responseText,
    })
  } catch (error) {
    const err = error as { message?: string }
    renderPreviewPage(popup, payload, {
      statusLabel: '请求失败',
      responseText: err.message || String(error),
    })
  }
}

const editorOptions = computed(() => ({
  readOnly: !props.canManage,
  minimap: { enabled: false },
  fontSize: 13,
  lineHeight: 22,
  scrollBeyondLastLine: false,
  wordWrap: 'on',
  automaticLayout: true,
  tabSize: 2,
  formatOnPaste: true,
  formatOnType: true,
  folding: true,
  foldingStrategy: 'auto',
  showFoldingControls: 'always',
  lineNumbers: 'on',
  lineNumbersMinChars: 3,
}))

const showRequestBodyMatcher = computed(() => {
  const method = String(props.endpoint?.method || '').trim().toUpperCase()
  return method === 'POST' || method === 'PUT' || method === 'PATCH'
})

onBeforeUnmount(() => {
  ;(['body', 'headers', 'cookies', 'requestBodyMatcher'] as JsonEditorKey[]).forEach((key) => {
    disposeEditorBindings(key)
  })
})

defineExpose({
  triggerSave: submit,
})
</script>

<template>
  <section class="mock-editor glass-panel">
    
    <!-- LIST VIEW -->
    <div v-if="viewMode === 'list'" class="view-list">
      <header class="mock-head">
        <div>
          <span class="mock-kicker">{{ $t('api_mock.mock_cases_title') }}</span>
          <h3>{{ endpoint ? endpoint.path : $t('api_mock.mock_cases_title') }}</h3>
          <p v-if="isAutoMockRunning" class="auto-mock-inline-hint">
            {{ $t(autoMockStatusText || 'api_mock.ai_auto_mock_running') }}
          </p>
        </div>
        <div class="mock-head-actions">
          <button
            type="button"
            class="btn-primary mini shadow-sm auto-mock-btn"
            :disabled="!canManage || !endpoint || isAutoMockRunning"
            @click="emit('start-auto-mock')"
          >
            {{ isAutoMockRunning ? $t('api_mock.ai_auto_mock_running_short') : $t('api_mock.ai_auto_mock') }}
          </button>
          <button
            type="button"
            class="btn-primary mini shadow-sm"
            :disabled="!canManage || !endpoint || currentEndpointAutoMockLocked"
            @click="handleAddCase"
          >
            <Plus class="w-4 h-4" />
            {{ $t('api_mock.add_mock_case') }}
          </button>
        </div>
      </header>

      <div v-if="!endpoint" class="empty-box">{{ $t('api_mock.select_endpoint_hint') }}</div>
      <div v-else class="case-grid">
         <button
            v-for="item in cases"
            :key="item.id"
            type="button"
            class="case-card"
            @click="selectCaseLocal(item.id)"
         >
            <div class="case-topline">
              <strong>{{ item.name }}</strong>
              <span v-if="item.is_default" class="default-pill">{{ $t('api_mock.default_case') }}</span>
            </div>
            <p>{{ item.status_code }} · {{ item.mode }} · {{ item.enabled ? $t('api_mock.enabled') : $t('api_mock.disabled') }}</p>
         </button>
         <div v-if="cases.length === 0" class="empty-box large">{{ $t('api_mock.mock_case_empty') }}</div>
      </div>
    </div>

    <!-- DETAIL VIEW -->
    <div v-if="viewMode === 'detail'" class="view-detail">
      <header class="detail-header">
         <button type="button" class="back-link" @click="backToList">
            <ArrowLeft class="w-4 h-4" />
            <span>{{ $t('api_mock.back_to_list') }}</span>
         </button>
         <div class="detail-actions">
           <button type="button" class="btn-secondary mini" @click="browseEndpoint">
              <ExternalLink class="w-4 h-4" />
              {{ $t('api_mock.browse_endpoint') }}
           </button>
           <button type="button" class="btn-primary mini" :disabled="!canManage || savingCase" @click="submit">
             <Save class="w-4 h-4" />
             {{ savingCase ? $t('api_mock.saving') : $t('api_mock.save_mock_case') }}
           </button>
           <button v-if="currentCase" type="button" class="btn-secondary mini danger" :disabled="!canManage || deletingCase" @click="emit('delete-case', currentCase.id)">
             <Trash2 class="w-4 h-4" />
           </button>
         </div>
      </header>
      
      <div class="detail-name-row">
        <label class="meta-field">
          <span class="meta-label">{{ $t('api_mock.mock_case_name') }}</span>
          <input
            v-model="form.name"
            class="input-field meta-input"
            :placeholder="$t('api_mock.mock_case_name')"
            :disabled="!canManage"
          />
        </label>
        <label class="meta-field">
          <span class="meta-label">{{ $t('api_mock.mock_case_description') }}</span>
          <input
            v-model="form.description"
            class="input-field meta-input"
            :placeholder="$t('api_mock.mock_case_description')"
            :disabled="!canManage"
          />
        </label>
      </div>

      <div class="matcher-panel glass-panel">
        <div class="matcher-head">
          <strong class="pane-title">{{ $t('api_mock.request_matchers_title') }}</strong>
          <span class="matcher-hint">{{ $t('api_mock.request_matchers_hint') }}</span>
        </div>
        <div class="matcher-grid" :style="{ '--matcher-columns': String(matcherColumnCount) }">
          <div v-if="hasPathMatchers" class="matcher-item">
            <span class="matcher-label">{{ $t('api_mock.matcher_path_params') }}</span>
            <div class="matcher-kv-table">
              <div class="matcher-kv-head">
                <span>{{ $t('api_mock.matcher_col_key') }}</span>
                <span>{{ $t('api_mock.matcher_col_value') }}</span>
              </div>
              <div class="matcher-kv-list custom-scrollbar">
                <label v-for="name in pathParamNames" :key="`path-${name}`" class="matcher-kv-row">
                  <span class="matcher-key">{{ name }}</span>
                  <input
                    v-model="pathMatcherInputs[name]"
                    class="input-field matcher-input"
                    :placeholder="$t('api_mock.matcher_value_placeholder')"
                    :disabled="!canManage"
                  />
                </label>
              </div>
            </div>
          </div>
          <div v-if="hasQueryMatchers" class="matcher-item">
            <span class="matcher-label">{{ $t('api_mock.matcher_query_params') }}</span>
            <div class="matcher-kv-table">
              <div class="matcher-kv-head">
                <span>{{ $t('api_mock.matcher_col_key') }}</span>
                <span>{{ $t('api_mock.matcher_col_value') }}</span>
              </div>
              <div class="matcher-kv-list custom-scrollbar">
                <label v-for="name in queryParamNames" :key="`query-${name}`" class="matcher-kv-row">
                  <span class="matcher-key">{{ name }}</span>
                  <input
                    v-model="queryMatcherInputs[name]"
                    class="input-field matcher-input"
                    :placeholder="$t('api_mock.matcher_value_placeholder')"
                    :disabled="!canManage"
                  />
                </label>
              </div>
            </div>
          </div>
          <div v-if="showRequestBodyMatcher" class="matcher-item">
            <span class="matcher-label">{{ $t('api_mock.matcher_body_json') }}</span>
            <div class="matcher-monaco-wrapper">
              <VueMonacoEditor
                v-model:value="requestBodyMatcherText"
                language="json"
                theme="vs"
                width="100%"
                height="188px"
                :options="editorOptions"
                @mount="mountRequestBodyMatcherEditor"
              />
            </div>
          </div>
        </div>
      </div>

      <div class="response-layout">
         <div class="split-pane response-pane">
            <div class="pane-head">
               <strong class="pane-title">{{ $t('api_mock.response_data') }}</strong>
               <label class="toggle-item styled-toggle">
                 <input v-model="form.enableMockjs" type="checkbox" :disabled="!canManage">
                 <span>{{ $t('api_mock.enable_mockjs') }}</span>
               </label>
            </div>
            <div class="monaco-wrapper large">
               <VueMonacoEditor
                 v-model:value="form.bodyText"
                 language="json"
                 theme="vs"
                 width="100%"
                 height="420px"
                 :options="editorOptions"
                 @mount="mountBodyEditor"
               />
            </div>
            <p class="mockjs-hint" v-if="form.enableMockjs">
              Support Mock.js syntax (e.g. <code>"list|1-10": [{"id|+1": 1}]</code>). Generates dynamic fake data on every request.
            </p>
         </div>
      </div>

      <!-- ADVANCED SETTINGS COLLAPSIBLE -->
      <details class="advanced-settings glass-panel">
         <summary>{{ $t('api_mock.advanced_settings') }}</summary>
         <div class="details-content">
            <div class="detail-grid top-grid">
              <label class="field">
                <span>{{ $t('api_mock.status_code') }}</span>
                <input v-model.number="form.statusCode" type="number" min="100" max="599" class="input-field" :disabled="!canManage">
              </label>
              <label class="field">
                <span>{{ $t('api_mock.delay_ms') }}</span>
                <input v-model.number="form.delayMs" type="number" min="0" class="input-field" :disabled="!canManage">
              </label>
            </div>
            <div class="toggle-grid">
              <label class="toggle-item">
                <input v-model="form.enabled" type="checkbox" :disabled="!canManage">
                <span>{{ $t('api_mock.enabled') }}</span>
              </label>
              <label class="toggle-item">
                <input v-model="form.isDefault" type="checkbox" :disabled="!canManage">
                <span>{{ $t('api_mock.default_case') }}</span>
              </label>
            </div>
            <div class="detail-grid columns compact">
              <div class="field">
                <span>{{ $t('api_mock.headers_json') }}</span>
                <div class="monaco-wrapper compact">
                  <VueMonacoEditor v-model:value="form.headersText" language="json" theme="vs" width="100%" height="128px" :options="editorOptions" @mount="mountHeadersEditor" />
                </div>
              </div>
              <div class="field">
                <span>{{ $t('api_mock.cookies_json') }}</span>
                <div class="monaco-wrapper compact">
                  <VueMonacoEditor v-model:value="form.cookiesText" language="json" theme="vs" width="100%" height="128px" :options="editorOptions" @mount="mountCookiesEditor" />
                </div>
              </div>
            </div>
         </div>
      </details>
    </div>
  </section>
</template>

<style scoped>
.mock-editor {
  display: flex;
  flex-direction: column;
  padding: 1.25rem;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.4);
  backdrop-filter: blur(12px);
  min-height: 0;
}

/* LIST VIEW */
.view-list {
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
  min-height: 0;
}

.mock-head {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: flex-start;
}

.mock-head-actions {
  display: inline-flex;
  gap: 0.5rem;
  align-items: center;
}

.mock-head-actions .btn-primary,
.mock-head-actions .btn-secondary {
  height: 44px;
  min-height: 44px;
  padding-top: 0;
  padding-bottom: 0;
  box-sizing: border-box;
  line-height: 1;
}

.auto-mock-btn {
  background: linear-gradient(135deg, #fb923c, #f97316);
  box-shadow: 0 8px 18px rgba(249, 115, 22, 0.28);
  border: 1px solid rgba(251, 146, 60, 0.5);
}

.auto-mock-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #f97316, #ea580c);
  box-shadow: 0 10px 20px rgba(234, 88, 12, 0.32);
}

.auto-mock-btn:disabled {
  background: #cbd5e1;
  border-color: #cbd5e1;
  box-shadow: none;
}

.auto-mock-inline-hint {
  margin: 0.35rem 0 0;
  color: #0f766e;
  font-size: 0.76rem;
  font-weight: 600;
}

.mock-kicker {
  color: #0284c7;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.mock-head h3 {
  margin: 0.35rem 0 0;
  font-size: 1.25rem;
  color: #0f172a;
}

.case-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1rem;
}

.case-card {
  text-align: left;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  padding: 1.1rem;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
}

.case-card:hover {
  transform: translateY(-2px);
  border-color: #cbd5e1;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
}

.case-topline {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 0.5rem;
}

.case-topline strong {
  color: #0f172a;
  font-size: 1rem;
}

.case-card p {
  margin: 0;
  color: #64748b;
  font-size: 0.8rem;
}

.default-pill {
  display: inline-flex;
  padding: 0.2rem 0.5rem;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  font-size: 0.72rem;
  font-weight: 700;
}

.empty-box {
  min-height: 12rem;
  border-radius: 18px;
  border: 1px dashed #cbd5e1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #64748b;
}

.empty-box.large {
  grid-column: 1 / -1;
  min-height: 16rem;
}

/* DETAIL VIEW */
.view-detail {
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
  min-height: 0;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid #e2e8f0;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  background: transparent;
  border: none;
  color: #475569;
  font-weight: 600;
  font-size: 0.95rem;
  cursor: pointer;
  padding: 0.4rem 0.6rem;
  border-radius: 8px;
  transition: all 0.15s;
}

.back-link:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.detail-actions {
  display: flex;
  gap: 0.65rem;
  align-items: center;
}

.danger {
  color: #b91c1c;
  border-color: rgba(252, 165, 165, 0.92);
  background: rgba(254, 242, 242, 0.6);
}
.danger:hover {
  background: rgba(254, 226, 226, 0.9);
}

.detail-name-row {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(320px, 1.5fr);
  gap: 1rem;
}

@media (max-width: 1100px) {
  .detail-name-row {
    grid-template-columns: minmax(0, 1fr);
  }
}

.meta-field {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  padding: 0.75rem 0.85rem;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
}

.meta-label {
  color: #475569;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.input-field {
  width: 100%;
  padding: 0.62rem 0.75rem;
  border: 1px solid #d7e0eb;
  border-radius: 10px;
  background: #ffffff;
  font-size: 0.92rem;
  color: #1e293b;
  line-height: 1.2;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.input-field:focus {
  border-color: #38bdf8;
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.12);
}

.input-field:disabled {
  background: #f1f5f9;
  color: #64748b;
}

.meta-input {
  font-size: 0.95rem;
}

.matcher-panel {
  border-radius: 14px;
  border: 1px solid #d8e2ee;
  background: #f8fafc;
  padding: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.matcher-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.9rem 1rem;
  border-bottom: 1px solid #e2e8f0;
}

.matcher-hint {
  color: #64748b;
  font-size: 0.75rem;
}

.matcher-grid {
  display: grid;
  gap: 0.9rem;
  grid-template-columns: repeat(var(--matcher-columns, 1), minmax(0, 1fr));
  padding: 0.9rem 1rem 1rem;
}

.matcher-item {
  display: flex;
  flex-direction: column;
  gap: 0;
  border: 1px solid #d9e2ef;
  border-radius: 10px;
  background: #ffffff;
  overflow: hidden;
}

.matcher-label {
  color: #334155;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  padding: 0.55rem 0.7rem;
}

.matcher-kv-table {
  display: flex;
  flex-direction: column;
  min-height: 8.4rem;
}

.matcher-kv-head {
  display: grid;
  grid-template-columns: minmax(110px, 0.42fr) minmax(0, 1fr);
  align-items: center;
  padding: 0.42rem 0.7rem;
  background: #f8fafc;
  color: #64748b;
  font-size: 0.69rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  border-bottom: 1px solid #e2e8f0;
}

.matcher-kv-list {
  display: flex;
  flex-direction: column;
  max-height: 15rem;
  overflow: auto;
}

.matcher-kv-row {
  display: grid;
  grid-template-columns: minmax(110px, 0.42fr) minmax(0, 1fr);
  align-items: stretch;
  min-height: 2.1rem;
  border-bottom: 1px solid #edf2f7;
}

.matcher-kv-row:last-child {
  border-bottom: none;
}

.matcher-key {
  color: #334155;
  font-size: 0.79rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  padding: 0.45rem 0.7rem;
  line-height: 1.25;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  word-break: break-all;
}

.matcher-input {
  min-height: 100%;
  border: none !important;
  border-left: 1px solid #edf2f7 !important;
  border-radius: 0 !important;
  background: #ffffff !important;
  box-shadow: none !important;
  font-size: 0.84rem;
  padding: 0.42rem 0.62rem;
}

.matcher-input:focus {
  border-left-color: #bae6fd !important;
  box-shadow: inset 0 0 0 1px rgba(14, 165, 233, 0.35) !important;
}

.matcher-monaco-wrapper {
  min-height: 188px;
  border-top: 1px solid #edf2f7;
  background: #fff;
}

@media (max-width: 1200px) {
  .matcher-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.response-layout {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.split-pane {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.pane-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 2.2rem;
}

.pane-title {
  color: #1e293b;
  font-size: 1.05rem;
}

.toggle-item {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  color: #475569;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
}

.styled-toggle input {
  accent-color: #0284c7;
  width: 1rem;
  height: 1rem;
}

.monaco-wrapper {
  flex: 0 0 auto;
  min-height: 0;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
  box-shadow: inset 0 2px 4px rgba(15, 23, 42, 0.02);
}

.monaco-wrapper.large {
  min-height: 420px;
  height: 420px;
}

.mockjs-hint {
  font-size: 0.75rem;
  color: #64748b;
  margin: 0;
}
.mockjs-hint code {
  background: #f1f5f9;
  padding: 0.1rem 0.3rem;
  border-radius: 4px;
  color: #0ea5e9;
}

/* ADVANCED SETTINGS */
.advanced-settings {
  border-radius: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  overflow: hidden;
  margin-top: 1rem;
}

.advanced-settings summary {
  padding: 0.85rem 1.1rem;
  font-weight: 700;
  color: #475569;
  cursor: pointer;
  user-select: none;
  background: #f1f5f9;
  outline: none;
}

.advanced-settings summary:hover {
  background: #e2e8f0;
}

.details-content {
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.detail-grid {
  display: grid;
  gap: 1rem;
}

.top-grid {
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
}

.columns {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.monaco-wrapper.compact {
  min-height: 128px;
  height: 128px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.field span {
  color: #475569;
  font-size: 0.8rem;
  font-weight: 600;
}

.toggle-grid {
  display: flex;
  gap: 1.5rem;
}
</style>
