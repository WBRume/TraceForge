import { computed, nextTick, reactive, ref, shallowRef, watch, type ComputedRef, type Ref } from 'vue'
import { reviewerColor, reviewerColorIndex } from '@/utils/skillReview'
import type * as Monaco from 'monaco-editor'
import type {
  AvatarPopoverState,
  InlineComposerPosition,
  LineAvatarSlot,
  LineReviewAnchor,
  ReviewerGroup,
  SelectionRange,
  SkillComment,
} from './skillEditorTypes'

type UseSkillEditorMonacoOptions = {
  selectedRange: Ref<SelectionRange | null>
  comments: Ref<SkillComment[]>
  commentBody: Ref<string>
  canLineReview: ComputedRef<boolean>
  isDiffMode: ComputedRef<boolean>
  isReadOnly: ComputedRef<boolean>
  switchToEditContentView: () => void
}

export function useSkillEditorMonaco(options: UseSkillEditorMonacoOptions) {
  const {
    selectedRange,
    comments,
    commentBody,
    canLineReview,
    isDiffMode,
    isReadOnly,
    switchToEditContentView,
  } = options

  const AVATAR_RAIL_WIDTH = 64

  const activeCommentId = ref('')
  const isInlineComposerFocused = ref(false)
  const isPointerSelecting = ref(false)
  const lineAvatarSlots = ref<LineAvatarSlot[]>([])
  const avatarPopover = reactive<AvatarPopoverState>({
    visible: false,
    line: 0,
    userId: '',
    top: 0,
    left: 0,
  })
  const inlineComposerPosition = reactive<InlineComposerPosition>({
    top: 0,
    left: 0,
    maxWidth: 480,
    visible: false,
  })

  const editorRef = shallowRef<Monaco.editor.IStandaloneCodeEditor | null>(null)
  const monacoRef = shallowRef<typeof import('monaco-editor') | null>(null)
  const selectionListener = shallowRef<Monaco.IDisposable | null>(null)
  const mouseDownListener = shallowRef<Monaco.IDisposable | null>(null)
  const mouseUpListener = shallowRef<Monaco.IDisposable | null>(null)
  const scrollListener = shallowRef<Monaco.IDisposable | null>(null)
  const layoutListener = shallowRef<Monaco.IDisposable | null>(null)
  const contentListener = shallowRef<Monaco.IDisposable | null>(null)
  const selectionDecorations = shallowRef<Monaco.editor.IEditorDecorationsCollection | null>(null)
  const commentDecorations = shallowRef<Monaco.editor.IEditorDecorationsCollection | null>(null)
  const activeCommentDecorations = shallowRef<Monaco.editor.IEditorDecorationsCollection | null>(null)
  const editorStageRef = ref<HTMLElement | null>(null)
  const avatarPopoverRef = ref<HTMLElement | null>(null)

  const showLineReviewAvatars = computed(() => (
    !isDiffMode.value && comments.value.length > 0
  ))

  const resetInlineCommentComposer = () => {
    inlineComposerPosition.visible = false
    isInlineComposerFocused.value = false
  }

  const clearSelectionDecoration = () => {
    selectionDecorations.value?.set([])
  }

  const clearActiveCommentDecoration = () => {
    activeCommentDecorations.value?.set([])
  }

  const closeAvatarPopover = () => {
    avatarPopover.visible = false
    avatarPopover.line = 0
    avatarPopover.userId = ''
  }

  const clearSelectedRange = () => {
    selectedRange.value = null
    commentBody.value = ''
    clearSelectionDecoration()
    resetInlineCommentComposer()
  }

  const selectionRangeKey = (range: SelectionRange) => (
    `${range.line_start}:${range.char_start}-${range.line_end}:${range.char_end}`
  )

  const toSelectionRange = (
    selection: Monaco.Selection,
    model: Monaco.editor.ITextModel,
  ): SelectionRange | null => {
    const start = selection.getStartPosition()
    const end = selection.getEndPosition()
    const charStart = model.getOffsetAt(start)
    const charEnd = model.getOffsetAt(end)
    if (charStart === charEnd) return null
    return {
      line_start: start.lineNumber,
      line_end: end.lineNumber,
      column_start: start.column,
      column_end: end.column,
      char_start: charStart,
      char_end: charEnd,
      selected_text: model.getValueInRange(selection),
    }
  }

  const updateSelectionDecoration = (range: Monaco.IRange | null) => {
    const monaco = monacoRef.value
    if (!monaco || !selectionDecorations.value || !range) {
      clearSelectionDecoration()
      return
    }
    selectionDecorations.value.set([
      {
        range: new monaco.Range(
          range.startLineNumber,
          range.startColumn,
          range.endLineNumber,
          range.endColumn,
        ),
        options: {
          className: 'skill-selection-highlight',
          inlineClassName: 'skill-selection-inline-highlight',
        },
      },
    ])
  }

  const reviewerDisplayName = (comment: SkillComment) => (
    comment.expert_display_name?.trim() || comment.expert_user_id.slice(0, 8)
  )

  const lineReviewAnchors = computed<LineReviewAnchor[]>(() => {
    const lineMap = new Map<number, Map<string, ReviewerGroup>>()
    comments.value.forEach((comment) => {
      const line = Math.max(1, comment.line_start)
      const reviewersByLine = lineMap.get(line) || new Map<string, ReviewerGroup>()
      if (!lineMap.has(line)) {
        lineMap.set(line, reviewersByLine)
      }
      const key = comment.expert_user_id
      const existing = reviewersByLine.get(key)
      if (existing) {
        existing.comments.push(comment)
        if (!existing.avatarSvg && comment.expert_avatar_svg) {
          existing.avatarSvg = comment.expert_avatar_svg
        }
        return
      }
      reviewersByLine.set(key, {
        userId: key,
        displayName: reviewerDisplayName(comment),
        avatarSvg: comment.expert_avatar_svg || null,
        colorIndex: reviewerColorIndex(key),
        comments: [comment],
      })
    })

    return [...lineMap.entries()]
      .map(([line, reviewers]) => ({
        line,
        reviewers: [...reviewers.values()]
          .map((group) => ({
            ...group,
            comments: [...group.comments].sort((a, b) => (
              new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
            )),
          }))
          .sort((a, b) => {
            if (a.comments.length !== b.comments.length) {
              return b.comments.length - a.comments.length
            }
            const latestA = new Date(a.comments[0]?.created_at || 0).getTime()
            const latestB = new Date(b.comments[0]?.created_at || 0).getTime()
            if (latestA !== latestB) return latestB - latestA
            return a.displayName.localeCompare(b.displayName)
          }),
      }))
      .sort((a, b) => a.line - b.line)
  })

  const popoverLineReviewers = computed(() => {
    if (!avatarPopover.visible || !avatarPopover.line) return []
    return lineReviewAnchors.value.find((entry) => entry.line === avatarPopover.line)?.reviewers || []
  })

  const popoverActiveReviewer = computed(() => (
    popoverLineReviewers.value.find((entry) => entry.userId === avatarPopover.userId)
    || popoverLineReviewers.value[0]
    || null
  ))

  const activePopoverComments = computed(() => (
    popoverActiveReviewer.value?.comments || []
  ))

  const popoverReviewerName = computed(() => popoverActiveReviewer.value?.displayName || '')
  const popoverReviewerAvatarSvg = computed(() => popoverActiveReviewer.value?.avatarSvg || null)
  const popoverReviewerColor = computed(() => (
    popoverActiveReviewer.value?.userId ? reviewerColor(popoverActiveReviewer.value.userId) : ''
  ))

  const resolveCommentRange = (
    comment: SkillComment,
    model: Monaco.editor.ITextModel,
    monaco: typeof import('monaco-editor'),
  ) => {
    const modelLength = model.getValueLength()
    if (comment.char_start !== null && comment.char_end !== null) {
      const startOffset = Math.max(0, Math.min(comment.char_start, modelLength))
      const desiredEnd = Math.max(startOffset + 1, Math.min(comment.char_end, modelLength))
      const endOffset = Math.min(desiredEnd, modelLength)
      if (endOffset > startOffset) {
        const startPosition = model.getPositionAt(startOffset)
        const endPosition = model.getPositionAt(endOffset)
        return new monaco.Range(
          startPosition.lineNumber,
          startPosition.column,
          endPosition.lineNumber,
          endPosition.column,
        )
      }
    }

    const maxLine = model.getLineCount()
    const startLine = Math.max(1, Math.min(comment.line_start, maxLine))
    const endLine = Math.max(startLine, Math.min(comment.line_end, maxLine))
    const safeStartCol = Math.max(1, comment.column_start)
    const safeEndCol = Math.max(comment.column_end, safeStartCol + 1)
    return new monaco.Range(startLine, safeStartCol, endLine, safeEndCol)
  }

  const setActiveComment = (comment: SkillComment | null) => {
    const editor = editorRef.value
    const monaco = monacoRef.value
    const model = editor?.getModel()
    if (!editor || !monaco || !model || !comment) {
      activeCommentId.value = ''
      clearActiveCommentDecoration()
      return
    }
    activeCommentId.value = comment.id
    const range = resolveCommentRange(comment, model, monaco)
    const userClass = `skill-active-user-${reviewerColorIndex(comment.expert_user_id)}`
    activeCommentDecorations.value?.set([
      {
        range,
        options: {
          className: `skill-active-comment-highlight ${userClass}`,
          inlineClassName: `skill-active-comment-inline ${userClass}`,
        },
      },
    ])
  }

  const buildCommentDecorations = () => {
    const editor = editorRef.value
    const monaco = monacoRef.value
    const model = editor?.getModel()
    if (!editor || !monaco || !model) return []

    return comments.value.map((comment) => {
      const maxLine = model.getLineCount()
      const startLine = Math.max(1, Math.min(comment.line_start, maxLine))
      const endLine = Math.max(startLine, Math.min(comment.line_end, maxLine))
      const startCol = Math.max(1, comment.column_start || 1)
      const endCol = Math.max(startCol + 1, comment.column_end || model.getLineMaxColumn(endLine))
      const colorClass = `skill-comment-user-${reviewerColorIndex(comment.expert_user_id)}`
      const activeClass = activeCommentId.value === comment.id ? 'is-active' : ''
      return {
        range: new monaco.Range(startLine, startCol, endLine, endCol),
        options: {
          className: `skill-comment-line-highlight ${colorClass} ${activeClass}`,
          glyphMarginClassName: `skill-comment-glyph-margin ${colorClass}`,
        },
      }
    })
  }

  const refreshCommentDecorations = () => {
    commentDecorations.value?.set(buildCommentDecorations())
  }

  const refreshLineAvatarSlots = () => {
    const editor = editorRef.value
    const monaco = monacoRef.value
    const model = editor?.getModel()
    if (!editor || !monaco || !model || !showLineReviewAvatars.value) {
      lineAvatarSlots.value = []
      return
    }

    const nextSlots: LineAvatarSlot[] = []
    const layout = editor.getLayoutInfo()
    const avatarSize = 18
    const stackOverlap = 6
    const extraBadgeWidth = 24

    lineReviewAnchors.value.forEach((entry) => {
      const line = Math.max(1, Math.min(entry.line, model.getLineCount()))
      const anchor = editor.getScrolledVisiblePosition(new monaco.Position(line, 1))
      if (!anchor) return
      if (anchor.top + anchor.height < 0 || anchor.top > layout.height) return

      const primaryReviewer = entry.reviewers[0]
      if (!primaryReviewer) return
      const stackReviewers = entry.reviewers.slice(0, 3)
      const avatarCount = stackReviewers.length
      const avatarGroupWidth = avatarCount > 0
        ? avatarSize + Math.max(0, avatarCount - 1) * stackOverlap
        : 0
      const rowWidth = avatarGroupWidth + 4 + extraBadgeWidth
      const safeLeft = Math.max(4, AVATAR_RAIL_WIDTH - rowWidth - 6)

      nextSlots.push({
        line,
        top: Math.max(3, anchor.top + (anchor.height - avatarSize) / 2),
        left: safeLeft,
        rowWidth,
        primaryReviewer,
        stackReviewers,
        totalCommentCount: entry.reviewers.reduce((sum, group) => sum + group.comments.length, 0),
      })
    })

    lineAvatarSlots.value = nextSlots
  }

  const syncAvatarPopoverPosition = () => {
    if (!avatarPopover.visible) return
    const stage = editorStageRef.value
    if (!stage) return
    const slot = lineAvatarSlots.value.find((entry) => entry.line === avatarPopover.line)
    if (!slot) {
      closeAvatarPopover()
      return
    }
    const popoverWidth = 320
    const popoverHeight = 280
    const desiredLeft = slot.left + slot.rowWidth + 8
    const desiredTop = slot.top + 16
    avatarPopover.left = Math.max(8, Math.min(desiredLeft, stage.clientWidth - popoverWidth - 8))
    avatarPopover.top = Math.max(8, Math.min(desiredTop, stage.clientHeight - popoverHeight - 8))
  }

  const openReviewerPopover = (slot: LineAvatarSlot, event: MouseEvent) => {
    if (!showLineReviewAvatars.value) return
    clearSelectedRange()
    setActiveComment(null)
    avatarPopover.visible = true
    avatarPopover.line = slot.line
    avatarPopover.userId = slot.primaryReviewer.userId

    const stage = editorStageRef.value
    const trigger = event.currentTarget as HTMLElement | null
    if (stage && trigger) {
      const stageRect = stage.getBoundingClientRect()
      const triggerRect = trigger.getBoundingClientRect()
      const popoverWidth = 320
      const popoverHeight = 280
      const desiredLeft = triggerRect.left - stageRect.left + triggerRect.width + 8
      const desiredTop = triggerRect.top - stageRect.top - 4
      avatarPopover.left = Math.max(8, Math.min(desiredLeft, stage.clientWidth - popoverWidth - 8))
      avatarPopover.top = Math.max(8, Math.min(desiredTop, stage.clientHeight - popoverHeight - 8))
      return
    }
    syncAvatarPopoverPosition()
  }

  const switchPopoverReviewer = (reviewer: ReviewerGroup) => {
    if (!avatarPopover.visible) return
    avatarPopover.userId = reviewer.userId
  }

  const handleEditorStagePointerDown = (event: PointerEvent) => {
    isPointerSelecting.value = true
    inlineComposerPosition.visible = false
    if (!avatarPopover.visible) return
    const target = event.target as HTMLElement | null
    if (!target) return
    if (avatarPopoverRef.value?.contains(target)) return
    if (target.closest('[data-review-avatar="true"]')) return
    closeAvatarPopover()
  }

  const handleDocumentPointerDown = (event: PointerEvent) => {
    const target = event.target as HTMLElement | null
    if (
      target
      && !target.closest('.inline-composer-float')
      && !target.closest('[data-review-avatar="true"]')
      && !target.closest('.review-popover')
    ) {
      isPointerSelecting.value = true
      inlineComposerPosition.visible = false
    }
    if (!avatarPopover.visible) return
    if (!target) return
    if (avatarPopoverRef.value?.contains(target)) return
    if (target.closest('[data-review-avatar="true"]')) return
    closeAvatarPopover()
  }

  const handleDocumentPointerUp = () => {
    if (!isPointerSelecting.value) return
    isPointerSelecting.value = false
    renderInlineCommentComposer()
  }

  const updateInlineComposerPosition = () => {
    const editor = editorRef.value
    const monaco = monacoRef.value
    const range = selectedRange.value
    const model = editor?.getModel()
    if (!editor || !monaco || !range || isDiffMode.value || !canLineReview.value || !model || isPointerSelecting.value) {
      inlineComposerPosition.visible = false
      return
    }

    const stage = editorStageRef.value
    if (!stage) {
      inlineComposerPosition.visible = false
      return
    }

    const line = Math.max(1, Math.min(range.line_end, model.getLineCount()))
    const column = Math.max(1, Math.min(range.column_end, model.getLineMaxColumn(line)))
    const anchor = editor.getScrolledVisiblePosition(new monaco.Position(line, column))
    if (!anchor) {
      inlineComposerPosition.visible = false
      return
    }

    const layout = editor.getLayoutInfo()
    const stageRect = stage.getBoundingClientRect()
    const lineHeight = anchor.height
    const gap = lineHeight * 2 + 12
    const desiredTop = anchor.top + gap
    const minTop = 10
    const maxTop = Math.max(minTop, layout.height - 200)
    inlineComposerPosition.top = Math.min(Math.max(desiredTop, minTop), maxTop)

    const composerWidth = 340
    const anchorAbsLeft = stageRect.left + layout.contentLeft + anchor.left
    const stageRight = stageRect.right
    const spaceRight = stageRight - anchorAbsLeft
    let left = spaceRight >= composerWidth + 16
      ? anchorAbsLeft
      : Math.max(stageRect.left + 12, stageRight - composerWidth - 16)
    left = Math.max(left, stageRect.left + 12)
    inlineComposerPosition.left = left - stageRect.left
    inlineComposerPosition.maxWidth = Math.max(300, stageRect.right - left - 14)
    inlineComposerPosition.visible = true
  }

  const renderInlineCommentComposer = () => {
    if (!selectedRange.value || isDiffMode.value || !canLineReview.value || isPointerSelecting.value) {
      resetInlineCommentComposer()
      return
    }
    nextTick(updateInlineComposerPosition)
  }

  const focusCommentRange = async (
    comment: SkillComment,
    options: { clearEditorSelection?: boolean, selectRange?: boolean } = {},
  ) => {
    if (isDiffMode.value) {
      switchToEditContentView()
      await nextTick()
    }

    const editor = editorRef.value
    const monaco = monacoRef.value
    const model = editor?.getModel()
    if (!editor || !monaco || !model) return

    const clearEditorSelection = options.clearEditorSelection ?? true
    const selectRange = options.selectRange ?? true
    if (clearEditorSelection) {
      clearSelectedRange()
    }

    const range = resolveCommentRange(comment, model, monaco)
    if (selectRange) {
      editor.focus()
      editor.setSelection(range)
      editor.revealRangeInCenter(range)
      if (!isReadOnly.value) {
        updateSelectionDecoration(range)
      }
    } else {
      editor.revealRangeInCenter(range)
    }

    setActiveComment(comment)
    refreshCommentDecorations()
  }

  const pickPopoverComment = async (comment: SkillComment) => {
    await focusCommentRange(comment, {
      clearEditorSelection: true,
      selectRange: false,
    })
  }

  const jumpToComment = (comment: SkillComment) => {
    focusCommentRange(comment).catch(() => {})
  }

  const handleEditorMount = (
    editor: Monaco.editor.IStandaloneCodeEditor,
    monaco: typeof import('monaco-editor'),
  ) => {
    selectionListener.value?.dispose()
    mouseDownListener.value?.dispose()
    mouseUpListener.value?.dispose()
    scrollListener.value?.dispose()
    layoutListener.value?.dispose()
    contentListener.value?.dispose()
    editorRef.value = editor
    monacoRef.value = monaco
    selectionDecorations.value = editor.createDecorationsCollection()
    commentDecorations.value = editor.createDecorationsCollection()
    activeCommentDecorations.value = editor.createDecorationsCollection()

    mouseDownListener.value = editor.onMouseDown(() => {
      isPointerSelecting.value = true
      inlineComposerPosition.visible = false
    })
    mouseUpListener.value = editor.onMouseUp(() => {
      isPointerSelecting.value = false
      renderInlineCommentComposer()
    })

    selectionListener.value = editor.onDidChangeCursorSelection((event) => {
      if (!canLineReview.value || isDiffMode.value) {
        clearSelectedRange()
        return
      }

      const selection = event.selection
      if (selection.isEmpty()) {
        clearSelectedRange()
        return
      }

      const model = editor.getModel()
      if (!model) {
        clearSelectedRange()
        return
      }

      const mapped = toSelectionRange(selection, model)
      if (!mapped) {
        return
      }
      const current = selectedRange.value
      if (current && selectionRangeKey(current) === selectionRangeKey(mapped)) {
        updateSelectionDecoration(selection)
        return
      }
      selectedRange.value = mapped
      updateSelectionDecoration(selection)
    })
    scrollListener.value = editor.onDidScrollChange(() => {
      updateInlineComposerPosition()
      refreshLineAvatarSlots()
      syncAvatarPopoverPosition()
    })
    layoutListener.value = editor.onDidLayoutChange(() => {
      updateInlineComposerPosition()
      refreshLineAvatarSlots()
      syncAvatarPopoverPosition()
    })
    contentListener.value = editor.onDidChangeModelContent(() => {
      updateInlineComposerPosition()
      refreshLineAvatarSlots()
      syncAvatarPopoverPosition()
    })

    refreshCommentDecorations()
    updateInlineComposerPosition()
    refreshLineAvatarSlots()
    syncAvatarPopoverPosition()
  }

  const disposeMonaco = () => {
    selectionListener.value?.dispose()
    mouseDownListener.value?.dispose()
    mouseUpListener.value?.dispose()
    scrollListener.value?.dispose()
    layoutListener.value?.dispose()
    contentListener.value?.dispose()
    clearSelectedRange()
    selectionDecorations.value?.set([])
    commentDecorations.value?.set([])
    activeCommentDecorations.value?.set([])
    closeAvatarPopover()
  }

  watch(() => comments.value, () => {
    refreshCommentDecorations()
    refreshLineAvatarSlots()
    if (activeCommentId.value && !comments.value.some((item) => item.id === activeCommentId.value)) {
      setActiveComment(null)
    }
    if (avatarPopover.visible && activePopoverComments.value.length === 0) {
      closeAvatarPopover()
    }
    syncAvatarPopoverPosition()
  }, { deep: true })

  watch(() => avatarPopover.visible, (visible) => {
    if (!visible) return
    if (!avatarPopover.userId && popoverLineReviewers.value[0]) {
      avatarPopover.userId = popoverLineReviewers.value[0].userId
    }
  })

  watch(() => canLineReview.value, (allowed) => {
    if (!allowed) {
      clearSelectedRange()
    }
  })

  watch(() => selectedRange.value, () => {
    renderInlineCommentComposer()
  })

  watch(() => activeCommentId.value, () => {
    refreshCommentDecorations()
  })

  watch(() => lineReviewAnchors.value, () => {
    if (avatarPopover.visible && avatarPopover.line) {
      const reviewers = lineReviewAnchors.value.find((item) => item.line === avatarPopover.line)?.reviewers || []
      if (reviewers.length === 0) {
        closeAvatarPopover()
        return
      }
      if (!reviewers.some((item) => item.userId === avatarPopover.userId)) {
        avatarPopover.userId = reviewers[0].userId
      }
    }
    refreshLineAvatarSlots()
    syncAvatarPopoverPosition()
  }, { deep: true })

  watch(() => showLineReviewAvatars.value, (visible) => {
    if (!visible) {
      lineAvatarSlots.value = []
      closeAvatarPopover()
      return
    }
    nextTick(() => {
      refreshLineAvatarSlots()
      syncAvatarPopoverPosition()
    })
  })

  watch(() => isDiffMode.value, (diffMode) => {
    if (diffMode) {
      clearSelectedRange()
      closeAvatarPopover()
    }
  })

  return {
    AVATAR_RAIL_WIDTH,
    selectedRange,
    activeCommentId,
    isInlineComposerFocused,
    isPointerSelecting,
    lineAvatarSlots,
    avatarPopover,
    inlineComposerPosition,
    editorRef,
    monacoRef,
    selectionDecorations,
    commentDecorations,
    activeCommentDecorations,
    editorStageRef,
    avatarPopoverRef,
    showLineReviewAvatars,
    lineReviewAnchors,
    popoverLineReviewers,
    activePopoverComments,
    popoverReviewerName,
    popoverReviewerAvatarSvg,
    popoverReviewerColor,
    closeAvatarPopover,
    clearSelectedRange,
    setActiveComment,
    refreshCommentDecorations,
    refreshLineAvatarSlots,
    syncAvatarPopoverPosition,
    openReviewerPopover,
    switchPopoverReviewer,
    handleEditorStagePointerDown,
    handleDocumentPointerDown,
    handleDocumentPointerUp,
    focusCommentRange,
    pickPopoverComment,
    jumpToComment,
    handleEditorMount,
    disposeMonaco,
  }
}
