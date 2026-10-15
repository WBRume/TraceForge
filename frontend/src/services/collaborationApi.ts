import api from '@/utils/api'
import type { CollaborationManifest, CollaborationState, CollaborationHumanChangePage, CollaborationHumanChangeDetail } from '@/types/collaboration'

// Multi-repository manifests and raw objects can exceed a normal API request's
// transfer time. Lease and state requests retain the short default timeout.
const contentRequest = { timeout: 120_000 }

export function collaborationApi(workspaceId: string, taskId: string) {
  const path = `/workspaces/${encodeURIComponent(workspaceId)}/tasks/${encodeURIComponent(taskId)}/collaboration`
  return {
    reviewBaseline: async (): Promise<CollaborationManifest> => (await api.get(`${path}/review/baseline`, contentRequest)).data,
    review: async (): Promise<{ input: CollaborationManifest; cloud: CollaborationManifest; running: boolean }> => (await api.get(`${path}/review`, contentRequest)).data,
    state: async (): Promise<CollaborationState> => (await api.get(path)).data,
    humanChanges: async (page = 1): Promise<CollaborationHumanChangePage> => (await api.get(`${path}/human-changes`, { params: { page } })).data,
    humanChange: async (id: string): Promise<CollaborationHumanChangeDetail> => (await api.get(`${path}/human-changes/${encodeURIComponent(id)}`)).data,
    post: async <T = CollaborationState>(action: string, payload: Record<string, unknown>): Promise<T> => (await api.post(`${path}/${action}`, payload)).data,
    snapshot: async (id: string, base?: string): Promise<CollaborationManifest> => (await api.get(`${path}/snapshots/${encodeURIComponent(id)}`, { ...contentRequest, params: base ? { base_snapshot_id: base } : {} })).data,
    object: async (hash: string): Promise<ArrayBuffer> => (await api.get(`${path}/objects/${hash}`, { ...contentRequest, responseType: 'arraybuffer' })).data,
    upload: async (hash: string, data: Uint8Array, identity: { client_id: string; instance_id: string; lease_epoch: number }): Promise<void> => { await api.put(`${path}/objects/${hash}`, data, { ...contentRequest, params: identity, headers: { 'Content-Type': 'application/octet-stream' } }) },
  }
}

export function base64Bytes(content: string): Uint8Array {
  return Uint8Array.from(atob(content), (char) => char.charCodeAt(0))
}
export function bytesBase64(data: ArrayBuffer): string {
  const bytes = new Uint8Array(data)
  let text = ''
  for (let offset = 0; offset < bytes.length; offset += 8192) text += String.fromCharCode(...bytes.subarray(offset, offset + 8192))
  return btoa(text)
}
