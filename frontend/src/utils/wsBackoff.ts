/**
 * WebSocket 重连退避：指数增长 + 随机抖动，避免服务端抖动时的连接风暴。
 *
 * delay = min(cap, base * 2^attempt) + rand(0, base)
 * 连接成功（onopen）时把 attempt 重置为 0。
 */
export function wsBackoffDelay(attempt: number, baseMs = 1200, capMs = 30000): number {
  const safeAttempt = Math.max(0, Math.floor(attempt))
  const exponential = Math.min(capMs, baseMs * Math.pow(2, safeAttempt))
  const jitter = Math.random() * baseMs
  return Math.round(exponential + jitter)
}
