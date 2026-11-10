export interface AssetRequestOwner {
  readonly wsId: string
  readonly assetId: string
  readonly baseUrl: string
  readonly signal: AbortSignal
  isCurrent: () => boolean
}

interface AssetRequest extends AssetRequestOwner {
  isLatest: () => boolean
}

export function createAssetRequestScope() {
  let current: AssetRequestOwner | undefined
  let resourceController: AbortController | undefined
  const latest = new Map<string, AbortController>()

  const invalidate = () => {
    resourceController?.abort()
    current = undefined
    latest.clear()
  }

  const activate = (wsId: string, assetId: string) => {
    invalidate()
    if (!wsId || !assetId) return
    const controller = new AbortController()
    resourceController = controller
    const owner: AssetRequestOwner = {
      wsId,
      assetId,
      baseUrl: `/workspaces/${wsId}/assets/${assetId}`,
      signal: controller.signal,
      isCurrent: () => current === owner && !controller.signal.aborted,
    }
    current = owner
    return owner
  }

  // The owner fixes the resource and generation for the entire async chain.
  // Named queries additionally supersede older queries for the same state.
  const run = async <T>(
    key: string | null,
    owner: AssetRequestOwner | undefined,
    action: (request: AssetRequest) => Promise<T>,
    fallback: T,
  ): Promise<T> => {
    if (!owner?.isCurrent()) return fallback
    if (key) latest.get(key)?.abort()
    const resource = current
    const controller = new AbortController()
    if (key) latest.set(key, controller)
    const abort = () => controller.abort()
    owner.signal.addEventListener('abort', abort, { once: true })
    const request: AssetRequest = {
      ...owner,
      signal: controller.signal,
      isCurrent: () => owner.isCurrent() && !controller.signal.aborted,
      isLatest: () => current === resource && (key ? latest.get(key) === controller : owner.isCurrent()),
    }
    try {
      const result = await action(request)
      return request.isCurrent() ? result : fallback
    } catch (error) {
      if (request.isCurrent()) throw error
      return fallback
    } finally {
      owner.signal.removeEventListener('abort', abort)
    }
  }

  return { activate, invalidate, capture: () => current, run }
}

export type AssetRequestScope = ReturnType<typeof createAssetRequestScope>
