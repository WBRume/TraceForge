import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { startLocalResourceService } from '../server'

// Execute the bundled production worker, never TypeScript in a test loader.
export async function startServer(config: Parameters<typeof startLocalResourceService>[0], options: Parameters<typeof startLocalResourceService>[1] = {}) {
  const service = await startLocalResourceService(config, {
    workerUrl: new URL('../../../dist-desktop-host/localResourceWorker.js', import.meta.url), ...options,
  })
  const address = service.server?.address() as AddressInfo | undefined
  const server = service.server && address ? Object.assign(service.server, {
    url: new URL(`http://127.0.0.1:${address.port}`), port: address.port,
  }) : undefined
  return { ...service, server }
}

export async function serve(options: { fetch: (request: Request) => Response }) {
  const server = createServer(async (request, response) => {
    try {
      const result = options.fetch(new Request(new URL(request.url || '/', 'http://127.0.0.1')))
      response.writeHead(result.status, Object.fromEntries(result.headers))
      response.end(Buffer.from(await result.arrayBuffer()))
    } catch {
      response.writeHead(404); response.end()
    }
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address() as AddressInfo
  return {
    url: new URL(`http://127.0.0.1:${address.port}`),
    stop: async () => {
      const closed = new Promise<void>(resolve => server.close(() => resolve()))
      server.closeAllConnections()
      await closed
    },
  }
}
