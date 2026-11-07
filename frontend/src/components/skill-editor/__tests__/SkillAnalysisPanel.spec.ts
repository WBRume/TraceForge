import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SkillAnalysisPanel from '@/components/skill-editor/SkillAnalysisPanel.vue'
import type { SkillEditorViewModel } from '@/composables/useSkillEditorViewModel'

describe('skill review report', () => {
  it('renders persisted findings without a completion banner or execution timeline', () => {
    const wrapper = mount(SkillAnalysisPanel, { props: { vm: {
      latestAnalysis: { status: 'SUCCESS', progress: 100, risk_level: 'HIGH',
        file_stats: { total_files: 2, domain_milestones: [{ run_id: 'run', sequence: 1, timestamp: 1,
          call_id: '', tool: 'submit_skill_review', stage: 'started', message: '正在审查技能包', issues: [] }] },
        key_files: [{ path: 'scripts/check.py' }], review_suggestions: ['改用参数数组，避免 shell 注入'],
      },
      analysisRunning: false, analysisLoading: false, canManage: true, runAnalysis: vi.fn(),
    } as unknown as SkillEditorViewModel }, global: { stubs: { SkillAnalysisRiskList: true } } })
    expect(wrapper.text()).toContain('scripts/check.py')
    expect(wrapper.text()).toContain('改用参数数组，避免 shell 注入')
    expect(wrapper.text()).not.toContain('正在审查技能包')
    expect(wrapper.text()).not.toContain('已完成')
    expect(wrapper.text()).not.toContain('100%')
    wrapper.unmount()
  })
})
