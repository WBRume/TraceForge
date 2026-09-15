/**
 * RAG 可导入 Markdown 构建工具。
 *
 * TraceForge 推荐使用统一的 Markdown 结构导入知识库 / RAG：
 * - 文件头部携带 YAML front-matter，方便 RAG 平台按 metadata 过滤（分类、产品、版本、项目、仓库等）。
 * - 正文使用统一的二级标题，便于切块与检索。
 *
 * 两个入口共用同一份来源模型：
 * 1. 问题定位结果气泡的「导出 Markdown」
 * 2. 案例详情页的「导出 Markdown」
 */
import type { DiagnosisResultPayload } from '@/types/diagnosis'

export interface RagMarkdownSection {
  heading: string
  body: string
}

export type RagMetadataValue = string | number | boolean | null | undefined

export interface RagMarkdownOptions {
  title: string
  metadata?: Record<string, RagMetadataValue>
  sections: RagMarkdownSection[]
}

export interface RagRepository {
  id?: string
  name?: string
  repo_name?: string
  repo_url?: string
  repo_slug?: string
  branch_name?: string
}

export interface RagCaseDetail {
  id?: string
  source_task_id?: string | null
  source_task_phenomenon?: string | null
  title?: string | null
  problem_description?: string | null
  product_name?: string | null
  product_version?: string | null
  site_name?: string | null
  project_name?: string | null
  repositories?: RagRepository[] | null
  code_context?: string | null
  analysis_process?: string | null
  root_cause?: string | null
  solution?: string | null
  category?: string | null
  priority?: string | null
  status?: string | null
  diagnosis_detail?: Record<string, unknown> | null
}

/**
 * 两处导出共用的规范化来源模型。
 * 问题定位结果和案例详情都先归一化到此结构，再由 buildRagMarkdownFromSource
 * 生成 Markdown，确保两边 metadata 与正文章节完全一致。
 */
export interface RagExportSource {
  title: string
  sourceType: 'diagnosis' | 'case'
  sourceId?: string
  sourceTaskId?: string
  caseId?: string
  namespace: 'knowledge'
  visibility: string
  status: string
  category?: string
  priority?: string
  productName?: string
  productVersion?: string
  siteName?: string
  projectName?: string
  repositories?: RagRepository[]
  problemDescription?: string
  resultContent?: string
  analysisProcess?: string
  rootCause?: string
  solution?: string
  codeContext?: string
  similarCases?: unknown
  callChain?: unknown
  confidence?: number
}

function yamlValue(value: RagMetadataValue): string {
  if (value === null || value === undefined) return '""'
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(String(value))
}

function pushSection(lines: string[], heading: string, body: unknown): void {
  const text = String(body ?? '').trim()
  if (!text) return
  lines.push(`## ${heading}`, '', text, '')
}

/**
 * 生成带 YAML front-matter 的 RAG Markdown。
 * 空 section 会被自动跳过，避免导入后出现空块。
 */
export function buildRagMarkdown({ title, metadata = {}, sections }: RagMarkdownOptions): string {
  const lines: string[] = ['---']
  const metaEntries = Object.entries(metadata).filter(([, value]) => {
    if (value === null || value === undefined) return false
    return String(value).trim() !== ''
  })
  for (const [key, value] of metaEntries) {
    lines.push(`${key}: ${yamlValue(value)}`)
  }
  lines.push('---', '', `# ${String(title).trim() || 'Untitled'}`, '')
  for (const section of sections) {
    pushSection(lines, section.heading, section.body)
  }
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n'
}

export function downloadMarkdownFile(markdown: string, filename: string): void {
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function locationText(startLine: unknown, endLine: unknown): string {
  const start = Number(startLine)
  const end = Number(endLine)
  if (!Number.isFinite(start)) return ''
  if (Number.isFinite(end) && end !== start) return `:${start}-${end}`
  return `:${start}`
}

function formatCallChain(callChain: unknown): string {
  if (!Array.isArray(callChain)) return ''
  const rows = callChain.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
  return rows.map((node, index) => {
    const seq = node.seq ?? index + 1
    const label = [node.module, node.function]
      .filter((value) => value != null && String(value).trim() !== '')
      .join('.') || String(node.file_path || '未命名节点')
    const lines = [`${seq}. ${label}`]
    if (node.file_path) lines.push(`   文件：${node.file_path}`)
    if (node.description) lines.push(`   说明：${node.description}`)
    return lines.join('\n')
  }).join('\n')
}

function formatCodeContext(codeContext: unknown): string {
  if (!Array.isArray(codeContext)) return ''
  const rows = codeContext.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
  return rows.map((item, index) => {
    const filePath = String(item.file_path || '')
    const location = locationText(item.start_line, item.end_line)
    const lines = [`${index + 1}. ${filePath}${location}`]
    if (item.note) lines.push(`   说明：${item.note}`)
    if (item.snippet) {
      const snippet = String(item.snippet).replace(/\n/g, '\n   ')
      lines.push('   ```', `   ${snippet}`, '   ```')
    }
    return lines.join('\n')
  }).join('\n\n')
}

function formatSimilarCases(similarCases: unknown): string {
  if (!Array.isArray(similarCases)) return ''
  const rows = similarCases.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
  return rows.map((item) => {
    const title = String(item.title || '')
    const similarity = item.similarity ? `（相似度：${item.similarity}）` : ''
    const lines = [`- **${title}**${similarity}`]
    if (item.summary) lines.push(`  - ${item.summary}`)
    if (item.reference) lines.push(`  - 参考：${item.reference}`)
    return lines.join('\n')
  }).join('\n')
}

function repositoryNames(repositories: unknown): string {
  if (!Array.isArray(repositories)) return ''
  return repositories
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => String(item.repo_name || item.name || item.repo_slug || '').trim())
    .filter(Boolean)
    .join(', ')
}

function formatRepositories(repositories: unknown): string {
  if (!Array.isArray(repositories)) return ''
  return repositories
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => {
      const name = String(item.repo_name || item.name || item.repo_slug || '').trim()
      const url = String(item.repo_url || '').trim()
      const branch = item.branch_name ? ` (${item.branch_name})` : ''
      return [name + branch, url].filter(Boolean).join(' - ')
    })
    .filter(Boolean)
    .join('\n')
}

function productVersionProjectRepoText(input: {
  productName?: unknown
  productVersion?: unknown
  siteName?: unknown
  projectName?: unknown
  repositories?: unknown
}): string {
  const versionText = input.productVersion ? String(input.productVersion) : '未填写'
  const lines = [
    input.productName ? `产品：${input.productName}` : '',
    `版本：${versionText}`,
    input.siteName ? `局点：${input.siteName}` : '',
    input.projectName ? `项目：${input.projectName}` : '',
  ].filter(Boolean)

  const repoText = formatRepositories(input.repositories)
  if (repoText) lines.push(`仓库：\n${repoText}`)

  return lines.join('\n')
}

/**
 * 唯一 Markdown 构建入口：
 * 无论来源是问题定位结果还是案例详情，都先归一化为 RagExportSource，
 * 再走这里生成完全相同结构的 Markdown。
 */
export function buildRagMarkdownFromSource(source: RagExportSource): string {
  const title = source.title.trim() || '未命名文档'
  const metadata: Record<string, RagMetadataValue> = {
    title,
    source_type: source.sourceType,
    source_id: source.sourceId || '',
    case_id: source.caseId || '',
    source_task_id: source.sourceTaskId || '',
    namespace: source.namespace,
    visibility: source.visibility,
    status: source.status,
    version: source.sourceType === 'case' ? 1 : undefined,
    category: source.category || '',
    priority: source.priority || '',
    product_name: source.productName || '',
    product_version: source.productVersion || '',
    site_name: source.siteName || '',
    project_name: source.projectName || '',
    repositories: repositoryNames(source.repositories),
    confidence: source.confidence,
  }

  return buildRagMarkdown({
    title,
    metadata,
    sections: [
      { heading: '产品/版本/项目/仓库', body: productVersionProjectRepoText(source) },
      { heading: '问题描述', body: source.problemDescription || '' },
      { heading: '结果内容', body: source.resultContent || '' },
      { heading: '分析过程', body: source.analysisProcess || '' },
      { heading: '根因', body: source.rootCause || '' },
      { heading: '解决方案', body: source.solution || '' },
      { heading: '代码上下文', body: source.codeContext || '' },
      { heading: '相似案例', body: formatSimilarCases(source.similarCases) },
      { heading: '调用链路', body: formatCallChain(source.callChain) },
    ],
  })
}

/**
 * 从问题定位结果生成 RAG Markdown。
 *
 * 适用于“尚未转案例”的阶段；输入先归一化为 RagExportSource，
 * 与案例详情导出共用同一套统一 Markdown 结构。
 */
export function buildDiagnosisRagMarkdown(
  payload: DiagnosisResultPayload,
  taskName: string,
  extras: {
    taskId?: string
    problemDescription?: string
    productName?: string
    productVersion?: string
    projectName?: string
    repositories?: RagRepository[]
  } = {},
): string {
  const title = taskName.trim() || '问题定位结果'
  const confidenceText = `置信度：${payload.confidence}%`
  const analysisText = [payload.evidence_chain, confidenceText].filter(Boolean).join('\n\n')
  const solutionParts = [
    payload.fix_suggestion,
    payload.fix_code ? `修复代码：\n\`\`\`\n${payload.fix_code}\n\`\`\`` : '',
  ].filter(Boolean).join('\n\n')

  return buildRagMarkdownFromSource({
    title,
    sourceType: 'diagnosis',
    sourceId: extras.taskId || '',
    sourceTaskId: extras.taskId || '',
    namespace: 'knowledge',
    visibility: 'workspace',
    status: 'candidate',
    confidence: payload.confidence,
    productName: extras.productName,
    productVersion: extras.productVersion,
    projectName: extras.projectName,
    repositories: extras.repositories,
    problemDescription: extras.problemDescription,
    resultContent: payload.summary ?? undefined,
    analysisProcess: analysisText,
    rootCause: payload.root_cause ?? undefined,
    solution: solutionParts,
    codeContext: formatCodeContext(payload.code_context),
    similarCases: payload.similar_cases,
    callChain: payload.call_chain,
  })
}

function detailString(detail: Record<string, unknown>, key: string): string | undefined {
  const value = detail[key]
  return typeof value === 'string' && value.trim() ? value : undefined
}

function detailNumber(detail: Record<string, unknown>, key: string): number | undefined {
  if (detail[key] === undefined || detail[key] === null) return undefined
  const value = Number(detail[key])
  return Number.isFinite(value) ? value : undefined
}

function caseAnalysisProcess(detail: Record<string, unknown>, fallback: string): string {
  const evidence = detailString(detail, 'evidence_chain')
  const confidence = detailNumber(detail, 'confidence')
  if (!evidence) return fallback

  const confidenceText = confidence === undefined ? '' : `置信度：${confidence}%`
  const fallbackText = fallback || ''
  const isDefaultStyle = !fallbackText || (
    fallbackText.includes(evidence)
    && /置信度\s*[:：]\s*\d+%/.test(fallbackText)
  )
  if (!isDefaultStyle) return fallbackText
  return [evidence, confidenceText].filter(Boolean).join('\n\n')
}

function caseSolution(detail: Record<string, unknown>, fallback: string): string {
  const fixCode = detailString(detail, 'fix_code')
  const suggestion = detailString(detail, 'fix_suggestion')
  if (!fixCode && !suggestion) return fallback

  // 保留案例可编辑文本中的说明部分；已转换生成的“修复代码:”旧文本统一替换为带围栏的 Markdown 代码块。
  const fallbackSuggestion = fallback.replace(/\n*修复代码:[\s\S]*$/, '').trim()
  const baseSuggestion = fallbackSuggestion || suggestion || ''
  const codeBlock = fixCode ? `修复代码：\n\`\`\`\n${fixCode}\n\`\`\`` : ''
  return [baseSuggestion, codeBlock].filter(Boolean).join('\n\n')
}

function caseCodeContext(detail: Record<string, unknown>, fallback: string): string {
  if (Array.isArray(detail.code_context) && detail.code_context.length > 0) {
    return formatCodeContext(detail.code_context)
  }
  return fallback
}

/**
 * 从案例详情（`serialize_case` 返回结构）生成 RAG Markdown。
 * 先归一化为 RagExportSource，与问题定位结果导出共用同一套 Markdown 结构。
 */
export function buildCaseRagMarkdown(caseDetail: RagCaseDetail): string {
  const title = String(caseDetail.title || '未命名案例')
  const detail = caseDetail.diagnosis_detail || {}
  const visibility = String(caseDetail.category || '').toUpperCase() === 'PUBLIC' ? 'public' : 'workspace'
  const status = String(caseDetail.status || '').toUpperCase() === 'APPROVED' ? 'published' : String(caseDetail.status || '')

  return buildRagMarkdownFromSource({
    title,
    sourceType: 'case',
    sourceId: caseDetail.id || '',
    sourceTaskId: caseDetail.source_task_id || '',
    caseId: caseDetail.id || '',
    namespace: 'knowledge',
    visibility,
    status,
    category: caseDetail.category || '',
    priority: caseDetail.priority || '',
    productName: caseDetail.product_name || '',
    productVersion: caseDetail.product_version || '',
    siteName: caseDetail.site_name || '',
    projectName: caseDetail.project_name || '',
    repositories: caseDetail.repositories || undefined,
    problemDescription: caseDetail.source_task_phenomenon || caseDetail.problem_description || '',
    resultContent: detailString(detail, 'summary') || '',
    analysisProcess: caseAnalysisProcess(detail, caseDetail.analysis_process || ''),
    rootCause: caseDetail.root_cause || detailString(detail, 'root_cause') || '',
    solution: caseSolution(detail, caseDetail.solution || ''),
    codeContext: caseCodeContext(detail, caseDetail.code_context || ''),
    similarCases: detail.similar_cases,
    callChain: detail.call_chain,
    confidence: detailNumber(detail, 'confidence'),
  })
}