import { computed, ref, shallowRef } from 'vue'
import api from '@/utils/api'
import type { AssetDocumentCapabilities, AssetDocumentPayload, AssetThreadMarker, AssetVersion } from './types'
import type { AssetRequestOwner, AssetRequestScope } from './requestScope'

export function useAssetDocument(scope: AssetRequestScope, loadFailedMessage: () => string) {
  const documentData = ref<AssetDocumentPayload | null>(null)
  const versions = ref<AssetVersion[]>([])
  const loadingDocument = shallowRef(false)
  const loadingVersions = shallowRef(false)
  const error = shallowRef('')
  const activeVersionId = computed(() => documentData.value?.active_version?.id || '')
  const markersByBlock = computed(() => {
    const map: Record<string, AssetThreadMarker[]> = {}
    for (const marker of documentData.value?.thread_markers || []) {
      (map[marker.block_id] ||= []).push(marker)
    }
    return map
  })
  const capabilities = computed<AssetDocumentCapabilities>(() => documentData.value?.capabilities || {
    can_view: false,
    can_comment: false,
    can_ai_reply: false,
    can_apply_resolution: false,
    can_manual_edit: false,
    inline_review_enabled: false,
    ai_available: false,
    ai_unavailable_reason: null,
  })
  const clearError = () => { error.value = '' }
  const reset = () => {
    documentData.value = null
    versions.value = []
    loadingDocument.value = false
    loadingVersions.value = false
    clearError()
  }

  const loadDocument = (versionId?: string, owner = scope.capture()) => scope.run<AssetDocumentPayload | null>(
    'document', owner, async (request) => {
      loadingDocument.value = true
      clearError()
      try {
        const res = await api.get(`${request.baseUrl}/document`, {
          params: { version_id: versionId || undefined }, signal: request.signal,
        })
        if (!request.isCurrent()) return null
        const data = res.data as AssetDocumentPayload
        if (data.asset.id !== request.assetId || data.asset.workspace_id !== request.wsId) return null
        documentData.value = data
        return documentData.value
      } catch (err: any) {
        if (request.isCurrent()) {
          error.value = err?.response?.data?.detail || loadFailedMessage()
          documentData.value = null
        }
        return null
      } finally {
        if (request.isLatest()) loadingDocument.value = false
      }
    }, null,
  )

  const loadVersions = (owner = scope.capture()) => scope.run<AssetVersion[]>(
    'versions', owner, async (request) => {
      loadingVersions.value = true
      try {
        const res = await api.get(`${request.baseUrl}/versions`, { signal: request.signal })
        if (!request.isCurrent()) return []
        versions.value = ((res.data?.items || []) as AssetVersion[]).filter(item => item.asset_id === request.assetId)
        return versions.value
      } finally {
        if (request.isLatest()) loadingVersions.value = false
      }
    }, [],
  )

  const setMarkerCount = (threadId: string, delta: number) => {
    const marker = documentData.value?.thread_markers.find(item => item.thread_id === threadId)
    if (marker) marker.message_count = Math.max(0, Number(marker.message_count || 0) + delta)
  }

  return {
    documentData, versions, loadingDocument, loadingVersions, error, clearError,
    activeVersionId, markersByBlock, capabilities, reset, loadDocument, loadVersions, setMarkerCount,
  }
}

export type AssetDocumentModel = ReturnType<typeof useAssetDocument>
export type RefreshAssetDocument = (versionId?: string, owner?: AssetRequestOwner) => Promise<void>
