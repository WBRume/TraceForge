import { createServer } from 'node:http'
import { timingSafeEqual } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { PlaybookGuard } from './guard.mjs'

export const name = 'traceforge-playbook-guard'
export const inject = ['tools']

export function apply(ctx, config = {}) {
  const secret = process.env.TRACEFORGE_PLAYBOOK_GUARD_TOKEN ?? ''
  if (secret.length < 32) throw new Error('TRACEFORGE_PLAYBOOK_GUARD_TOKEN must contain at least 32 characters')
  const guard = new PlaybookGuard(config.platformOrigin ?? 'http://127.0.0.1:8000')
  const schemas = JSON.parse(readFileSync(new URL('./tools.json', import.meta.url), 'utf8'))
  const unguard = ctx.tools.guard(exec => guard.reason(exec.agent.id, exec.name))
  for (const tool of schemas) {
    ctx.tools.register({
      name: tool.name, description: tool.description, parameters: tool.inputSchema,
      output: { schema: { type: 'object', additionalProperties: true }, render: (_args, result) => result.content },
      execute: (args, exec) => guard.execute(exec.agent.id, tool.name, args, exec.callId, exec.signal),
    })
  }
  const expected = Buffer.from(`Bearer ${secret}`)
  const server = createServer(async (req, res) => {
    res.setHeader('Content-Type', 'application/json')
    const supplied = Buffer.from(req.headers.authorization ?? '')
    if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) {
      res.writeHead(401).end(JSON.stringify({ error: 'UNAUTHORIZED' })); return
    }
    try {
      if (req.method === 'GET' && req.url === '/capabilities') {
        res.end(JSON.stringify({ protocol: 'traceforge-playbook-guard/1', pre_execution_deny: true })); return
      }
      if (req.method !== 'POST' || !['/policy', '/revoke'].includes(req.url)) {
        res.writeHead(404).end('{}'); return
      }
      const chunks = []
      let size = 0
      for await (const chunk of req) {
        size += chunk.length
        if (size > 64_000) throw new Error('REQUEST_TOO_LARGE')
        chunks.push(chunk)
      }
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
      const result = req.url === '/policy' ? guard.install(body) : guard.revoke(body.session_id)
      res.end(JSON.stringify(result))
    } catch (error) {
      res.writeHead(409).end(JSON.stringify({ error: error.message }))
    }
  })
  // Control credentials never authorize binding a public interface.
  server.listen(config.port ?? 4198, '127.0.0.1')
  ctx.on('dispose', () => { guard.close(); server.close(); unguard() })
}
