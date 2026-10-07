import { effectScope, nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useFeatureConfig } from '../useFeatureConfig'
import { featureConfigApi, type Capability, type FeatureConfig } from '@/services/featureConfigApi'

vi.mock('@/services/featureConfigApi', () => ({
  featureConfigApi: { test: vi.fn(), save: vi.fn() },
}))
const config = (): FeatureConfig => ({
  feature: 'speech', title: '语音输入', revision: 4, configured: true,
  fields: [
    { key: 'api_key', label: 'API Key', kind: 'secret', value: 'sk-0********abcd', has_value: true,
      source: 'database', options: [], minimum: 0, maximum: 4096, hint: '' },
    { key: 'region', label: '地域', kind: 'select', value: 'beijing', has_value: true,
      source: 'environment', options: ['beijing', 'singapore'], minimum: 0, maximum: 4096, hint: '' },
  ],
})
const status: Capability = { feature: 'speech', title: '语音输入', status: 'READY', mode: 'api',
  explanation: '已就绪', guidance: '', facts: {}, checked_at: '' }
const setup = () => {
  const scope = effectScope()
  const current = ref(config())
  const state = scope.run(() => useFeatureConfig(() => current.value))!
  return { scope, current, state }
}
beforeEach(() => { vi.resetAllMocks() })

describe('feature credential and draft contracts', () => {
  it('keeps the stored credential when the replacement input is erased', async () => {
    const { scope, state } = setup()
    vi.mocked(featureConfigApi.test).mockResolvedValue({ data: status } as never)
    state.updateSecret('api_key', 'replacement')
    state.updateSecret('api_key', '')
    await state.test()
    expect(featureConfigApi.test).toHaveBeenCalledWith('speech', { revision: 4, values: {} })
    scope.stop()
  })
  it('never posts masks, retains credentials when changing another field, and carries the revision', async () => {
    const { scope, state } = setup()
    expect(state.values.api_key).toBe('')
    state.values.region = 'singapore'
    vi.mocked(featureConfigApi.test).mockResolvedValue({ data: status } as never)
    await state.test()
    expect(featureConfigApi.test).toHaveBeenCalledWith('speech', { revision: 4, values: { region: 'singapore' } })
    scope.stop()
  })

  it('uses distinct patch operations for clear, inherit and replace', async () => {
    const { scope, state } = setup()
    vi.mocked(featureConfigApi.test).mockResolvedValue({ data: status } as never)
    state.secretActions.api_key = 'clear'
    await state.test()
    expect(featureConfigApi.test).toHaveBeenLastCalledWith('speech', { revision: 4, values: { api_key: '' } })
    state.secretActions.api_key = 'inherit'
    await state.test()
    expect(featureConfigApi.test).toHaveBeenLastCalledWith('speech', { revision: 4, values: { api_key: null } })
    state.secretActions.api_key = 'replace'
    expect(state.invalidSecret.value).toBe(true)
    state.values.api_key = 'new-private-value'
    await state.test()
    expect(featureConfigApi.test).toHaveBeenLastCalledWith('speech', { revision: 4, values: { api_key: 'new-private-value' } })
    scope.stop()
  })

  it('marks a delayed probe stale after draft changes', async () => {
    const { scope, state } = setup()
    let resolve!: (value: unknown) => void
    vi.mocked(featureConfigApi.test).mockImplementationOnce(() => new Promise(complete => { resolve = complete }) as never)
    const pending = state.test()
    state.values.region = 'singapore'
    resolve({ data: status })
    await pending
    expect(state.testStale.value).toBe(true)
    scope.stop()
  })

  it('clears entered plaintext after saving and emits the runtime refresh event', async () => {
    const { scope, state } = setup()
    const changed = vi.fn()
    window.addEventListener('traceforge-features-changed', changed)
    vi.mocked(featureConfigApi.save).mockResolvedValue({ data: { config: config(), applied: true, message: '' } } as never)
    state.secretActions.api_key = 'replace'
    state.values.api_key = 'new-private-value'
    await state.save()
    expect(state.values.api_key).toBe('')
    expect(changed).toHaveBeenCalledOnce()
    window.removeEventListener('traceforge-features-changed', changed)
    scope.stop()
  })

  it('restores environment settings without writing form values', async () => {
    const { scope, state } = setup()
    vi.mocked(featureConfigApi.save).mockResolvedValue({ data: { config: config(), applied: true, message: '' } } as never)
    state.values.region = 'singapore'
    await state.save(true)
    expect(featureConfigApi.save).toHaveBeenCalledWith('speech', { revision: 4, values: {}, reset: true })
    scope.stop()
  })

  it('loads the new revision and discards old drafts when another configuration is opened', async () => {
    const { scope, state, current } = setup()
    state.values.api_key = 'unsubmitted-private-value'
    current.value = { ...config(), revision: 8 }
    await nextTick()
    expect(state.values.api_key).toBe('')
    expect(state.secretActions.api_key).toBe('keep')
    scope.stop()
  })
})
