import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import EvidenceDetailDialog from '../EvidenceDetailDialog.vue'

const sections = vi.hoisted(() => ({ loadEvidenceDetail: vi.fn(), loadFinalSummary: vi.fn() }))
vi.mock('@/composables/useTaskDetailSections', () => ({ useTaskDetailSections: () => sections }))

async function openDetail(metadata: Record<string, string>, remainingRisk?: string) {
  sections.loadEvidenceDetail.mockResolvedValue({
    id: 'evidence', title: 'Diagnostic log', source: { source_metadata: metadata },
  })
  sections.loadFinalSummary.mockResolvedValue({ remaining_risk: remainingRisk })
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

  it('uses the evidence failure metadata instead of a later summary', async () => {
    const wrapper = await openDetail({
      kind: 'closeout_attachment', failure_stage: 'REPRODUCTION', failure_reason: 'NOT_REPRODUCIBLE',
    }, 'Failure stage: COMPILE; reason: COMPILE_ERROR.')
    expect(wrapper.text()).toContain('问题复现与验证')
    expect(wrapper.text()).toContain('问题无法复现')
    expect(wrapper.text()).not.toContain('编译错误')
    wrapper.unmount()
  })

  it('keeps historical development evidence readable', async () => {
    const wrapper = await openDetail({ kind: 'closeout_commit', landing_method: 'HUMAN_ADJUSTED' },
      'Failure stage: COMPILE; reason: COMPILE_ERROR.')
    expect(wrapper.text()).toContain('落地方式')
    expect(wrapper.text()).toContain('人工调整后实现')
    expect(wrapper.text()).toContain('编译阶段')
    expect(wrapper.text()).toContain('编译错误')
    wrapper.unmount()
  })
})
