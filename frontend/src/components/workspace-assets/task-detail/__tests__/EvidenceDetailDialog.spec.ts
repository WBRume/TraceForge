import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import EvidenceDetailDialog from '../EvidenceDetailDialog.vue'

const sections = vi.hoisted(() => ({ loadEvidenceDetail: vi.fn() }))
vi.mock('@/composables/useTaskDetailSections', () => ({ useTaskDetailSections: () => sections }))

async function openDetail(metadata: Record<string, string>, sourceUri?: string) {
  sections.loadEvidenceDetail.mockResolvedValue({
    id: 'evidence', title: 'Diagnostic log', source: { source_metadata: metadata, source_uri: sourceUri },
    attachments: [],
  })
  const wrapper = mount(EvidenceDetailDialog, {
    props: { visible: false, evidenceId: 'evidence', workspaceId: 'ws', taskId: 'task' },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })],
      stubs: { 'el-dialog': { template: '<section><slot /></section>' }, 'el-skeleton': true, 'el-button': true },
    },
  })
  await wrapper.setProps({ visible: true })
  await flushPromises()
  return wrapper
}

describe('closeout evidence labels', () => {
  it('shows the diagnosis method for saved completion evidence', async () => {
    const wrapper = await openDetail({ kind: 'closeout_attachment', landing_method: 'AI_DIAGNOSED' })
    expect(wrapper.text()).toContain('定位方式')
    expect(wrapper.text()).toContain('依据 AI 分析定位根因')
    expect(wrapper.text()).not.toContain('落地方式')
    wrapper.unmount()
  })

  it('shows the failure stage and reason saved on the evidence', async () => {
    const wrapper = await openDetail({
      kind: 'closeout_attachment', failure_stage: 'REPRODUCTION', failure_reason: 'NOT_REPRODUCIBLE',
    })
    expect(wrapper.text()).toContain('问题复现与验证')
    expect(wrapper.text()).toContain('问题无法复现')
    wrapper.unmount()
  })

  it('renders a PR link for reference evidence', async () => {
    const url = 'https://example.com/pull/42'
    const wrapper = await openDetail({ kind: 'closeout_pr', landing_method: 'HUMAN_ADJUSTED' }, url)
    expect(wrapper.text()).toContain('落地方式')
    expect(wrapper.text()).toContain('人工调整后实现')
    expect(wrapper.get('a').attributes('href')).toBe(url)
    wrapper.unmount()
  })

  it('does not use a source URL as an attachment when there is no associated file', async () => {
    const wrapper = await openDetail({ kind: 'closeout_attachment' }, '/api/upload/files/old.log')
    expect(wrapper.find('a').exists()).toBe(false)
    wrapper.unmount()
  })
})
