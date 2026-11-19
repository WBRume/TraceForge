import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import type { AssetDocumentPayload, AssetVersion } from '@/composables/asset-discussion/types'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import type { ReviewBlock } from './docxReviewSource'

type DraftState = { base_version_id: string; revision: number }
type Draft = DraftState & {
  text: string | null
  docx_edits: Record<string, string>
  blocks: ReviewBlock[] | null
}

function withOriginalLineEndings(input: string, original: string): string {
  const normalized = original.replace(/\r\n?/g, '\n')
  if (input === normalized) return original
  const endings = [...original.matchAll(/\r\n|\r|\n/g)].map(match => match[0])
  if (!endings.length) return input

  let first = 0
  let tail = 0
  while (first < input.length && input[first] === normalized[first]) first++
  while (tail < Math.min(input.length, normalized.length) - first
    && input.at(-1 - tail) === normalized.at(-1 - tail)) tail++
  const countBreaks = (text: string) => (text.match(/\n/g) || []).length
  const prefixBreaks = countBreaks(input.slice(0, first))
  const suffixBreaks = tail ? countBreaks(input.slice(-tail)) : 0
  const totalBreaks = countBreaks(input)
  let breakIndex = 0
  return input.replace(/\n/g, () => {
    const index = breakIndex++
    if (index < prefixBreaks) return endings[index]!
    if (index >= totalBreaks - suffixBreaks) return endings[endings.length - totalBreaks + index]!
    return endings[Math.min(index, endings.length - suffixBreaks - 1)] ?? endings[0]!
  })
}

export function useDocumentDraft(options: {
  url: Ref<string>
  document: Ref<AssetDocumentPayload | null>
  activeVersionId: Ref<string>
  onPublished: (version: AssetVersion) => Promise<unknown>
}) {
  const { t } = useI18n()
  const draft = ref<Draft | null>(null)
  const editing = ref(false)
  const busy = ref(false)
  const editingBlockId = ref('')
  const source = ref<string | null>(null)
  const originalText = ref<string | null>(null)
  const confirm = ref<'publish' | 'discard' | 'leave' | null>(null)
  const baseVersion = computed(() => draft.value?.base_version_id)
  const stale = computed(() => !!baseVersion.value && baseVersion.value !== options.activeVersionId.value)
  const dirty = computed(() => editing.value && source.value !== (draft.value?.text ?? null))
  const canPublish = computed(() =>
    !!draft.value?.revision && !dirty.value && !stale.value && !editingBlockId.value &&
    (draft.value.text === null ? Object.keys(draft.value.docx_edits).length > 0 : draft.value.text !== originalText.value),
  )

  function close() {
    editing.value = false
    editingBlockId.value = ''
    source.value = null
    originalText.value = null
    confirm.value = null
  }

  watch(options.url, () => {
    close()
    busy.value = false
    draft.value = null
  }, { flush: 'sync' })

  async function begin() {
    const { url, document } = options
    const target = url.value
    const published = document.value
    const version = published?.active_version
    if (!target || !version || busy.value) return
    busy.value = true
    try {
      const { data } = await api.get<Draft | null>(target)
      if (target !== url.value) return
      originalText.value = published.source_text ?? null
      draft.value = data ?? {
        base_version_id: version.id,
        revision: 0,
        text: originalText.value,
        docx_edits: {},
        blocks: originalText.value === null ? published.blocks : null,
      }
      source.value = draft.value.text
      editing.value = true
    } catch (error) {
      ElMessage.error(formatApiError(error, t('doc_review.draft_load_failed'), t))
    } finally {
      if (target === url.value) busy.value = false
    }
  }

  function updateSource(event: Event) {
    const input = event.target as HTMLTextAreaElement
    source.value = withOriginalLineEndings(input.value, source.value ?? '')
  }

  async function save(edits: Record<string, string>) {
    const target = options.url.value
    const current = draft.value
    if (!current || busy.value) return
    busy.value = true
    try {
      const { data } = await api.put<Draft>(target, {
        base_version_id: current.base_version_id,
        revision: current.revision,
        text: source.value,
        docx_edits: edits,
      })
      if (target === options.url.value) {
        draft.value = data
        source.value = data.text
        editingBlockId.value = ''
        ElMessage.success(t('doc_review.draft_saved'))
      }
    } catch (error) {
      ElMessage.error(formatApiError(error, t('doc_review.manual_edit_save_failed'), t))
    } finally {
      if (target === options.url.value) busy.value = false
    }
  }

  function saveBlock(blockId: string, text: string) {
    if (blockId !== editingBlockId.value) return
    return save({ ...draft.value?.docx_edits, [blockId]: text })
  }

  function saveSource() {
    if (dirty.value) return save({})
  }

  function leave() {
    if (dirty.value || editingBlockId.value) confirm.value = 'leave'
    else close()
  }

  async function confirmAction() {
    const action = confirm.value
    const current = draft.value
    const target = options.url.value
    if (!action || busy.value || !current) return
    if (action === 'leave') {
      close()
      return
    }
    if (action === 'publish' && !canPublish.value) {
      confirm.value = null
      return
    }
    busy.value = true
    const state = { base_version_id: current.base_version_id, revision: current.revision }
    try {
      if (action === 'discard') {
        if (current.revision) await api.delete(target, { data: state })
        if (target !== options.url.value) return
        draft.value = null
        close()
      } else {
        const { data } = await api.post<AssetVersion>(`${target}/publish`, state)
        if (target !== options.url.value) return
        draft.value = null
        close()
        ElMessage.success(t('doc_review.draft_published'))
        await options.onPublished(data)
      }
    } catch (error) {
      if (target !== options.url.value) return
      confirm.value = null
      ElMessage.error(formatApiError(error, t('doc_review.draft_action_failed'), t))
    } finally {
      if (target === options.url.value) busy.value = false
    }
  }

  function preventLoss(event: BeforeUnloadEvent) {
    if (dirty.value || editingBlockId.value) event.preventDefault()
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('beforeunload', preventLoss)
    onBeforeUnmount(() => window.removeEventListener('beforeunload', preventLoss))
  }

  return {
    draft, editing, busy, editingBlockId, source, stale, dirty, canPublish, confirm,
    begin, updateSource, saveBlock, saveSource, leave, confirmAction,
  }
}
