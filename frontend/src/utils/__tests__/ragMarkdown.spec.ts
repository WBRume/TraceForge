import { describe, expect, it } from 'vitest'
import {
  buildCaseRagMarkdown,
  buildDiagnosisRagMarkdown,
  buildRagMarkdown,
} from '@/utils/ragMarkdown'
import type { DiagnosisResultPayload } from '@/types/diagnosis'

const diagnosisPayload: DiagnosisResultPayload = {
  summary: '连接池在高峰期被耗尽',
  root_cause: '连接池配置过小',
  evidence_chain: '日志显示获取连接超时',
  fix_suggestion: '扩容连接池并增加熔断',
  fix_code: 'pool.maxActive = 200',
  code_context: [
    { file_path: 'src/pool.py', start_line: 12, end_line: 34, snippet: 'pool = Pool(maxActive=50)', note: '连接池配置' },
  ],
  similar_cases: [{ title: '连接池耗尽排查', similarity: '高', reference: 'case-1', summary: '同类连接池问题' }],
  call_chain: [{ seq: 1, module: 'Gateway', function: 'handleRequest', file_path: 'Gateway.java', description: '入口' }],
  confidence: 85,
}

describe('ragMarkdown', () => {
  it('builds a diagnosis markdown that can be imported into RAG', () => {
    const markdown = buildDiagnosisRagMarkdown(diagnosisPayload, '接口偶发超时定位', {
      taskId: 'task-1',
      problemDescription: '生产环境接口偶发超时',
      productName: 'Billing',
      productVersion: '1.2.0',
      projectName: 'Billing 项目',
      repositories: [
        { repo_name: 'billing-service', repo_url: 'https://git.example.com/billing-service' },
      ],
    })

    expect(markdown).toContain('source_type: "diagnosis"')
    expect(markdown).toContain('source_task_id: "task-1"')
    expect(markdown).toContain('product_name: "Billing"')
    expect(markdown).toContain('product_version: "1.2.0"')
    expect(markdown).toContain('project_name: "Billing 项目"')
    expect(markdown).toContain('repositories: "billing-service"')
    expect(markdown).not.toContain('workspace_id')
    expect(markdown).not.toContain('workspace_name')
    expect(markdown).toContain('# 接口偶发超时定位')
    expect(markdown).toContain('## 问题描述')
    expect(markdown).toContain('生产环境接口偶发超时')
    expect(markdown).toContain('## 产品/版本/项目/仓库')
    expect(markdown).toContain('产品：Billing')
    expect(markdown.indexOf('## 产品/版本/项目/仓库')).toBeLessThan(markdown.indexOf('## 问题描述'))
    expect(markdown).toContain('版本：1.2.0')
    expect(markdown).toContain('项目：Billing 项目')
    expect(markdown).toContain('仓库：')
    expect(markdown).toContain('billing-service')
    expect(markdown).toContain('## 结果内容')
    expect(markdown).toContain('连接池在高峰期被耗尽')
    expect(markdown).toContain('## 根因')
    expect(markdown).toContain('连接池配置过小')
    expect(markdown).toContain('## 解决方案')
    expect(markdown).toContain('扩容连接池并增加熔断')
    expect(markdown).toContain('pool.maxActive = 200')
    expect(markdown).toContain('## 代码上下文')
    expect(markdown).toContain('src/pool.py:12-34')
    expect(markdown).toContain('## 相似案例')
    expect(markdown).toContain('连接池耗尽排查')
    expect(markdown).toContain('## 调用链路')
    expect(markdown).toContain('Gateway.handleRequest')
    expect(markdown).not.toContain('## 诊断明细')
    expect(markdown.indexOf('Gateway.handleRequest')).toBeGreaterThan(markdown.indexOf('## 调用链路'))
    expect(markdown).not.toContain('## 对话快照摘要')
    expect(markdown).not.toContain('## 评审意见')
  })

  it('builds a case markdown with RAG metadata and all required sections', () => {
    const markdown = buildCaseRagMarkdown({
      id: 'case-1',
      source_task_id: 'task-1',
      title: '接口偶发超时定位',
      problem_description: '生产环境接口偶发超时',
      product_name: 'Billing',
      product_version: '1.2.0',
      site_name: '华东局点',
      project_name: 'Billing 项目',
      repositories: [
        { repo_name: 'billing-service', repo_url: 'https://git.example.com/billing-service', branch_name: 'master' },
      ],
      code_context: '工作区关联仓库: billing-service\n\n相关代码上下文:\nsrc/pool.py',
      analysis_process: '压测复现并查看日志\n\n置信度: 85%',
      root_cause: '连接池耗尽',
      solution: '扩容连接池并增加熔断',
      category: 'PUBLIC',
      priority: 'P1',
      status: 'APPROVED',
      diagnosis_detail: {
        summary: '连接池在高峰期被耗尽',
        evidence_chain: '压测复现并查看日志',
        fix_suggestion: '扩容连接池并增加熔断',
        fix_code: 'pool.maxActive = 200',
        confidence: 85,
        similar_cases: [{ title: '连接池耗尽排查' }],
        call_chain: [{ module: 'Gateway', function: 'handleRequest' }],
        code_context: [{ file_path: 'src/pool.py', start_line: 12, end_line: 34, note: '连接池配置' }],
      },
    })

    expect(markdown).toContain('source_type: "case"')
    expect(markdown).toContain('case_id: "case-1"')
    expect(markdown).toContain('product_name: "Billing"')
    expect(markdown).toContain('product_version: "1.2.0"')
    expect(markdown).toContain('project_name: "Billing 项目"')
    expect(markdown).toContain('repositories: "billing-service"')
    expect(markdown).not.toContain('workspace_id')
    expect(markdown).not.toContain('workspace_name')
    expect(markdown).toContain('visibility: "public"')
    expect(markdown).toContain('status: "published"')
    expect(markdown).toContain('# 接口偶发超时定位')
    expect(markdown).toContain('## 问题描述')
    expect(markdown).toContain('## 产品/版本/项目/仓库')
    expect(markdown).toContain('产品：Billing')
    expect(markdown.indexOf('## 产品/版本/项目/仓库')).toBeLessThan(markdown.indexOf('## 问题描述'))
    expect(markdown).toContain('版本：1.2.0')
    expect(markdown).toContain('局点：华东局点')
    expect(markdown).toContain('项目：Billing 项目')
    expect(markdown).toContain('仓库：')
    expect(markdown).toContain('billing-service (master) - https://git.example.com/billing-service')
    expect(markdown).toContain('## 结果内容')
    expect(markdown).toContain('连接池在高峰期被耗尽')
    expect(markdown).toContain('## 分析过程')
    expect(markdown).toContain('压测复现并查看日志')
    expect(markdown).toContain('置信度：85%')
    expect(markdown).toContain('## 根因')
    expect(markdown).toContain('连接池耗尽')
    expect(markdown).toContain('## 解决方案')
    expect(markdown).toContain('扩容连接池并增加熔断')
    expect(markdown).toContain('```\npool.maxActive = 200\n```')
    expect(markdown).toContain('## 代码上下文')
    expect(markdown).toContain('1. src/pool.py:12-34')
    expect(markdown).toContain('说明：连接池配置')
    expect(markdown).not.toContain('工作区关联仓库')
    expect(markdown).toContain('## 相似案例')
    expect(markdown).toContain('连接池耗尽排查')
    expect(markdown).toContain('## 调用链路')
    expect(markdown).toContain('Gateway.handleRequest')
    expect(markdown).not.toContain('## 诊断明细')
    expect(markdown).not.toContain('## 对话快照摘要')
    expect(markdown).not.toContain('## 评审意见')
    expect(markdown).not.toContain('review_round')
    expect(markdown).not.toContain('reviewer_id')
    expect(markdown).not.toContain('approved_at')
  })

  it('skips empty sections automatically', () => {
    const markdown = buildRagMarkdown({
      title: '空字段文档',
      sections: [
        { heading: '保留', body: '有内容' },
        { heading: '丢弃', body: '   ' },
      ],
    })
    expect(markdown).toContain('## 保留')
    expect(markdown).not.toContain('## 丢弃')
  })
})
