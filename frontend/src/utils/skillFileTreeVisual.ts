import type { Component } from 'vue'
import {
  Braces,
  FileArchive,
  FileCode,
  FileCog,
  FileImage,
  FileSpreadsheet,
  FileTerminal,
  FileText,
  FileType,
  Folder,
} from 'lucide-vue-next'

export type SkillTreeTone =
  | 'folder'
  | 'markdown'
  | 'code'
  | 'terminal'
  | 'data'
  | 'sheet'
  | 'image'
  | 'archive'
  | 'config'
  | 'text'
  | 'default'

export type SkillTreeVisual = {
  icon: Component
  tone: SkillTreeTone
  extLabel: string
}

const MARKDOWN_EXT = new Set(['md', 'mdx'])
const CODE_EXT = new Set([
  'py', 'js', 'ts', 'tsx', 'jsx', 'java', 'go', 'rs', 'cpp', 'cc', 'cxx', 'c', 'h', 'hpp',
  'cs', 'rb', 'php', 'swift', 'kt', 'kts', 'scala', 'vue', 'svelte', 'html', 'css', 'scss',
  'less', 'sql', 'r', 'lua',
])
const TERMINAL_EXT = new Set(['sh', 'bash', 'zsh', 'fish', 'ps1', 'bat', 'cmd'])
const DATA_EXT = new Set(['json', 'yaml', 'yml', 'toml', 'ini', 'xml'])
const SHEET_EXT = new Set(['csv', 'tsv', 'xls', 'xlsx'])
const IMAGE_EXT = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico'])
const ARCHIVE_EXT = new Set(['zip', 'rar', '7z', 'tar', 'gz', 'tgz', 'bz2', 'xz'])
const TEXT_EXT = new Set(['txt', 'rst', 'adoc', 'log'])
const CONFIG_NAMES = new Set([
  'dockerfile',
  'makefile',
  '.env',
  '.env.local',
  '.env.example',
  '.gitignore',
  '.gitattributes',
  '.editorconfig',
  'package-lock.json',
  'pnpm-lock.yaml',
  'yarn.lock',
])

const normalizeExtLabel = (ext: string): string => {
  const normalized = String(ext || '').trim().toUpperCase()
  if (!normalized) return 'FILE'
  return normalized.length > 6 ? normalized.slice(0, 6) : normalized
}

const resolveExt = (name: string): string => {
  const normalized = String(name || '').trim().toLowerCase()
  if (!normalized) return ''
  if (normalized.startsWith('.') && normalized.indexOf('.', 1) < 0) return ''
  const lastDot = normalized.lastIndexOf('.')
  if (lastDot <= 0 || lastDot >= normalized.length - 1) return ''
  return normalized.slice(lastDot + 1)
}

const matchVisualByName = (name: string): SkillTreeVisual | null => {
  const normalized = String(name || '').trim().toLowerCase()
  if (!normalized) return null
  if (CONFIG_NAMES.has(normalized)) {
    return { icon: FileCog, tone: 'config', extLabel: 'CFG' }
  }
  return null
}

export const resolveSkillTreeVisual = (
  name: string,
  nodeType: 'file' | 'directory',
): SkillTreeVisual => {
  if (nodeType === 'directory') {
    return {
      icon: Folder,
      tone: 'folder',
      extLabel: 'DIR',
    }
  }

  const byName = matchVisualByName(name)
  if (byName) return byName

  const ext = resolveExt(name)
  const extLabel = normalizeExtLabel(ext)

  if (MARKDOWN_EXT.has(ext)) return { icon: FileText, tone: 'markdown', extLabel: extLabel || 'MD' }
  if (TERMINAL_EXT.has(ext)) return { icon: FileTerminal, tone: 'terminal', extLabel }
  if (CODE_EXT.has(ext)) return { icon: FileCode, tone: 'code', extLabel }
  if (DATA_EXT.has(ext)) return { icon: Braces, tone: 'data', extLabel }
  if (SHEET_EXT.has(ext)) return { icon: FileSpreadsheet, tone: 'sheet', extLabel }
  if (IMAGE_EXT.has(ext)) return { icon: FileImage, tone: 'image', extLabel }
  if (ARCHIVE_EXT.has(ext)) return { icon: FileArchive, tone: 'archive', extLabel }
  if (TEXT_EXT.has(ext)) return { icon: FileType, tone: 'text', extLabel }

  return { icon: FileType, tone: 'default', extLabel }
}
