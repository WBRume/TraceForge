import { computed, reactive, ref, type ComputedRef, type Ref } from 'vue'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import type { SelectionRange, SkillComment, SkillRatingItem, SkillReviewOverview } from './skillEditorTypes'

type TranslateFn = (key: string, params?: Record<string, unknown>) => string

type UseSkillEditorReviewOptions = {
  t: TranslateFn
  actionError: Ref<string>
  isEdit: ComputedRef<boolean>
  isReadOnly: ComputedRef<boolean>
  isDiffMode: ComputedRef<boolean>
  isViewingHistoricalVersion: ComputedRef<boolean>
  skillId: ComputedRef<string | undefined>
  selectedWorkspaceId: Ref<string>
  activeFilePath: Ref<string>
  currentRef: ComputedRef<string>
  isWorktreeRef: ComputedRef<boolean>
  latestVersionId: ComputedRef<string>
  selectedRange: Ref<SelectionRange | null>
  onCommentsUpdated?: () => void
}

const emptyReviewOverview = (): SkillReviewOverview => ({
  average_score: null,
  review_count: 0,
  my_score: null,
  my_note: null,
  can_review: false,
  current_version_no: 0,
})

export function useSkillEditorReview(options: UseSkillEditorReviewOptions) {
  const {
    t,
    actionError,
    isEdit,
    isReadOnly,
    isDiffMode,
    isViewingHistoricalVersion,
    skillId,
    selectedWorkspaceId,
    activeFilePath,
    currentRef,
    isWorktreeRef,
    latestVersionId,
    selectedRange,
    onCommentsUpdated,
  } = options

  const reviewOverview = ref<SkillReviewOverview>(emptyReviewOverview())
  const ratingForm = reactive({ score: 0, note: '' })
  const ratingNotes = ref<SkillRatingItem[]>([])
  const comments = ref<SkillComment[]>([])
  const commentBody = ref('')

  const ratingSaving = ref(false)
  const ratingNotesLoading = ref(false)
  const showRatingNotesModal = ref(false)
  const showRatingNoteError = ref(false)
  const commentSaving = ref(false)

  const canReview = computed(() => (
    isEdit.value
    && reviewOverview.value.can_review
    && !isViewingHistoricalVersion.value
  ))

  const canLineReview = computed(() => (
    canReview.value && isReadOnly.value
  ))

  const canSubmitComment = computed(() => (
    canLineReview.value
    && !isDiffMode.value
    && !!selectedRange.value
    && commentBody.value.trim().length > 0
    && !commentSaving.value
  ))

  const applyDetailReviewState = (data: Record<string, unknown>) => {
    reviewOverview.value = {
      average_score: (data.average_score as number | null) ?? null,
      review_count: Number(data.review_count || 0),
      my_score: (data.my_score as number | null) ?? null,
      my_note: (data.my_note as string | null) ?? null,
      can_review: Boolean(data.can_review),
      current_version_no: Number(data.latest_version_no || 0),
    }
    if (reviewOverview.value.my_score) {
      ratingForm.score = reviewOverview.value.my_score
    }
    if (reviewOverview.value.my_note) {
      ratingForm.note = reviewOverview.value.my_note
    }
  }

  const resetForNewSkill = () => {
    reviewOverview.value = emptyReviewOverview()
    ratingForm.score = 0
    ratingForm.note = ''
    ratingNotes.value = []
    comments.value = []
    commentBody.value = ''
    showRatingNoteError.value = false
    showRatingNotesModal.value = false
  }

  const loadReviewOverview = async () => {
    if (!isEdit.value || !skillId.value || !selectedWorkspaceId.value) return
    try {
      const res = await api.get(`/skills/${skillId.value}/reviews/overview`, {
        params: { workspace_id: selectedWorkspaceId.value },
      })
      reviewOverview.value = res.data
      if (res.data.my_score !== null) {
        ratingForm.score = res.data.my_score
      }
      if (res.data.my_note !== null) {
        ratingForm.note = res.data.my_note
      }
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.review_overview_failed'), t)
    }
  }

  const loadRatingNotes = async () => {
    if (!isEdit.value || !skillId.value || !selectedWorkspaceId.value) return
    ratingNotesLoading.value = true
    try {
      const res = await api.get(`/skills/${skillId.value}/reviews/ratings`, {
        params: { workspace_id: selectedWorkspaceId.value },
      })
      ratingNotes.value = res.data.items || []
      showRatingNotesModal.value = true
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.rating_notes_failed'), t)
    } finally {
      ratingNotesLoading.value = false
    }
  }

  const submitRating = async () => {
    if (!canReview.value || !isEdit.value || !skillId.value || !selectedWorkspaceId.value) return

    showRatingNoteError.value = false
    if (ratingForm.score <= 0) return
    if (!ratingForm.note.trim()) {
      showRatingNoteError.value = true
      return
    }

    ratingSaving.value = true
    try {
      await api.post(`/skills/${skillId.value}/reviews/rating`, {
        score: ratingForm.score,
        note: ratingForm.note.trim() || null,
      }, {
        params: { workspace_id: selectedWorkspaceId.value },
      })
      await loadReviewOverview()
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.rating_failed'), t)
    } finally {
      ratingSaving.value = false
    }
  }

  const loadComments = async () => {
    if (!isEdit.value || !skillId.value || !selectedWorkspaceId.value || !activeFilePath.value) {
      comments.value = []
      onCommentsUpdated?.()
      return
    }

    try {
      const targetVersion = isWorktreeRef.value ? latestVersionId.value : currentRef.value
      const res = await api.get(`/skills/${skillId.value}/reviews/comments`, {
        params: {
          workspace_id: selectedWorkspaceId.value,
          version_id: targetVersion || undefined,
          file_path: activeFilePath.value,
        },
      })
      comments.value = (res.data.items || []).map((item: SkillComment) => ({
        ...item,
        expert_avatar_svg: item.expert_avatar_svg || null,
        char_start: item.char_start === null || item.char_start === undefined ? null : Number(item.char_start),
        char_end: item.char_end === null || item.char_end === undefined ? null : Number(item.char_end),
      })) as SkillComment[]
      onCommentsUpdated?.()
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.comment_load_failed'), t)
    }
  }

  const submitComment = async () => {
    if (!canSubmitComment.value || !selectedRange.value) return
    if (!isEdit.value || !skillId.value || !selectedWorkspaceId.value || !activeFilePath.value) return

    commentSaving.value = true
    try {
      await api.post(`/skills/${skillId.value}/reviews/comments`, {
        version_id: latestVersionId.value || null,
        file_path: activeFilePath.value,
        body: commentBody.value.trim(),
        line_start: selectedRange.value.line_start,
        line_end: selectedRange.value.line_end,
        column_start: selectedRange.value.column_start,
        column_end: selectedRange.value.column_end,
        char_start: selectedRange.value.char_start,
        char_end: selectedRange.value.char_end,
        selected_text: selectedRange.value.selected_text,
      }, {
        params: { workspace_id: selectedWorkspaceId.value },
      })
      selectedRange.value = null
      commentBody.value = ''
      await loadComments()
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.comment_save_failed'), t)
    } finally {
      commentSaving.value = false
    }
  }

  return {
    reviewOverview,
    ratingForm,
    ratingNotes,
    comments,
    commentBody,
    ratingSaving,
    ratingNotesLoading,
    showRatingNotesModal,
    showRatingNoteError,
    commentSaving,
    canReview,
    canLineReview,
    canSubmitComment,
    applyDetailReviewState,
    resetForNewSkill,
    loadReviewOverview,
    loadRatingNotes,
    submitRating,
    loadComments,
    submitComment,
  }
}
