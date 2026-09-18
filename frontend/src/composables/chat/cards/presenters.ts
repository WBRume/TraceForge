/**
 * 置顶卡片的展示层纯函数：状态卡文案解析与 HITL 选项归一化。
 * 无状态、无副作用，仅做「引擎/后端数据 → 界面文案」的转换。
 */

/** 去掉状态消息尾部「(model: xxx)」标注，正文只保留纯状态描述。 */
export function statusMessageText(message: unknown): string {
  return String(message || '').replace(/\s*\(model:\s*[^)]*\)\s*$/i, '').trim()
}

/** 优先取卡片显式 model 字段，否则从状态消息中的「(model: xxx)」标注解析。 */
export function statusModelText(card: { model?: unknown; message?: unknown } | null | undefined): string {
  const explicit = String(card?.model || '').trim()
  if (explicit) return explicit
  const match = String(card?.message || '').match(/\(model:\s*([^)]+)\)/i)
  return match?.[1]?.trim() || ''
}

/** HITL 选项兼容两种形态：{ value, label } 对象或纯字符串。 */
export function hitlOptionValue(option: unknown): string {
  if (option && typeof option === 'object') {
    const item = option as Record<string, unknown>
    return String(item.value ?? item.label ?? '').trim()
  }
  return String(option ?? '').trim()
}

export function hitlOptionLabel(option: unknown): string {
  if (option && typeof option === 'object') {
    const item = option as Record<string, unknown>
    return String(item.label ?? item.value ?? '').trim()
  }
  return String(option ?? '').trim()
}
