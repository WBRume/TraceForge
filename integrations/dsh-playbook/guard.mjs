import { createHash } from 'node:crypto'

export const toolNames = ['propose_hypotheses', 'propose_experiment', 'propose_patch', 'read_source']

// This plugin belongs on a dedicated host. Every unbound session is denied,
// including delegated agents and PTC; an event observer is never an authority.
export class PlaybookGuard {
  #policies = new Map()
  #active = new Map()

  constructor(platformOrigin, fetcher = fetch) {
    this.platformOrigin = new URL(platformOrigin).origin
    this.fetcher = fetcher
  }

  install(input) {
    if (!input || typeof input.session_id !== 'string' || !input.session_id
        || !Number.isInteger(input.policy_epoch) || input.policy_epoch < 1
        || !['READONLY', 'WORKSPACE_WRITE'].includes(input.tier)
        || typeof input.dispatch_ticket !== 'string' || !input.dispatch_ticket
        || typeof input.mcp_config?.headers?.Authorization !== 'string'
        || new URL(input.mcp_config.url).origin !== this.platformOrigin) {
      throw new Error('INVALID_POLICY')
    }
    const previous = this.#policies.get(input.session_id)
    if (previous && input.policy_epoch < previous.policy_epoch) throw new Error('STALE_POLICY')
    if ((this.#active.get(input.session_id)?.size ?? 0) > 0) throw new Error('EXECUTOR_NOT_QUIESCENT')
    const policy = structuredClone(input)
    policy.expires = Date.now() + 3_600_000
    policy.revoked = false
    this.#policies.set(input.session_id, policy)
    return { session_id: input.session_id, dispatch_ticket: input.dispatch_ticket,
      policy_epoch: input.policy_epoch, guard_digest: createHash('sha256').update(JSON.stringify(input)).digest('hex') }
  }

  reason(sessionId, tool) {
    const policy = this.#policies.get(sessionId)
    if (!policy || policy.revoked || policy.expires <= Date.now()) return 'PLAYBOOK_TICKET_REQUIRED'
    if (!toolNames.includes(tool)) return 'PLAYBOOK_TOOL_DENIED'
    if (tool === 'propose_patch' && policy.tier !== 'WORKSPACE_WRITE') return 'PLAYBOOK_READONLY'
  }

  revoke(sessionId) {
    const policy = this.#policies.get(sessionId)
    if (policy) policy.revoked = true
    for (const controller of this.#active.get(sessionId) ?? []) controller.abort()
    return { revoked: true, active_calls: this.#active.get(sessionId)?.size ?? 0 }
  }

  close() {
    for (const sessionId of this.#policies.keys()) this.revoke(sessionId)
  }

  async execute(sessionId, tool, args, callId, signal) {
    const reason = this.reason(sessionId, tool)
    if (reason) throw new Error(reason)
    const policy = this.#policies.get(sessionId)
    const controller = new AbortController()
    const active = this.#active.get(sessionId) ?? new Set()
    active.add(controller)
    this.#active.set(sessionId, active)
    try {
      const response = await this.fetcher(policy.mcp_config.url, {
        method: 'POST', redirect: 'error',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', ...policy.mcp_config.headers },
        body: JSON.stringify({ jsonrpc: '2.0', id: String(callId), method: 'tools/call', params: { name: tool, arguments: args } }),
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(30_000), ...(signal ? [signal] : [])]),
      })
      if (!response.ok) throw new Error(`PLAYBOOK_TOOL_HTTP_${response.status}`)
      const result = (await response.json()).result
      if (!result || !Array.isArray(result.content)) throw new Error('PLAYBOOK_TOOL_INVALID_RESULT')
      if (this.reason(sessionId, tool)) throw new Error('PLAYBOOK_TICKET_REVOKED')
      return result
    } finally {
      active.delete(controller)
    }
  }
}
