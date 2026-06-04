export type ApiMockProject = {
  id: string
  workspace_id: string
  task_id: string
  creator_id: string
  proxy_enabled: boolean
  proxy_base_url: string | null
  temp_workspace_path: string
  active_source_version_id: string | null
  created_at: string
  updated_at: string | null
}

export type ApiMockSourceVersion = {
  id: string
  project_id: string
  source_type: 'CODE_ANALYSIS' | 'SWAGGER_IMPORT'
  source_name: string | null
  summary_json: Record<string, unknown> | null
  is_active: boolean
  creator_id: string
  created_at: string
}

export type ApiMockEndpoint = {
  id: string
  project_id: string
  source_version_id: string
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
  row_version: number
  created_at: string
  updated_at: string | null
}

export type ApiMockEntity = {
  id: string
  project_id: string
  source_version_id: string
  endpoint_id: string | null
  name: string
  description: string | null
  schema_json: Record<string, unknown>
  row_version: number
  created_at: string
  updated_at: string | null
}

export type ApiMockMockCase = {
  id: string
  project_id: string
  endpoint_id: string
  name: string
  description: string | null
  is_default: boolean
  sort_order: number
  mode: 'STATIC' | 'MOCKJS' | 'PROXY'
  request_path_params_json: Record<string, unknown> | null
  request_query_json: Record<string, unknown> | null
  request_body_json: unknown
  static_body_json: Record<string, unknown> | null
  mockjs_template: string | null
  status_code: number
  headers_json: Record<string, unknown> | null
  cookies_json: Array<Record<string, unknown>> | null
  delay_ms: number
  enabled: boolean
  updated_by: string
  row_version: number
  created_at: string
  updated_at: string | null
}

export type ApiMockRule = ApiMockMockCase

export type ApiMockDocument = {
  project_id: string
  source_version_id: string
  source_type: 'CODE_ANALYSIS' | 'SWAGGER_IMPORT'
  source_name: string | null
  content: string
  created_at: string
}

export type ApiMockJob = {
  id: string
  project_id: string
  creator_id: string
  job_type: string
  status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED'
  progress: number
  message: string | null
  result_json: Record<string, unknown> | null
  created_at: string
  updated_at: string | null
  started_at: string | null
  finished_at: string | null
}

export type ApiMockPreviewResponse = {
  mode: 'STATIC' | 'MOCKJS' | 'PROXY'
  status_code: number
  headers: Record<string, unknown>
  cookies: Array<Record<string, unknown>>
  body: unknown
  latency_ms: number
  restc_command?: string | null
}
