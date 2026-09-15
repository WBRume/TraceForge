import api from '@/utils/api'
import type { SearchCapabilities, SearchResponse, Retrieval, MessageContext } from '@/types/search'

export const searchApi = {
  capabilities: (signal?: AbortSignal) => api.get<SearchCapabilities>('/search/capabilities', { signal }).then(r => r.data),
  query: (params: { q: string; retrieval: Retrieval; type: string; cursor?: string }, signal: AbortSignal) =>
    api.get<SearchResponse>('/search', { params, signal }).then(r => r.data),
  close: (cursor: string) => api.post('/search/sessions/close', { cursor }),
  context: (ws: string, task: string, message: string, signal: AbortSignal) =>
    api.get<MessageContext>(`/workspaces/${ws}/tasks/${task}/messages/${message}/context`, { signal }).then(r => r.data),
  moreContext: (ws: string, task: string, cursor: string, direction: 'before' | 'after', signal: AbortSignal) =>
    api.get<MessageContext>(`/workspaces/${ws}/tasks/${task}/messages/context`, { params: { cursor, direction }, signal }).then(r => r.data),
}
