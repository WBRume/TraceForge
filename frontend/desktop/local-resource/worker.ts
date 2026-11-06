import './platform-node'
import { parentPort } from 'node:worker_threads'
import { Runtime, type Config } from './runtime'
let runtime: Runtime
let pending = Promise.resolve()
parentPort!.on('message', ({ id, kind, payload }) => {
  pending = pending.then(async () => {
  try {
    if (kind === 'configure') {
      runtime = new Runtime(payload as Config)
      runtime.collaboration.index.onChanged = task_id => parentPort!.postMessage({ event: 'collaboration_changed', task_id })
      parentPort!.postMessage({ id, result: true }); return
    }
    if (kind === 'shutdown') { await runtime?.collaboration.close(); runtime?.db.close(); parentPort!.postMessage({ id, result: true }); return }
    if (kind === 'grant_roots') { runtime.config.allowed_roots = payload; parentPort!.postMessage({ id, result: true }); return }
    const result = kind === 'inspect' ? runtime.inspect(payload)
      : kind === 'collaboration' ? await runtime.collaboration.executeAsync(payload.kind, payload.payload)
      : runtime.operation(payload, kind === 'register' ? 'register' : kind === 'checkout' ? 'checkout' : 'all')
    parentPort!.postMessage({ id, result })
  } catch (error) { parentPort!.postMessage({ id, error: error instanceof Error ? error.message : String(error) }) }
  })
})
