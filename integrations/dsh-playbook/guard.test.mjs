import test from 'node:test'
import assert from 'node:assert/strict'
import { PlaybookGuard } from './guard.mjs'

const policy = { session_id: 'one', policy_epoch: 1, tier: 'READONLY', dispatch_ticket: 'call-1',
  mcp_config: { url: 'http://localhost:8000/api/playbook-tools/run', headers: { Authorization: 'Bearer ticket' } } }

test('unbound/delegated sessions and native filesystem/shell tools are denied', () => {
  const guard = new PlaybookGuard('http://localhost:8000')
  guard.install(policy)
  assert.equal(guard.reason('other', 'read_source'), 'PLAYBOOK_TICKET_REQUIRED')
  for (const name of ['bash', 'write_file', 'run_code', 'task', 'webfetch']) assert.equal(guard.reason('one', name), 'PLAYBOOK_TOOL_DENIED')
  assert.equal(guard.reason('one', 'propose_patch'), 'PLAYBOOK_READONLY')
  assert.equal(guard.reason('one', 'read_source'), undefined)
})

test('stale epoch and cross-origin proxy requests cannot install', () => {
  const guard = new PlaybookGuard('http://localhost:8000')
  guard.install({ ...policy, policy_epoch: 2 })
  assert.throws(() => guard.install(policy), /STALE_POLICY/)
  assert.throws(() => guard.install({ ...policy, mcp_config: { ...policy.mcp_config, url: 'http://other/' } }), /INVALID_POLICY/)
})

test('revocation aborts in-flight tools; policy change requires quiescence', async () => {
  const guard = new PlaybookGuard('http://localhost:8000', async (_url, request) => new Promise((_resolve, reject) => {
    request.signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true })
  }))
  guard.install(policy)
  const call = guard.execute('one', 'read_source', { path: '.' }, 'id')
  assert.throws(() => guard.install({ ...policy, policy_epoch: 2 }), /EXECUTOR_NOT_QUIESCENT/)
  guard.revoke('one')
  await assert.rejects(call, /aborted/)
  assert.equal(guard.reason('one', 'read_source'), 'PLAYBOOK_TICKET_REQUIRED')
})
