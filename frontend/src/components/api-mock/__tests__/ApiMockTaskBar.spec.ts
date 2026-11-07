import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'
import ApiMockTaskBar from '../ApiMockTaskBar.vue'

describe('API Mock status and cancellation', () => {
  const create = (canManage = true) => mount(ApiMockTaskBar, {
    props: { selectedTaskName: '订单', currentSourceLabel: 'OpenAPI', canView: true, canManage, cancelBusy: false,
      collabConnected: true, onlineUsers: [], activeJob: { id: 'job', job_type: 'AUTO_GENERATE_MOCK_CASES',
        status: 'RUNNING', progress: 30, message: '正在生成 Mock 场景', result_json: {} } },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh', missingWarn: false, fallbackWarn: false, messages: { zh: {} } })],
      stubs: { CollabPresenceBar: true } },
  })

  it('shows one current status, keeps cancellation at the top, and removes its control on completion', async () => {
    const wrapper = create()
    expect(wrapper.findAll('[role="status"]')).toHaveLength(1)
    expect(wrapper.get('[role="status"]').text()).toContain('正在生成 Mock 场景')
    await wrapper.get('.job-cancel').trigger('click')
    expect(wrapper.emitted('cancel-job')).toHaveLength(1)
    await wrapper.setProps({ activeJob: { ...wrapper.props('activeJob')!, message: '正在校验业务产物', progress: 70 } })
    expect(wrapper.text()).not.toContain('正在生成 Mock 场景')
    expect(wrapper.text()).toContain('正在校验业务产物')
    await wrapper.setProps({ activeJob: { ...wrapper.props('activeJob')!, status: 'SUCCESS', progress: 100, message: '新增 3 个用例' } })
    expect(wrapper.text()).not.toContain('正在校验业务产物')
    expect(wrapper.get('[role="status"]').text()).toContain('新增 3 个用例')
    expect(wrapper.find('.job-cancel').exists()).toBe(false)
  })

  it('disables repeated cancellation while the worker stops', async () => {
    const wrapper = create()
    await wrapper.setProps({ activeJob: { ...wrapper.props('activeJob')!, result_json: { cancel_requested: true } } })
    expect(wrapper.get('.job-cancel').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('api_mock.cancel_requested')
  })

  it('does not offer cancellation to a viewer', () => {
    expect(create(false).find('.job-cancel').exists()).toBe(false)
  })
})
