import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, shallowRef } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { useAgentModels } from '@/composables/useAgentModels'

const api = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/utils/api', () => ({ default: api }))
const catalogue = (backend = 'dsh', model = 'private/a') => ({ data: {
  backend, current_model: model, options: [{ value: model, label: model }, { value: 'private/b', label: 'B' }],
} })
let wrapper: VueWrapper | undefined
afterEach(() => { wrapper?.unmount(); api.get.mockReset() })

function setup(initial = { workspaceId: 'w', taskId: 't1', resourceId: '' }) {
  const context = shallowRef(initial)
  let models!: ReturnType<typeof useAgentModels>
  wrapper = mount(defineComponent({ setup() {
    models = useAgentModels(() => context.value)
    return () => null
  } }))
  return { models, context }
}

describe('Agent model selection', () => {
  it('defaults to the active model and preserves a user choice during refresh', async () => {
    api.get.mockResolvedValue(catalogue())
    const { models } = setup()
    await flushPromises()
    expect(models.selection.value).toEqual({ backend: 'dsh', model: 'private/a' })
    models.select('private/b')
    await models.reload()
    expect(models.selected.value).toBe('private/b')
    models.observe('private/a')
    expect(models.selected.value).toBe('private/b')
    models.submitted({ backend: 'dsh', model: 'private/b' })
    models.observe('private/actual')
    expect(models.selected.value).toBe('private/actual')
  })

  it('clears immediately and discards a stale request when changing tasks or resources', async () => {
    let resolveOld!: (value: unknown) => void
    api.get.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    api.get.mockResolvedValueOnce(catalogue('opencode', 'provider/new'))
    const { models, context } = setup()
    context.value = { workspaceId: 'w', taskId: 't2', resourceId: 'local' }
    expect(models.selection.value).toBeUndefined()
    await flushPromises()
    resolveOld(catalogue())
    await flushPromises()
    expect(models.selection.value).toEqual({ backend: 'opencode', model: 'provider/new' })
    expect(api.get.mock.calls[1][1].params).toEqual({ task_id: 't2', resource_id: 'local' })
  })

  it('can retry after a failure without inventing a model', async () => {
    api.get.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(catalogue())
    const { models } = setup()
    await flushPromises()
    expect(models.error.value).toBeTruthy()
    expect(models.selection.value).toBeUndefined()
    await models.reload()
    expect(models.error.value).toBe('')
    expect(models.selected.value).toBe('private/a')
  })

  it('keeps a newer draft when an earlier send is accepted', async () => {
    api.get.mockResolvedValue(catalogue())
    const { models } = setup()
    await flushPromises()
    const submitted = models.selection.value
    models.select('private/b')
    models.submitted(submitted)
    models.observe('private/a')
    expect(models.selected.value).toBe('private/b')
  })

  it('does not let a slow catalogue overwrite a newer runtime model event', async () => {
    let resolve!: (value: unknown) => void
    api.get.mockImplementation(() => new Promise(done => { resolve = done }))
    const { models } = setup()
    models.observe('private/runtime')
    resolve(catalogue())
    await flushPromises()
    expect(models.selected.value).toBe('private/runtime')
    expect(models.options.value.some(item => item.value === 'private/runtime')).toBe(true)
  })
})
