import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import CasePromotionReviewView from '../CasePromotionReviewView.vue'
import CasePromotionReview from '@/components/case-center/CasePromotionReview.vue'
import api from '@/utils/api'

const pushMock = vi.fn()
const replaceMock = vi.fn()

vi.mock('vue-router', () => ({
  useRoute: () => ({
    params: { wsId: 'ws-test', jobId: 'job-123' },
    path: '/workspaces/ws-test/cases/promotions/job-123',
    name: 'workspaceCasePromotionReview',
  }),
  useRouter: () => ({
    push: pushMock,
    replace: replaceMock,
  }),
}))

vi.mock('@/utils/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    success: vi.fn(),
    info: vi.fn(),
    error: vi.fn(),
  },
  ElMessageBox: {
    confirm: vi.fn().mockResolvedValue(true),
  },
}))

describe('CasePromotionReviewView.vue', () => {
  const sampleDraft = {
    grouping_reason: '由于故障类型差异，建议按微服务拆分为两套规程',
    playbooks: [
      {
        title: '订单服务超时排查规程',
        source_case_ids: ['case-1', 'case-2'],
        summary: '通过链路追踪核查上游下游耗时',
        symptoms: ['下单接口超时 504', '网关报警响应延迟'],
        steps: ['1. 检查网关日志', '2. 核实数据库连接池'],
      },
      {
        title: '库存锁定异常定位规程',
        source_case_ids: ['case-3'],
        summary: '核查分布式锁竞争与Redis状态',
        symptoms: ['库存扣减失败 409'],
        steps: ['1. 检查 Redis 慢日志', '2. 核实锁超时配置'],
      },
    ],
  }

  const pendingJob = {
    job_id: 'job-123',
    workspace_id: 'ws-test',
    status: 'SUCCESS',
    progress: 100,
    cases: [
      { id: 'case-1', title: '订单超时故障 A' },
      { id: 'case-2', title: '订单超时故障 B' },
      { id: 'case-3', title: '库存扣减异常 C' },
    ],
    result: {
      review_state: 'PENDING',
      draft_revision: 'rev-001',
      draft: sampleDraft,
    },
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue({
      data: { items: [pendingJob] },
    })
  })

  it('loads job draft and renders master-detail layout (not waterfall)', async () => {
    const wrapper = mount(CasePromotionReviewView)
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith('/workspaces/ws-test/cases/playbook-promotions', {
      params: { job_id: 'job-123' },
    })

    const review = wrapper.findComponent(CasePromotionReview)
    expect(review.exists()).toBe(true)
    expect(wrapper.text()).toContain('案例晋升诊断规程确认')
    expect(wrapper.text()).toContain('2 套规程 · 待入库')
    expect(wrapper.text()).toContain('AI 分组策略依据')

    // 检查左侧 Master 导航列表
    const navItems = wrapper.findAll('.playbook-nav-item')
    expect(navItems).toHaveLength(2)
    expect(navItems[0].text()).toContain('规程 1')
    expect(navItems[0].text()).toContain('订单服务超时排查规程')
    expect(navItems[1].text()).toContain('规程 2')
    expect(navItems[1].text()).toContain('库存锁定异常定位规程')

    // 默认展示规程 1 的详情，非全部瀑布流平铺
    expect(wrapper.find('.detail-badge').text()).toBe('规程 1')
    const titleInput = wrapper.find('input.form-input')
    expect((titleInput.element as HTMLInputElement).value).toBe('订单服务超时排查规程')

    // 点击左侧第二个规程卡片进行切换
    await navItems[1].trigger('click')
    expect(wrapper.find('.detail-badge').text()).toBe('规程 2')
    expect((wrapper.find('input.form-input').element as HTMLInputElement).value).toBe('库存锁定异常定位规程')

    wrapper.unmount()
  })

  it('submits confirmation and navigates back after successful confirm', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        ...pendingJob,
        result: {
          ...pendingJob.result,
          review_state: 'CONFIRMED',
          spec_ids: ['spec-1', 'spec-2'],
        },
      },
    })

    const wrapper = mount(CasePromotionReviewView)
    await flushPromises()

    const confirmBtn = wrapper.findAll('button').find((b) => b.text().includes('确认入库'))!
    expect(confirmBtn.exists()).toBe(true)
    await confirmBtn.trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith(
      '/workspaces/ws-test/cases/playbook-promotions/job-123/confirm',
      expect.objectContaining({
        draft_revision: 'rev-001',
        draft: expect.objectContaining({
          playbooks: expect.arrayContaining([
            expect.objectContaining({ title: '订单服务超时排查规程' }),
          ]),
        }),
      }),
    )

    wrapper.unmount()
  })

  it('discards draft after modal confirmation', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        ...pendingJob,
        result: {
          ...pendingJob.result,
          review_state: 'DISCARDED',
        },
      },
    })

    const wrapper = mount(CasePromotionReviewView, {
      global: {
        stubs: { ConfirmActionModal: true },
      },
    })
    await flushPromises()

    const discardBtn = wrapper.findAll('button').find((b) => b.text().includes('放弃草案'))!
    await discardBtn.trigger('click')
    await flushPromises()

    const modals = wrapper.findAllComponents({ name: 'ConfirmActionModal' })
    expect(modals[0].props('show')).toBe(true)
    expect(modals[0].props('title')).toBe('放弃诊断规程草案')
    expect(modals[0].props('tone')).toBe('danger')

    modals[0].vm.$emit('confirm')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith(
      '/workspaces/ws-test/cases/playbook-promotions/job-123/discard',
      { draft_revision: 'rev-001' },
    )

    wrapper.unmount()
  })

  it('triggers merge regeneration when requested via ConfirmActionModal', async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        job_id: 'job-merged-456',
        workspace_id: 'ws-test',
        status: 'RUNNING',
        progress: 10,
      },
    })

    const wrapper = mount(CasePromotionReviewView, {
      global: {
        stubs: { ConfirmActionModal: true },
      },
    })
    await flushPromises()

    const mergeBtn = wrapper.findAll('button').find((b) => b.text().includes('全部合并，重新提炼'))!
    expect(mergeBtn.exists()).toBe(true)
    await mergeBtn.trigger('click')
    await flushPromises()

    const modals = wrapper.findAllComponents({ name: 'ConfirmActionModal' })
    expect(modals[1].props('show')).toBe(true)
    expect(modals[1].props('title')).toBe('全部合并并重新提炼')
    expect(modals[1].props('tone')).toBe('primary')

    modals[1].vm.$emit('confirm')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith(
      '/workspaces/ws-test/cases/playbook-promotions/job-123/regenerate',
      expect.objectContaining({
        draft_revision: 'rev-001',
        idempotency_key: expect.any(String),
      }),
    )

    expect(replaceMock).toHaveBeenCalledWith(
      expect.objectContaining({
        params: { wsId: 'ws-test', jobId: 'job-merged-456' },
      }),
    )

    wrapper.unmount()
  })

  it('renders active progress card when job is running', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        items: [
          {
            job_id: 'job-123',
            workspace_id: 'ws-test',
            status: 'RUNNING',
            progress: 45,
            cases: [{ id: 'case-1', title: '故障案例' }],
          },
        ],
      },
    })

    const wrapper = mount(CasePromotionReviewView)
    await flushPromises()

    expect(wrapper.text()).toContain('AI 正在提炼与聚类诊断规程')
    expect(wrapper.text()).toContain('45%')

    wrapper.unmount()
  })

  it('navigates back when clicking back button', async () => {
    const wrapper = mount(CasePromotionReviewView)
    await flushPromises()

    const backBtn = wrapper.find('.back-link-btn')
    await backBtn.trigger('click')

    expect(pushMock).toHaveBeenCalledWith({
      name: 'workspaceCases',
      params: { wsId: 'ws-test' },
    })

    wrapper.unmount()
  })
})
