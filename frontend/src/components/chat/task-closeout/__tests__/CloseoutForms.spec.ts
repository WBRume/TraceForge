import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { shallowRef } from 'vue'
import CompleteCloseoutForm from '../CompleteCloseoutForm.vue'
import FailCloseoutForm from '../FailCloseoutForm.vue'
import TaskCloseoutPanel from '../TaskCloseoutPanel.vue'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'

const calls = vi.hoisted(() => ({ completeTask: vi.fn(), failTask: vi.fn() }))
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string, params?: { id?: string }) => params?.id ? `${key} ${params.id}` : key }),
}))
vi.mock('@/composables/useTaskCloseout', () => ({
  useTaskCloseout: () => ({ saving: shallowRef(false), error: shallowRef(null), ...calls }),
}))

const global = { mocks:{ $t:(key:string) => key } }
beforeEach(() => vi.clearAllMocks())

function collaborationHost(driverId?: string) {
  const state = shallowRef(driverId ? {
    driver_connected: true, driver_user_id: driverId, lease_epoch: 7,
    driver_profile: { display_name: 'Avery', avatar_url: '/avatars/avery.png', avatar_svg: null },
  } : null)
  return { state, phase: shallowRef('READY'), establishing: shallowRef(false), refresh: vi.fn() }
}
describe('closeout requirement and optional evidence', () => {
  it('selects a requirement in diagnosis completion without adding it to development closeout', async () => {
    const selectedRequirement = { id:'leaf', title:'Diagnosed requirement', status:'READY' }
    const wrapper = mount(CompleteCloseoutForm, { props:{ taskType:'DIAGNOSIS', selectedRequirement }, global })
    await wrapper.find('.closeout-requirement-entry').trigger('click')
    expect(wrapper.emitted('toggle-requirement-picker')).toHaveLength(1)
    await wrapper.find('textarea').setValue('Root cause confirmed')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({ requirement_id:'leaf', completion_summary:'Root cause confirmed' })
    await wrapper.setProps({ taskType:'DEVELOPMENT' })
    expect(wrapper.find('.closeout-requirement-entry').exists()).toBe(false)
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[1]?.[0]).toMatchObject({ requirement_id:undefined })
    wrapper.unmount()
  })
  it('submits failure without attachments while requiring a failure summary', async () => {
    const wrapper = mount(FailCloseoutForm, { global })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')).toBeUndefined()
    await wrapper.find('textarea').setValue('Environment could not reproduce the issue')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]).toEqual([expect.objectContaining({ failure_summary:'Environment could not reproduce the issue' }), []])
    expect(wrapper.findAll('label.required').some((label) => label.text().includes('failure_evidence'))).toBe(false)
    wrapper.unmount()
  })

  it('uses diagnosis methods and resets the selected method when task type changes', async () => {
    const wrapper = mount(CompleteCloseoutForm, { props: { taskType: 'DIAGNOSIS' }, global })
    expect(wrapper.text()).toContain('chat.closeout.diagnosis.landing_method')
    expect(wrapper.find('textarea').attributes('placeholder')).toContain('diagnosis.completion_summary_placeholder')
    await wrapper.find('.select-trigger').trigger('click')
    const options = wrapper.findAll('.option-item')
    expect(options.map(option => option.text())).toEqual([
      'chat.closeout.diagnosis.landing.ai_diagnosed',
      'chat.closeout.diagnosis.landing.human_assisted_diagnosis',
      'chat.closeout.diagnosis.landing.human_diagnosed',
      'chat.closeout.diagnosis.landing.ai_clue_only',
    ])
    await options[0]!.trigger('click')
    await wrapper.find('textarea').setValue('Root cause confirmed with logs')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({ landing_method: 'AI_DIAGNOSED' })
    await wrapper.setProps({ taskType: 'DEVELOPMENT' })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[1]?.[0]).toMatchObject({ landing_method: 'HUMAN_ADJUSTED' })
    expect(wrapper.text()).not.toContain('chat.closeout.diagnosis.')
    wrapper.unmount()
  })

  it('submits investigation stages and blockers without leaking development categories', async () => {
    const wrapper = mount(FailCloseoutForm, { props: { taskType: 'DIAGNOSIS' }, global })
    const selects = wrapper.findAll('.base-select')
    await selects[0]!.find('.select-trigger').trigger('click')
    expect(selects[0]!.text()).not.toContain('failure_stage_options.coding')
    const reproduction = selects[0]!.findAll('.option-item').find(option => option.text().endsWith('.reproduction'))!
    await reproduction.trigger('click')
    await selects[1]!.find('.select-trigger').trigger('click')
    expect(selects[1]!.text()).not.toContain('failure_reason_options.compile_error')
    const reason = selects[1]!.findAll('.option-item').find(option => option.text().endsWith('.not_reproducible'))!
    await reason.trigger('click')
    await wrapper.find('textarea').setValue('Cannot reproduce with available logs')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]).toEqual([{
      failure_stage: 'REPRODUCTION', failure_reason: 'NOT_REPRODUCIBLE', failure_summary: 'Cannot reproduce with available logs',
    }, []])
    await wrapper.setProps({ taskType: 'DEVELOPMENT' })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[1]?.[0]).toMatchObject({ failure_stage: 'CODING', failure_reason: 'OTHER' })
    wrapper.unmount()
  })

  it('passes the diagnosis task type to both panel forms', async () => {
    const wrapper = shallowMount(TaskCloseoutPanel, {
      props: { show: true, mode: 'fail', workspaceId: 'ws', taskId: 'task', taskType: 'DIAGNOSIS' },
      global: { ...global, stubs: { Teleport: true } },
    })
    expect(wrapper.findComponent(FailCloseoutForm).props('taskType')).toBe('DIAGNOSIS')
    await wrapper.setProps({ mode: 'complete' })
    expect(wrapper.findComponent(CompleteCloseoutForm).props('taskType')).toBe('DIAGNOSIS')
    wrapper.unmount()
  })

  it.each([
    { mode: 'complete', action: 'completeTask', status: 'COMPLETED', fields: {
      completion_summary: 'Result recorded', landing_method: 'HUMAN_ADJUSTED',
      requirement_id: undefined, commit_id: null, pr_url: null, local_ref: null,
    } },
    { mode: 'fail', action: 'failTask', status: 'FAILED', fields: {
      failure_summary: 'Result recorded', failure_stage: 'CODING', failure_reason: 'OTHER',
    } },
  ] as const)('submits $mode without a code version confirmation', async ({ mode, action, status, fields }) => {
    const result = { status }
    calls[action].mockResolvedValueOnce(result)
    const wrapper = mount(TaskCloseoutPanel, {
      props: { show: true, mode, workspaceId: 'ws', taskId: 'task' },
      global: { ...global, stubs: { Teleport: true } },
    })

    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('collaboration.blocked')
    await wrapper.get('textarea').setValue('Result recorded')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(calls[action].mock.calls).toEqual([['ws', 'task', fields, []]])
    expect(wrapper.emitted('success')?.[0]?.[0]).toEqual(result)
    wrapper.unmount()
  })

  it.each(['complete', 'fail'] as const)('blocks %s during agent work or while a host is connecting', async mode => {
    const collaboration = collaborationHost()
    const wrapper = mount(TaskCloseoutPanel, {
      props: {
        show: true, mode, workspaceId: 'ws', taskId: 'task', agentActive: true,
        collaboration: collaboration as unknown as LocalCollaboration,
      },
      global: { ...global, stubs: { Teleport: true } },
    })
    expect(wrapper.text()).toContain('chat.closeout.availability.agent_active')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    collaboration.establishing.value = true
    await wrapper.setProps({ agentActive: false })
    expect(wrapper.text()).toContain('chat.closeout.availability.connecting')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    await wrapper.get('form').trigger('submit')
    expect(calls.completeTask).not.toHaveBeenCalled()
    expect(calls.failTask).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows the other host identity and enables submission after disconnect', async () => {
    const collaboration = collaborationHost('another-user')
    const wrapper = mount(TaskCloseoutPanel, {
      props: {
        show: true, mode: 'fail', workspaceId: 'ws', taskId: 'task', userId: 'me',
        collaboration: collaboration as unknown as LocalCollaboration,
      },
      global: { ...global, stubs: { Teleport: true } },
    })
    expect(wrapper.text()).toContain('chat.closeout.availability.other_host')
    expect(wrapper.text()).toContain('another-user')
    expect(wrapper.get('img[alt="Avery"]').attributes('src')).toBe('/avatars/avery.png')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    collaboration.state.value = null
    await flushPromises()
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('requests consent for the current own host lease and preserves the form on cancel', async () => {
    const collaboration = collaborationHost('me')
    calls.failTask.mockResolvedValueOnce({ status: 'FAILED' })
    const wrapper = mount(TaskCloseoutPanel, {
      props: {
        show: true, mode: 'fail', workspaceId: 'ws', taskId: 'task', userId: 'me',
        collaboration: collaboration as unknown as LocalCollaboration,
      },
      global,
    })
    const textarea = document.body.querySelector<HTMLTextAreaElement>('.closeout-form textarea')!
    const submit = () => textarea.form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    textarea.value = 'Delivery failed'
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
    submit()
    await flushPromises()
    expect(document.body.textContent).toContain('chat.closeout.availability.disconnect_title')
    expect(calls.failTask).not.toHaveBeenCalled()
    document.body.querySelector<HTMLButtonElement>('[aria-labelledby] .btn-secondary')!.click()
    await flushPromises()
    expect(document.body.querySelector<HTMLTextAreaElement>('.closeout-form textarea')?.value).toBe('Delivery failed')
    submit()
    await flushPromises()
    collaboration.state.value = { ...collaboration.state.value! }
    await flushPromises()
    document.body.querySelector<HTMLButtonElement>('[aria-labelledby] .confirm-btn')!.click()
    await flushPromises()
    expect(calls.failTask.mock.calls).toEqual([['ws', 'task', {
      failure_summary: 'Delivery failed', failure_stage: 'CODING', failure_reason: 'OTHER',
      disconnect_collaboration_lease_epoch: 7,
    }, []]])
    wrapper.unmount()
  })
})
