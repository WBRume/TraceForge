/** Shared by Tauri and Electron. Node workers execute blocking Git/file I/O. */
type Dispatch = (worker: number, kind: string, payload: any) => Promise<any>
// Profiles hosted in the same desktop process may map the same personal repo.
const registrations = new Map<string, Promise<unknown>>()

export class ResourceScheduler {
  private tails = new Map<string, Promise<unknown>>()
  private available = [1, 2]
  private waiters: ((worker: number) => void)[] = []
  private active = new Set<Promise<any>>()
  private send: Dispatch
  constructor(send: Dispatch) { this.send = send }

  private async exclusive<T>(key: string, action: () => Promise<T>): Promise<T> {
    const tails = key === 'registration' ? registrations : this.tails
    const previous = tails.get(key) ?? Promise.resolve()
    const next = previous.catch(() => {}).then(action)
    tails.set(key, next)
    try { return await next }
    finally { if (tails.get(key) === next) tails.delete(key) }
  }
  private async io(kind: string, payload: any) {
    const worker = this.available.shift() ?? await new Promise<number>(resolve => this.waiters.push(resolve))
    try { return await this.send(worker, kind, payload) }
    finally {
      const waiter = this.waiters.shift()
      if (waiter) waiter(worker); else this.available.push(worker)
    }
  }
  dispatch(kind: string, payload: any): Promise<any> {
    const work = this.schedule(kind, payload)
    this.active.add(work)
    work.then(() => this.active.delete(work), () => this.active.delete(work))
    return work
  }
  async drain(): Promise<void> {
    while (this.active.size) await Promise.allSettled([...this.active])
  }
  private async schedule(kind: string, payload: any): Promise<any> {
    if (kind === 'collaboration') {
      // Watchers and transport deltas remain on their original dedicated worker.
      return this.exclusive('task:' + payload.payload?.task_id, () => ['prepare', 'release', 'initialize'].includes(payload.kind)
        ? this.exclusive('registration', () => this.send(0, kind, payload)) : this.send(0, kind, payload))
    }
    if (kind !== 'operation') return this.io(kind, payload)
    return this.exclusive('operation:' + payload.operation_id, () => this.exclusive('task:' + payload.task_id, async () => {
      if (payload.kind === 'provision') {
        // Host-wide registration also covers two paths aliasing the same .git.
        const registered = await this.exclusive('registration', () => this.io('register', payload))
        if (registered.state === 'SUCCEEDED') return registered
        return this.io('checkout', payload)
      }
      if (['release', 'apply_patch'].includes(payload.kind) || (payload.kind === 'initialize' && payload.payload?.action === 'fetch')) {
        return this.exclusive('registration', () => this.io(kind, payload))
      }
      return this.io(kind, payload)
    }))
  }
}
