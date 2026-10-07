import { computed, reactive, ref, watch } from 'vue'
import { featureConfigApi, type Capability, type ConfigValue, type FeatureConfig, type FeaturePatch } from '@/services/featureConfigApi'

export function useFeatureConfig(config: () => FeatureConfig) {
  const values = reactive<Record<string, ConfigValue>>({})
  const secretActions = reactive<Record<string, 'keep' | 'replace' | 'clear' | 'inherit'>>({})
  const busy = ref<'test' | 'save' | 'reset' | ''>('')
  const testResult = ref<Capability | null>(null)
  const error = ref('')
  const testedSignature = ref('')
  watch(config, current => {
    Object.keys(values).forEach(key => delete values[key])
    Object.keys(secretActions).forEach(key => delete secretActions[key])
    current.fields.forEach(field => {
      values[field.key] = field.kind === 'secret' ? '' : field.value
      if (field.kind === 'secret') secretActions[field.key] = 'keep'
    })
    testResult.value = null
    testedSignature.value = ''
    error.value = ''
  }, { immediate: true })

  const patch = computed<FeaturePatch>(() => {
    const changed: FeaturePatch['values'] = {}
    config().fields.forEach(field => {
      if (field.kind !== 'secret') {
        if (values[field.key] !== field.value) changed[field.key] = values[field.key]!
        return
      }
      const action = secretActions[field.key]
      if (action === 'replace') changed[field.key] = values[field.key] || ''
      else if (action === 'clear') changed[field.key] = ''
      else if (action === 'inherit') changed[field.key] = null
    })
    return { revision: config().revision, values: changed }
  })
  const signature = computed(() => JSON.stringify(patch.value))
  const testStale = computed(() => !!testResult.value && testedSignature.value !== signature.value)
  const invalidSecret = computed(() => Object.keys(secretActions).some(key =>
    secretActions[key] === 'replace' && !String(values[key] || '').trim()))
  const updateSecret = (key: string, value: string) => {
    values[key] = value
    secretActions[key] = value ? 'replace' : 'keep'
  }
  const setSecretAction = (key: string, action: 'keep' | 'clear' | 'inherit') => {
    values[key] = ''
    secretActions[key] = action
  }
  const test = async () => {
    if (busy.value || invalidSecret.value) return
    busy.value = 'test'
    error.value = ''
    const body = patch.value
    const captured = signature.value
    try {
      testResult.value = (await featureConfigApi.test(config().feature, body)).data
      testedSignature.value = captured
    } finally { busy.value = '' }
  }
  const save = async (reset = false) => {
    if (busy.value || (!reset && invalidSecret.value)) return null
    busy.value = reset ? 'reset' : 'save'
    error.value = ''
    try {
      const body = reset ? { revision: config().revision, values: {}, reset: true } : patch.value
      const response = (await featureConfigApi.save(config().feature, body)).data
      // Never retain entered plaintext after a successful save.
      config().fields.filter(field => field.kind === 'secret').forEach(field => setSecretAction(field.key, 'keep'))
      window.dispatchEvent(new Event('traceforge-features-changed'))
      return response
    } finally { busy.value = '' }
  }
  return { values, secretActions, busy, testResult, testStale, invalidSecret, error, updateSecret, setSecretAction, test, save }
}
