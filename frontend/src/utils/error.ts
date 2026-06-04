import type { AxiosError } from 'axios'

type ApiErrorBody = {
  detail?: unknown
  message?: unknown
}

type ValidationErrorItem = {
  type?: unknown
  msg?: unknown
  loc?: unknown
  ctx?: unknown
}

type Translator = (key: string, params?: Record<string, unknown>) => string

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const toNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

const normalizeField = (loc: unknown): string | null => {
  if (!Array.isArray(loc) || loc.length === 0) {
    return null
  }

  const segments = loc
    .filter((segment): segment is string | number => typeof segment === 'string' || typeof segment === 'number')
    .map(segment => String(segment))
    .filter(segment => segment !== 'body' && segment !== 'query' && segment !== 'path')

  if (segments.length === 0) {
    return null
  }

  return segments.join('.')
}

const localizeField = (field: string, t?: Translator): string => {
  if (!t) {
    return field
  }

  if (field === 'email') {
    return t('auth.errors.fields.email')
  }
  if (field === 'password') {
    return t('auth.errors.fields.password')
  }
  if (field === 'display_name') {
    return t('auth.errors.fields.display_name')
  }

  return field
}

const localizeWorkspaceRawMessage = (message: string, t: Translator): string | null => {
  const projectPathExistsMatch = message.match(
    /project_path already exists, please provide a non-existing path:\s*(.+)$/i
  )
  if (projectPathExistsMatch?.[1]) {
    return t('workspaces.errors.project_path_exists', { path: projectPathExistsMatch[1].trim() })
  }

  const projectPathRootMatch = message.match(/project_path cannot be a filesystem root path:\s*(.+)$/i)
  if (projectPathRootMatch?.[1]) {
    return t('workspaces.errors.project_path_root_not_allowed', { path: projectPathRootMatch[1].trim() })
  }

  const normalized = message.toLowerCase()

  if (normalized.includes('project_path is required when git_repo_url is provided')) {
    return t('workspaces.errors.project_path_required_for_git')
  }

  if (normalized.includes('git_repo_url is required for git workspace')) {
    return t('workspaces.errors.git_repo_url_required')
  }

  if (normalized.includes('project_path parent directory is invalid')) {
    return t('workspaces.errors.project_path_parent_invalid')
  }

  if (normalized.includes('git executable not found in path')) {
    return t('workspaces.errors.git_not_found')
  }

  if (normalized.startsWith('git command timed out:')) {
    return t('workspaces.errors.git_command_timeout')
  }

  if (normalized.startsWith('git command failed:')) {
    return t('workspaces.errors.git_command_failed')
  }

  if (normalized.includes('workspace repository remote does not match configured git_repo_url')) {
    return t('workspaces.errors.repo_remote_mismatch')
  }

  return null
}

const localizeSkillRawMessage = (message: string, t: Translator): string | null => {
  const normalized = message.toLowerCase()

  if (
    normalized.includes('only https github urls are supported')
    || normalized.includes('only github.com public repositories are supported in v1')
    || normalized.includes('github repository url must be https://github.com/<owner>/<repo>')
    || normalized.includes('github repository url must not contain query or fragment')
    || normalized.includes('github repository url contains invalid owner/repo name')
  ) {
    return t('skills.editor.github_error_repo_url')
  }

  if (normalized.includes('failed to clone github repository')) {
    return t('skills.editor.github_error_repo_inaccessible')
  }

  if (normalized.includes('multiple skill directories matched')) {
    return t('skills.editor.github_error_multiple_matches')
  }

  if (normalized.includes('found matching directory but missing root skill.md')) {
    return t('skills.editor.github_error_missing_skill_md')
  }

  if (normalized.includes('not found in repository') && normalized.includes('skill directory')) {
    return t('skills.editor.github_error_not_found')
  }

  if (normalized.includes('skill_name must be a directory name')) {
    return t('skills.editor.github_error_skill_name_invalid')
  }

  return null
}

const localizeRawMessage = (message: string, t?: Translator): string | null => {
  if (!t) {
    return null
  }

  const workspaceMessage = localizeWorkspaceRawMessage(message, t)
  if (workspaceMessage) {
    return workspaceMessage
  }

  const skillMessage = localizeSkillRawMessage(message, t)
  if (skillMessage) {
    return skillMessage
  }

  const normalized = message.toLowerCase()

  if (
    normalized.includes('incorrect email or password')
    || normalized.includes('invalid credentials')
  ) {
    return t('auth.errors.invalid_credentials')
  }

  if (
    normalized.includes('path already exists')
    || (normalized.includes('path') && normalized.includes('already exists'))
    || normalized.includes('file or directory already exists')
  ) {
    return t('skills.editor.path_exists')
  }

  if (
    normalized.includes('already registered')
    || normalized.includes('already been registered')
    || (normalized.includes('email') && normalized.includes('already exists'))
  ) {
    return t('auth.errors.email_exists')
  }

  if (
    normalized.includes('valid email address')
    || (normalized.includes('email') && normalized.includes('not valid'))
  ) {
    return t('auth.errors.email_invalid')
  }

  if (
    normalized.includes('field required')
    || normalized.includes('required field')
  ) {
    return t('auth.errors.required')
  }

  const minMatch = normalized.match(/at least\s+(\d+)/i)
  if (minMatch?.[1]) {
    return t('auth.errors.too_short', { min: minMatch[1] })
  }

  const maxMatch = normalized.match(/at most\s+(\d+)/i)
  if (maxMatch?.[1]) {
    return t('auth.errors.too_long', { max: maxMatch[1] })
  }

  return null
}

const formatValidationItem = (item: unknown, t?: Translator): string | null => {
  if (typeof item === 'string' && item.trim().length > 0) {
    return localizeRawMessage(item.trim(), t) ?? item.trim()
  }

  if (!isRecord(item)) {
    return null
  }

  const { type, msg, loc, ctx } = item as ValidationErrorItem
  if (typeof msg !== 'string' || msg.trim().length === 0) {
    return null
  }

  const fieldPath = normalizeField(loc)
  const fieldKey = fieldPath?.split('.').at(-1)
  const fieldLabel = fieldKey ? localizeField(fieldKey, t) : fieldPath
  const prefix = fieldLabel ? `${fieldLabel}: ` : ''

  if (t && typeof type === 'string') {
    if (type === 'missing' || type === 'value_error.missing') {
      return `${prefix}${t('auth.errors.required')}`
    }

    if (type === 'string_too_short') {
      const minLength = isRecord(ctx) ? toNumber(ctx.min_length) : null
      return minLength
        ? `${prefix}${t('auth.errors.too_short', { min: minLength })}`
        : `${prefix}${t('auth.errors.validation_failed')}`
    }

    if (type === 'string_too_long') {
      const maxLength = isRecord(ctx) ? toNumber(ctx.max_length) : null
      return maxLength
        ? `${prefix}${t('auth.errors.too_long', { max: maxLength })}`
        : `${prefix}${t('auth.errors.validation_failed')}`
    }

    if (type.startsWith('value_error') && fieldKey === 'email') {
      return `${prefix}${t('auth.errors.email_invalid')}`
    }
  }

  const localizedMsg = localizeRawMessage(msg, t)
  return fieldLabel
    ? `${fieldLabel}: ${localizedMsg ?? msg}`
    : (localizedMsg ?? msg)
}

const formatDetail = (detail: unknown, t?: Translator): string | null => {
  if (typeof detail === 'string' && detail.trim().length > 0) {
    return localizeRawMessage(detail, t) ?? detail
  }

  if (Array.isArray(detail)) {
    const lines = detail
      .map(item => formatValidationItem(item, t))
      .filter((line): line is string => Boolean(line))

    if (lines.length > 0) {
      return lines.join('\n')
    }
  }

  if (isRecord(detail)) {
    const message = detail.message
    if (typeof message === 'string' && message.trim().length > 0) {
      return message
    }
  }

  return null
}

export const formatApiError = (error: unknown, fallback: string, t?: Translator): string => {
  const axiosError = error as AxiosError<ApiErrorBody>
  const responseData = axiosError.response?.data

  if (responseData) {
    const fromDetail = formatDetail(responseData.detail, t)
    if (fromDetail) {
      return fromDetail
    }

    if (typeof responseData.message === 'string' && responseData.message.trim().length > 0) {
      return localizeRawMessage(responseData.message, t) ?? responseData.message
    }
  }

  if (error instanceof Error && error.message.trim().length > 0) {
    return localizeRawMessage(error.message, t) ?? error.message
  }

  return fallback
}
