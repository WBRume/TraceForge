import { describe, expect, it } from 'vitest'
import {
  isPathWithinBase,
  joinWorkspacePath,
  slugifyWorkspaceDirName,
} from '../workspacePath'

describe('slugifyWorkspaceDirName', () => {
  it('replaces filesystem-unsafe characters with dashes', () => {
    expect(slugifyWorkspaceDirName('a/b\\c:d*e?f"g<h>i|j')).toBe('a-b-c-d-e-f-g-h-i-j')
  })

  it('trims leading/trailing dashes, dots and whitespace', () => {
    expect(slugifyWorkspaceDirName('  ..-- Billing V8 --.. ')).toBe('Billing V8')
  })

  it('keeps non-ascii characters (e.g. chinese names)', () => {
    expect(slugifyWorkspaceDirName('客户A Billing')).toBe('客户A Billing')
  })

  it('falls back to workspace when nothing is left', () => {
    expect(slugifyWorkspaceDirName('???')).toBe('workspace')
    expect(slugifyWorkspaceDirName('')).toBe('workspace')
  })
})

describe('joinWorkspacePath', () => {
  it('joins windows-style segments with backslash', () => {
    expect(joinWorkspacePath('D:\\sdd', 'workspace', 'Billing')).toBe('D:\\sdd\\workspace\\Billing')
  })

  it('joins posix-style segments with slash', () => {
    expect(joinWorkspacePath('/srv/sdd', 'workspace', 'Billing')).toBe('/srv/sdd/workspace/Billing')
  })

  it('trims redundant separators', () => {
    expect(joinWorkspacePath('D:\\sdd\\', '\\workspace\\', '\\ws\\')).toBe(
      'D:\\sdd\\workspace\\ws'
    )
  })

  it('returns empty string without input', () => {
    expect(joinWorkspacePath('', '')).toBe('')
  })
})

describe('isPathWithinBase', () => {
  it('accepts paths inside the base (windows)', () => {
    expect(isPathWithinBase('D:\\sdd\\workspace\\ws-a', 'D:\\sdd\\workspace')).toBe(true)
    expect(isPathWithinBase('D:\\sdd\\workspace', 'D:\\sdd\\workspace')).toBe(true)
    expect(isPathWithinBase('D:\\sdd\\workspace\\a\\b', 'D:\\sdd\\workspace')).toBe(true)
  })

  it('rejects paths outside the base (windows)', () => {
    expect(isPathWithinBase('D:\\other\\workspace\\ws', 'D:\\sdd\\workspace')).toBe(false)
    // 前缀相同但目录名不同（workspace-evil 不是 workspace 子目录）
    expect(isPathWithinBase('D:\\sdd\\workspace-evil\\ws', 'D:\\sdd\\workspace')).toBe(false)
    expect(isPathWithinBase('D:\\sdd\\ws', 'D:\\sdd\\workspace')).toBe(false)
  })

  it('is case-insensitive for windows drive paths', () => {
    expect(isPathWithinBase('D:\\SDD\\WORKSPACE\\ws', 'd:\\sdd\\workspace')).toBe(true)
  })

  it('accepts paths inside the base (posix)', () => {
    expect(isPathWithinBase('/srv/sdd/workspace/ws', '/srv/sdd/workspace')).toBe(true)
    expect(isPathWithinBase('/srv/sdd/other', '/srv/sdd/workspace')).toBe(false)
  })

  it('resolves dot segments', () => {
    expect(isPathWithinBase('D:\\sdd\\workspace\\..\\workspace\\ws', 'D:\\sdd\\workspace')).toBe(
      true
    )
    expect(isPathWithinBase('D:\\sdd\\workspace\\..\\other', 'D:\\sdd\\workspace')).toBe(false)
  })

  it('allows everything when base is empty', () => {
    expect(isPathWithinBase('C:\\anything', '')).toBe(true)
  })
})
