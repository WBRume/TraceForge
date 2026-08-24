/**
 * 统一 Markdown 导出方案。
 *
 * 问题定位结果气泡与案例详情页都通过此入口导出 RAG 可导入 Markdown，
 * 保证两份导出使用同一套 front-matter 和章节格式。
 */
import type { DiagnosisResultPayload } from '@/types/diagnosis'
import {
  buildCaseRagMarkdown,
  buildDiagnosisRagMarkdown,
  downloadMarkdownFile,
  type RagCaseDetail,
  type RagRepository,
} from '@/utils/ragMarkdown'

export interface DiagnosisMarkdownExportOptions {
  taskId?: string
  problemDescription?: string
  productName?: string
  productVersion?: string
  projectName?: string
  repositories?: RagRepository[]
}

function safeFileName(value: string): string {
  return value.replace(/[\\/:*?"<>|]/g, '_')
}

export function useMarkdownExport() {
  const exportDiagnosisMarkdown = (
    payload: DiagnosisResultPayload,
    taskName: string,
    options: DiagnosisMarkdownExportOptions = {},
  ) => {
    const markdown = buildDiagnosisRagMarkdown(payload, taskName, options)
    const safeName = safeFileName((taskName || 'diagnosis-result').trim())
    downloadMarkdownFile(markdown, `${safeName}-定位结果.md`)
  }

  const exportCaseMarkdown = (caseDetail: RagCaseDetail) => {
    const markdown = buildCaseRagMarkdown(caseDetail)
    const safeName = safeFileName(String(caseDetail.title || caseDetail.id || 'case'))
    downloadMarkdownFile(markdown, `${safeName}-RAG.md`)
  }

  return {
    exportDiagnosisMarkdown,
    exportCaseMarkdown,
    downloadMarkdownFile,
  }
}