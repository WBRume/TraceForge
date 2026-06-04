export type SkillDimension = 'GLOBAL' | 'WORKSPACE'

export type ContentViewMode = 'edit' | 'diff'

export type SkillFileNode = {
  path: string
  name: string
  node_type: 'file' | 'directory'
  children: SkillFileNode[]
}

export type SkillNodeType = 'file' | 'directory'

export type SkillVersion = {
  id: string
  version_no: number
  creator_id: string
  creator_display_name?: string | null
  created_at: string
  change_note?: string | null
}

export type SkillDiffFile = {
  status: string
  path: string
  old_path?: string | null
  is_binary: boolean
  additions?: number | null
  deletions?: number | null
}

export type SkillReviewOverview = {
  average_score: number | null
  review_count: number
  my_score: number | null
  my_note: string | null
  can_review: boolean
  current_version_no: number
}

export type SkillRatingItem = {
  id: string
  expert_user_id: string
  expert_display_name: string | null
  expert_avatar_svg: string | null
  score: number
  note: string | null
  version_no: number | null
  created_at: string
  updated_at: string | null
}

export type SkillComment = {
  id: string
  skill_id: string
  workspace_id: string
  version_id: string
  expert_user_id: string
  expert_display_name: string | null
  expert_avatar_svg: string | null
  file_path: string
  body: string
  selected_text: string | null
  line_start: number
  line_end: number
  column_start: number
  column_end: number
  char_start: number | null
  char_end: number | null
  created_at: string
}

export type SelectionRange = {
  line_start: number
  line_end: number
  column_start: number
  column_end: number
  char_start: number
  char_end: number
  selected_text: string
}

export type InlineComposerPosition = {
  top: number
  left: number
  maxWidth: number
  visible: boolean
}

export type ReviewerGroup = {
  userId: string
  displayName: string
  avatarSvg: string | null
  colorIndex: number
  comments: SkillComment[]
}

export type LineReviewAnchor = {
  line: number
  reviewers: ReviewerGroup[]
}

export type LineAvatarSlot = {
  line: number
  top: number
  left: number
  rowWidth: number
  primaryReviewer: ReviewerGroup
  stackReviewers: ReviewerGroup[]
  totalCommentCount: number
}

export type AvatarPopoverState = {
  visible: boolean
  line: number
  userId: string
  top: number
  left: number
}

export type SkillMetaSnapshot = {
  name: string
  description: string
  dimension: SkillDimension
  workspaceId: string
  entryFilePath: string
}
