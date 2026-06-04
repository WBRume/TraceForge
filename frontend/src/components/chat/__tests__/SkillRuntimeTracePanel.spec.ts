import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SkillRuntimeTracePanel from '@/components/chat/SkillRuntimeTracePanel.vue'
import type { SkillRuntimeEvent } from '@/types/runtimeSkillTrace'

const event = (overrides: Partial<SkillRuntimeEvent>): SkillRuntimeEvent => ({
  id: 'event-1',
  workspace_id: 'ws-1',
  task_id: 'task-1',
  skill_id: 'skill-1',
  ai_job_id: null,
  tool_use_id: 'tool-1',
  event_type: 'FILE_READ',
  evidence_level: 'EXACT_PATH',
  materialized_dir: 'checklist-ender',
  matched_path: null,
  relative_path: 'SKILL.md',
  tool_name: 'Read',
  tool_input_json: null,
  tool_result_preview: null,
  status: 'PENDING',
  confidence: 1,
  created_at: '2026-04-29T10:00:00Z',
  ...overrides,
})

const mountPanel = (events: SkillRuntimeEvent[]) => mount(SkillRuntimeTracePanel, {
  props: {
    skills: [
      { skill_id: 'skill-1', name: 'checklist-ender', materialized_dir: 'checklist-ender' },
      { skill_id: 'skill-2', name: 'budget-note', materialized_dir: 'simple-budget-note' },
    ],
    selectedSkillId: 'skill-1',
    events,
    loading: false,
  },
})

describe('SkillRuntimeTracePanel', () => {
  it('renders task-level events in input order instead of skill summary groups', () => {
    const wrapper = mountPanel([
      event({
        id: 'event-budget',
        skill_id: 'skill-2',
        materialized_dir: 'simple-budget-note',
        event_type: 'FILE_SEARCH',
        tool_name: 'Grep',
        relative_path: 'templates/',
        evidence_level: 'EXACT_PATH',
        status: 'PENDING',
        created_at: '2026-04-29T10:01:00Z',
      }),
      event({
        id: 'event-checklist',
        skill_id: 'skill-1',
        materialized_dir: 'checklist-ender',
        event_type: 'SCRIPT_EXEC',
        tool_name: 'Bash',
        relative_path: 'tools/run.py',
        evidence_level: 'COMMAND_PATH',
        status: 'RESULT_RETURNED',
        created_at: '2026-04-29T10:02:00Z',
      }),
    ])

    const rows = wrapper.findAll('.trace-event')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('budget-note')
    expect(rows[0].text()).toContain('FILE_SEARCH')
    expect(rows[0].text()).toContain('Grep')
    expect(rows[0].text()).toContain('templates/')
    expect(rows[1].text()).toContain('checklist-ender')
    expect(rows[1].text()).toContain('SCRIPT_EXEC')
    expect(rows[1].text()).toContain('Bash')
    expect(rows[1].text()).toContain('tools/run.py')
    expect(wrapper.text()).not.toContain('已使用')
    expect(wrapper.text()).not.toContain('未观察到')
  })

  it('shows evidence metadata, result preview, and unattributed fallback', () => {
    const wrapper = mountPanel([
      event({
        id: 'event-unattributed',
        skill_id: null,
        materialized_dir: null,
        event_type: 'TOOL_RESULT',
        tool_name: null,
        relative_path: null,
        evidence_level: 'RESULT_LINKED',
        status: 'RESULT_RETURNED',
        tool_result_preview: 'done',
      }),
    ])

    expect(wrapper.text()).toContain('未归因')
    expect(wrapper.text()).toContain('TOOL_RESULT')
    expect(wrapper.text()).toContain('RESULT_LINKED')
    expect(wrapper.text()).toContain('RESULT_RETURNED')
    expect(wrapper.find('details').exists()).toBe(true)
    expect(wrapper.text()).toContain('done')
  })

  it('renders the task-level empty state', () => {
    const wrapper = mountPanel([])

    expect(wrapper.text()).toContain('暂无可观察到的工具访问证据。')
  })
})
