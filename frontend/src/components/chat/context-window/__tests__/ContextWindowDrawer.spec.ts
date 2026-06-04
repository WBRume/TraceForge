import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ContextWindowDrawer from '@/components/chat/context-window/ContextWindowDrawer.vue'
import type { ContextWindowResponse } from '@/types/contextWindow'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('@/components/AppSideDrawer.vue', () => ({
  default: {
    name: 'AppSideDrawer',
    props: ['show', 'title', 'level', 'resizable'],
    emits: ['close', 'update:level'],
    template: '<section v-if="show"><slot name="icon" /><slot name="actions" /><slot /></section>',
  },
}))

const contextData: ContextWindowResponse = {
  task_id: 'task-1',
  workspace_id: 'ws-1',
  snapshot: {
    id: 'snap-1',
    workspace_id: 'ws-1',
    task_id: 'task-1',
    ai_job_id: 'job-1',
    status: 'SUCCESS',
    total_cost_usd: 0.0123,
    duration_ms: 1500,
  },
  provider_tokens: {
    available: true,
    status: 'available',
    total_tokens: 120,
    input_tokens: 80,
    output_tokens: 20,
    cache_read_tokens: 10,
    cache_creation_tokens: 5,
    thinking_tokens: 3,
    tool_io_tokens: 2,
  },
  categories: [
    {
      category: 'TOOL_RESULT',
      segment_count: 1,
      attribution_units: 40,
      char_count: 40,
      byte_count: 40,
      percentage: 66.666,
    },
    {
      category: 'THINKING',
      segment_count: 1,
      attribution_units: 20,
      char_count: 20,
      byte_count: 20,
      percentage: 33.333,
    },
  ],
  segments: [
    {
      id: 'seg-1',
      snapshot_id: 'snap-1',
      category: 'TOOL_RESULT',
      attribution_units: 40,
      char_count: 40,
      byte_count: 40,
      source_kind: 'tool_result',
      source_ref_id: 'tool-1',
      tool_use_id: 'tool-1',
      content_hash: 'abc1234567890',
      title: 'Tool Result',
      preview: 'short preview only',
    },
  ],
  segments_total: 1,
  segments_page: 1,
  segments_page_size: 50,
  selected_category: 'TOOL_RESULT',
  compaction: {
    task_id: 'task-1',
    workspace_id: 'ws-1',
    status: 'detected',
    has_detected_events: true,
    empty_reason: null,
    parser_version: 'compaction-v1',
    generated_at: '2026-05-01T00:00:00Z',
    data_sources: [
      { source: 'execution_log', status: 'scanned', event_count: 1 },
    ],
    phases: [
      {
        phase_index: 1,
        started_at: '2026-05-01T00:00:00Z',
        ended_at: '2026-05-01T00:10:00Z',
        token_before_estimate: 120000,
        token_after_estimate: 32000,
        phase_new_tokens_estimate: 120000,
        trigger: { turn_index: 4, ai_job_id: 'job-1', chat_message_id: 'msg-1', log_id: 'log-1', label: 'turn 4' },
        compaction_event_id: 'compact-1',
        estimation_note: 'estimated',
      },
      {
        phase_index: 2,
        started_at: '2026-05-01T00:10:00Z',
        ended_at: '2026-05-01T00:20:00Z',
        token_before_estimate: 32000,
        token_after_estimate: 120,
        phase_new_tokens_estimate: 0,
        trigger: null,
        compaction_event_id: null,
      },
    ],
    events: [
      {
        id: 'compact-1',
        phase_before: 1,
        phase_after: 2,
        detected_at: '2026-05-01T00:10:00Z',
        source: 'execution_log',
        source_ref_id: 'log-1',
        source_label: 'Execution log',
        event_type: 'context_compaction',
        token_before_estimate: 120000,
        token_after_estimate: 32000,
        token_reduction_estimate: 88000,
        tokens_estimated: true,
        preview: '[compaction] context compaction detected; tokens 120000 -> 32000',
        trigger: { turn_index: 4, ai_job_id: 'job-1', chat_message_id: 'msg-1', log_id: 'log-1', label: 'turn 4' },
        locator: { log_id: 'log-1' },
        risks: [
          {
            kind: 'history',
            label: '可能被压缩的历史对话',
            level: 'medium',
            reason: 'history risk',
            affected_segments: 2,
            sample_refs: [],
            estimated: true,
          },
        ],
      },
    ],
  },
}

const mountDrawer = (props: Record<string, unknown> = {}) => mount(ContextWindowDrawer, {
  props: {
    show: true,
    level: 1,
    loading: false,
    error: null,
    data: contextData,
    selectedCategory: 'TOOL_RESULT',
    segmentsLoading: false,
    ...props,
  },
  global: {
    mocks: {
      $t: (key: string) => key,
    },
  },
})

describe('ContextWindowDrawer', () => {
  it('renders provider tokens, attribution categories, and segment references', () => {
    const wrapper = mountDrawer()

    expect(wrapper.text()).toContain('120')
    expect(wrapper.text()).toContain('TOOL_RESULT')
    expect(wrapper.text()).toContain('short preview only')
    expect(wrapper.text()).toContain('tool_result')
    expect(wrapper.text()).toContain('abc1234567')
  })

  it('emits category selection from the attribution list', async () => {
    const wrapper = mountDrawer({ selectedCategory: null, data: { ...contextData, segments: [], selected_category: null } })

    await wrapper.findAll('button.category-row')[0].trigger('click')

    expect(wrapper.emitted('selectCategory')?.[0]).toEqual(['TOOL_RESULT'])
  })

  it('shows unavailable when provider usage is missing', () => {
    const wrapper = mountDrawer({
      data: {
        ...contextData,
        provider_tokens: { available: false, status: 'unavailable' },
      },
    })

    expect(wrapper.text()).toContain('chat.context_window_unavailable')
  })

  it('renders empty and error states', () => {
    expect(mountDrawer({ data: null, loading: true }).text()).toContain('common.loading')
    expect(mountDrawer({ data: null, loading: false, error: 'boom' }).text()).toContain('boom')
    expect(mountDrawer({ data: { ...contextData, snapshot: null } }).text()).toContain('chat.context_window_empty')
  })

  it('renders compaction timeline and emits locate actions', async () => {
    const wrapper = mountDrawer()

    await wrapper.find('[data-test="compaction-tab"]').trigger('click')

    expect(wrapper.find('[data-test="compaction-view"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('120,000')
    expect(wrapper.text()).toContain('32,000')
    expect(wrapper.text()).toContain('88,000')
    expect(wrapper.text()).toContain('可能被压缩的历史对话')

    await wrapper.findAll('.locator-btn')[0].trigger('click')

    expect(wrapper.emitted('locate')?.[0]).toEqual([{
      source: 'execution_log',
      source_ref_id: 'log-1',
      ai_job_id: 'job-1',
      chat_message_id: 'msg-1',
      log_id: undefined,
    }])
  })

  it('shows a clear empty state when no compaction event is detected', async () => {
    const wrapper = mountDrawer({
      data: {
        ...contextData,
        compaction: {
          ...contextData.compaction!,
          status: 'not_detected',
          has_detected_events: false,
          events: [],
          empty_reason: 'NO_COMPACTION_EVENTS',
        },
      },
    })

    await wrapper.find('[data-test="compaction-tab"]').trigger('click')

    expect(wrapper.find('[data-test="compaction-empty"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('chat.compaction_empty_title')
  })
})
