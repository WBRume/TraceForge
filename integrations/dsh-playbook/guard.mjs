import { createHash, randomUUID } from 'node:crypto'

export const toolNames = ['propose_hypotheses', 'propose_experiment', 'propose_patch', 'read_source']
const version = '2026-07-28'

async function readResult(response, requestId) {
  const mime = (response.headers.get('content-type') || '').split(';')[0].trim()
  if (mime === 'application/json') return response.json()
  if (mime !== 'text/event-stream' || !response.body) throw new Error('PLAYBOOK_TOOL_INVALID_TRANSPORT')
  let buffered = ''
  for await (const chunk of response.body.pipeThrough(new TextDecoderStream())) {
    buffered += chunk
    if (buffered.length > 2_000_000) throw new Error('PLAYBOOK_TOOL_RESPONSE_TOO_LARGE')
    const records = buffered.split(/\r?\n\r?\n/)
    buffered = records.pop()
    for (const record of records) {
      const data = record.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
      if (!data) continue
      const message = JSON.parse(data)
      if (message.id === requestId) return message
    }
  }
  throw new Error('PLAYBOOK_TOOL_RESPONSE_UNCONFIRMED')
}

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
      const id = randomUUID()
      const response = await this.fetcher(policy.mcp_config.url, {
        method: 'POST', redirect: 'error',
        headers: {
          ...policy.mcp_config.headers, 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream',
          'MCP-Protocol-Version': version, 'Mcp-Method': 'tools/call', 'Mcp-Name': tool,
        },
        body: JSON.stringify({ jsonrpc: '2.0', id, method: 'tools/call', params: {
          name: tool, arguments: args, _meta: {
            'io.modelcontextprotocol/protocolVersion': version,
            'io.modelcontextprotocol/clientCapabilities': {},
            'io.traceforge/callId': String(callId),
          },
        } }),
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(30_000), ...(signal ? [signal] : [])]),
      })
      if (!response.ok) throw new Error(`PLAYBOOK_TOOL_HTTP_${response.status}`)
      const message = await readResult(response, id)
      if (message.jsonrpc !== '2.0' || message.id !== id) throw new Error('PLAYBOOK_TOOL_RESULT_UNCORRELATED')
      const result = message.result
      if (result?.resultType === 'input_required') throw new Error('PLAYBOOK_TOOL_INPUT_CAPABILITY_UNSUPPORTED')
      if (result?.resultType !== 'complete' || !Array.isArray(result.content) || typeof result.isError !== 'boolean'
          || !result.structuredContent || result.isError !== (result.structuredContent.kind === 'error')) {
        throw new Error('PLAYBOOK_TOOL_INVALID_RESULT')
      }
      if (this.reason(sessionId, tool)) throw new Error('PLAYBOOK_TICKET_REVOKED')
      return result
    } finally {
      active.delete(controller)
    }
  }
}
