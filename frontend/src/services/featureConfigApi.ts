import api from '@/utils/api'

export type FeatureId = 'speech' | 'search' | 'diagnosis' | 'oauth' | 'agent'
export type CapabilityStatus = 'READY' | 'DEGRADED' | 'NOT_CONFIGURED' | 'DISABLED'
export type ConfigValue = string | number | boolean
export interface FeatureField {
  key: string
  label: string
  kind: 'text' | 'secret' | 'boolean' | 'number' | 'select' | 'url' | 'https'
  value: ConfigValue
  has_value: boolean
  source: 'database' | 'environment'
  options: string[]
  minimum: number
  maximum: number
  hint: string
  visible_when?: Record<string, string[]>
  option_labels?: Record<string, string>
  group?: string
}
export interface FeatureConfig {
  feature: FeatureId
  title: string
  revision: number
  configured: boolean
  fields: FeatureField[]
  error?: string
  providers?: { id: string; label: string; transports: string[]; default_transport: string }[]
}
export interface Capability {
  feature: FeatureId
  title: string
  status: CapabilityStatus
  mode: string
  explanation: string
  guidance: string
  facts: Record<string, boolean | string | number>
  checked_at: string
}
export interface FeaturePatch {
  revision: number
  values: Record<string, ConfigValue | null>
  reset?: boolean
}
export const featureConfigApi = {
  configs: () => api.get<{ items: FeatureConfig[] }>('/system-configs/features'),
  capabilities: () => api.get<{ items: Capability[] }>('/system-configs/capabilities', { timeout: 20000 }),
  test: (feature: FeatureId, body: FeaturePatch) =>
    api.post<Capability>('/system-configs/features/' + feature + '/test', body, { timeout: 20000 }),
  save: (feature: FeatureId, body: FeaturePatch) =>
    api.put<{ config: FeatureConfig; applied: boolean; message: string }>('/system-configs/features/' + feature, body, { timeout: 30000 }),
}
