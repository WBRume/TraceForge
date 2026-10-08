import type { ConfirmationField } from '../types'

type Message = { id?: string; role?: string; content?: string; metadata?: any; delivery_status?: string; session_generation?: number | null }
type Translate = (key: string, values?: Record<string, unknown>) => string

export type ConfirmationHistoryRow = {
  key: string
  title: string
  description: string
  options: string[]
  values: unknown[]
}

export type ConfirmationHistoryRecord = {
  kind: 'question' | 'answer' | 'resolution'
  status: string
  prompt: string
  rows: ConfirmationHistoryRow[]
  hasRecordedAnswer: boolean
}

export function isRedundantConfirmationReceipt(record: ConfirmationHistoryRecord | null): boolean {
  return record?.kind === 'resolution' && record.status === 'answered' && record.hasRecordedAnswer
}

const accepted = (message: Message) => !message.delivery_status || message.delivery_status === 'sent'
const parseAnswer = (value: unknown): unknown => {
  if (typeof value !== 'string') return value
  try { return JSON.parse(value) } catch { return value }
}

/** Present only explicitly linked confirmation messages; ordinary JSON remains ordinary chat. */
export function confirmationHistoryRecord(message: Message, messages: Message[] = []): ConfirmationHistoryRecord | null {
  const meta = message.metadata || {}
  const question = message.role === 'assistant' ? meta.confirmation : undefined
  const resolution = message.role === 'assistant' ? meta.confirmation_resolution : undefined
  const interactionId = question?.interaction_id || resolution?.interaction_id || meta.interaction_id
  if (!interactionId || (!question && !resolution && message.role !== 'user')) return null
  const related = messages.filter(item => item.session_generation === message.session_generation)
  const parent = question ? message : related.find(item => item.role === 'assistant'
    && item.metadata?.confirmation?.interaction_id === interactionId)
  const context = question || parent?.metadata?.confirmation || meta.confirmation_context || {}
  const kind = question ? 'question' : resolution ? 'resolution' : 'answer'
  const answer = resolution ? resolution.answer : parseAnswer(meta.confirmation_value ?? message.content)
  const localAnswer = related.find(item => item.role === 'user' && accepted(item)
    && item.metadata?.interaction_id === interactionId)
  const hasRecordedAnswer = Boolean(localAnswer || meta.confirmation_context?.answer_message_id)
  const showAnswers = kind === 'answer' || (kind === 'resolution' && resolution.status === 'answered' && !hasRecordedAnswer && answer != null)
  const fields: ConfirmationField[] = Array.isArray(context.fields) ? context.fields.filter((field: ConfirmationField) => !field.hidden) : []
  const answerMap = answer && typeof answer === 'object' && !Array.isArray(answer) ? answer as Record<string, unknown> : null
  const entries = fields.length ? fields : answerMap
    ? Object.keys(answerMap).map(key => ({ key, title: key } as ConfirmationField))
    : kind !== 'question' || context.options?.length ? [{ key: 'answer', title: '', options: context.options } as ConfirmationField] : []
  const rows = (kind === 'question' || showAnswers) ? entries.map(field => {
    const options = Array.isArray(field.options) ? field.options : []
    const value = answerMap ? answerMap[field.key] : answer
    const values = Array.isArray(value) ? value : [value]
    return {
      key: field.key,
      title: field.title || '',
      description: field.description || '',
      options: options.map(option => typeof option === 'string' ? option : option.label || option.value),
      values: showAnswers ? values.map(item => {
        const option = options.find(option => typeof option !== 'string' && (option.value === item
          || (typeof item === 'string' && item.startsWith(option.value + '\n'))))
        if (!option?.label) return item
        return typeof item === 'string' ? option.label + item.slice(option.value.length) : option.label
      }) : [],
    }
  }) : []
  const prompt = String(parent?.content || meta.confirmation_context?.prompt || (question ? message.content : '') || '')
  // Form titles are short headings; their complete questions live in fields.
  return {
    kind, status: String(resolution?.status || (kind === 'answer' && !accepted(message) ? 'unconfirmed' : '')),
    prompt: fields.length || (kind === 'resolution' && hasRecordedAnswer) ? '' : prompt, rows, hasRecordedAnswer,
  }
}

export function confirmationValueText(values: unknown[], t: Translate): string {
  if (!values.length) return t('chat.confirmation_history.none_selected')
  return values.map(value => {
    if (value == null || value === '') return t('chat.confirmation_history.not_provided')
    if (typeof value === 'boolean') return t(`chat.confirmation_history.${value ? 'yes' : 'no'}`)
    return typeof value === 'object' ? JSON.stringify(value) : String(value)
  }).join('、')
}

export function confirmationHistoryText(record: ConfirmationHistoryRecord, t: Translate): string {
  const heading = record.kind === 'resolution'
    ? t(`chat.confirmation_history.${['answered', 'cancelled', 'approved', 'rejected', 'closed'].includes(record.status) ? record.status : 'closed'}`)
    : t(`chat.confirmation_history.${record.kind}`)
  return [heading, record.prompt, ...record.rows.map((row, index) => [
    `${index + 1}. ${row.title || row.description || t('chat.confirmation_history.item', { index: index + 1 })}`,
    row.title && row.description ? row.description : '',
    record.kind === 'question' ? row.options.join(' / ') : confirmationValueText(row.values, t),
  ].filter(Boolean).join('\n'))].filter(Boolean).join('\n\n')
}
