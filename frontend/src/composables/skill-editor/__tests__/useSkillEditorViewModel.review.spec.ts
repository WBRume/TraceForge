import { beforeEach, describe, expect, it } from 'vitest'
import { apiMock, flushAll, mockEditModeApi, mountSkillEditorVm, resetHarnessState } from './harness'

describe('useSkillEditorViewModel review and comments', () => {
  beforeEach(() => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1' })
  })

  it('blocks rating submit without note and sets showRatingNoteError', async () => {
    mockEditModeApi()
    const { vm, wrapper } = await mountSkillEditorVm()

    vm.ratingForm.score = 4
    vm.ratingForm.note = ''
    apiMock.post.mockClear()

    await vm.submitRating()
    await flushAll()

    expect(vm.showRatingNoteError).toBe(true)
    const ratingCalls = apiMock.post.mock.calls.filter(([url]) => String(url).includes('/reviews/rating'))
    expect(ratingCalls.length).toBe(0)

    wrapper.unmount()
  })

  it('loads comments by version_id + file_path and uses latest version in worktree mode', async () => {
    mockEditModeApi()
    const { vm, wrapper } = await mountSkillEditorVm()

    apiMock.get.mockClear()
    await vm.openFile('SKILL.md')
    await flushAll()

    const commentsCall = apiMock.get.mock.calls.find(([url]) => String(url).includes('/reviews/comments'))
    expect(commentsCall).toBeTruthy()
    const query = (commentsCall?.[1] as { params: { version_id: string, file_path: string } }).params
    expect(query.version_id).toBe('ver-2')
    expect(query.file_path).toBe('SKILL.md')

    wrapper.unmount()
  })

  it('submits comment with line/column/char offsets and resets selection state', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1', readonly: true })
    mockEditModeApi()
    const { vm, wrapper } = await mountSkillEditorVm()

    vm.selectedRange = {
      line_start: 2,
      line_end: 3,
      column_start: 1,
      column_end: 4,
      char_start: 10,
      char_end: 25,
      selected_text: 'demo',
    }
    vm.commentBody = 'Looks good'
    expect(vm.canSubmitComment).toBe(true)

    apiMock.post.mockClear()
    await vm.submitComment()
    await flushAll()

    const commentCall = apiMock.post.mock.calls.find(([url]) => String(url).includes('/reviews/comments'))
    expect(commentCall).toBeTruthy()
    const payload = commentCall?.[1] as {
      version_id: string
      file_path: string
      line_start: number
      line_end: number
      column_start: number
      column_end: number
      char_start: number
      char_end: number
      selected_text: string
      body: string
    }
    expect(payload.version_id).toBe('ver-2')
    expect(payload.file_path).toBe('SKILL.md')
    expect(payload.line_start).toBe(2)
    expect(payload.line_end).toBe(3)
    expect(payload.column_start).toBe(1)
    expect(payload.column_end).toBe(4)
    expect(payload.char_start).toBe(10)
    expect(payload.char_end).toBe(25)
    expect(payload.selected_text).toBe('demo')
    expect(payload.body).toBe('Looks good')

    expect(vm.selectedRange).toBeNull()
    expect(vm.commentBody).toBe('')

    wrapper.unmount()
  })

  it('keeps canSubmitComment false in diff mode or without selection', async () => {
    resetHarnessState({ mode: 'edit', skillId: 'skill-1', workspaceId: 'ws-1', readonly: true })
    mockEditModeApi()
    const { vm, wrapper } = await mountSkillEditorVm()

    vm.selectedRange = null
    vm.commentBody = 'abc'
    expect(vm.canSubmitComment).toBe(false)

    vm.selectedRange = {
      line_start: 1,
      line_end: 1,
      column_start: 1,
      column_end: 2,
      char_start: 0,
      char_end: 1,
      selected_text: 'a',
    }
    vm.contentViewMode = 'diff'
    expect(vm.canSubmitComment).toBe(false)

    wrapper.unmount()
  })
})
