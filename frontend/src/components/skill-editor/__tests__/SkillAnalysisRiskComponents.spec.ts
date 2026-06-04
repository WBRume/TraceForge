import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SkillAnalysisRiskDetail from '@/components/skill-editor/SkillAnalysisRiskDetail.vue'
import SkillAnalysisRiskList from '@/components/skill-editor/SkillAnalysisRiskList.vue'
import type { SkillAnalysisRiskItem } from '@/types/skillAnalysis'

const risks: SkillAnalysisRiskItem[] = [
  {
    id: 'risk-a',
    risk_type: 'SECRET_ACCESS',
    risk_level: 'HIGH',
    file_path: 'SKILL.md',
    line_start: 12,
    title: 'SKILL.md:12 出现 token 访问线索',
    description: '该位置读取 token，可能暴露凭据。',
    evidence_summary: '读取 API_TOKEN 环境变量。',
    evidence_detail: '位置：SKILL.md:12\n命中内容：const token = process.env.API_TOKEN',
    matched_text: 'const token = process.env.API_TOKEN',
    recommendation: '确认 token 不会写入日志或外部请求。',
    source: 'static-rule',
    confidence: 0.78,
  },
  {
    risk_type: 'NETWORK_ACCESS',
    risk_level: 'MEDIUM',
    file_path: 'tools/fetch.ts',
    line_start: 3,
    evidence_summary: 'fetch 外部 URL',
    source: 'static-rule',
    confidence: 0.7,
  },
]

describe('SkillAnalysis risk components', () => {
  it('renders concrete risk rows and emits detail navigation', async () => {
    const wrapper = mount(SkillAnalysisRiskList, {
      props: { risks },
    })

    expect(wrapper.text()).toContain('SKILL.md:12 出现 token 访问线索')
    expect(wrapper.text()).toContain('读取 API_TOKEN 环境变量。')
    expect(wrapper.text()).toContain('SKILL.md:12')

    await wrapper.find('.risk-card').trigger('click')
    expect(wrapper.emitted('openRisk')?.[0]).toEqual(['risk-a'])
  })

  it('renders risk detail with evidence and emits file/back/navigation events', async () => {
    const wrapper = mount(SkillAnalysisRiskDetail, {
      props: { risks, riskKey: 'risk-a' },
    })

    expect(wrapper.text()).toContain('SKILL.md:12 出现 token 访问线索')
    expect(wrapper.text()).toContain('该位置读取 token')
    expect(wrapper.text()).toContain('读取 API_TOKEN 环境变量。')
    expect(wrapper.text()).toContain('const token = process.env.API_TOKEN')
    expect(wrapper.text()).toContain('确认 token 不会写入日志或外部请求。')

    const buttons = wrapper.findAll('button')
    await buttons[0].trigger('click')
    expect(wrapper.emitted('back')).toHaveLength(1)

    await wrapper.find('.btn-locate-file').trigger('click')
    expect(wrapper.emitted('openFile')?.[0]).toEqual(['SKILL.md'])

    await buttons[2].trigger('click')
    expect(wrapper.emitted('openRisk')?.[0]?.[0]).toContain('NETWORK_ACCESS')
  })

  it('falls back for legacy risk items without enriched fields', () => {
    const wrapper = mount(SkillAnalysisRiskDetail, {
      props: { risks, riskKey: 'NETWORK_ACCESS-tools-fetch-ts-3-static-rule-1' },
    })

    expect(wrapper.text()).toContain('tools/fetch.ts:3 · NETWORK_ACCESS')
    expect(wrapper.text()).toContain('fetch 外部 URL')
    expect(wrapper.text()).toContain('请结合文件上下文人工复核')
  })
})
