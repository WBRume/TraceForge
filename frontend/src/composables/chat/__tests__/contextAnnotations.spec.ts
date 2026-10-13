import { afterEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import { useContextAnnotations } from '../annotations/useContextAnnotations'
import { formatAnnotationMessage, type AnnotationSelection } from '../annotations/contextAnnotations'
import { parseUnifiedDiff, unifiedDiffSelection } from '../annotations/unifiedDiff'
import { readMessageSelection } from '../annotations/messageSelection'
import { useChatSend } from '../session/useChatSend'
import { useChatTerminalController, type ChatTerminalBridge } from '@/composables/chat-terminal/useChatTerminalController'

vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('element-plus', () => ({ ElMessage: { warning: vi.fn(), error: vi.fn(), success: vi.fn() } }))

const scopes: ReturnType<typeof effectScope>[] = []
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); document.body.innerHTML = ''; vi.restoreAllMocks() })
function setup() {
  const scope = effectScope(); scopes.push(scope)
  const task = ref('task-a')
  const annotations = scope.run(() => useContextAnnotations(() => task.value))!
  const selection: AnnotationSelection = {
    source: { kind: 'diff', filePath: 'repo/src/client.ts', side: 'modified', lineStart: 35, lineEnd: 36 },
    selectedText: 'const value = user.name\nreturn value',
  }
  const add = (comment = '这里需改成可选链操作符') => { annotations.select(selection, { x: 10, y: 20 }); annotations.add(comment) }
  const send = vi.fn().mockResolvedValue(true)
  const options: Parameters<typeof useChatSend>[0] = {
    annotations, getWorkspaceId: () => 'workspace', getTaskId: () => task.value,
    task: { getCurrentTask: () => ({ id: task.value }), isTaskPreStart: ref(false), isTaskProvisioning: ref(false), isTaskInterrupted: ref(false), isTerminalStatus: ref(false) },
    submissions: { send, busy: ref(false), current: ref([]) }, messages: { upsert: vi.fn() },
    noteSentTime: vi.fn(), findHitlCard: () => undefined, engine: { engineRunning: ref(false) },
    ws: { isOpen: () => true, sendFrame: vi.fn(() => true), connect: vi.fn() },
    recoverSession: vi.fn(), resumeInterruptedTask: vi.fn(), applyTaskSessionPayload: vi.fn(),
    isUndoing: () => false, isHistoryAnchored: () => false, returnToLatest: vi.fn(), getCreatorMeta: () => ({}), scrollTo: vi.fn(), resolveActionError: vi.fn(),
  }
  const composer = scope.run(() => useChatSend(options))!
  return { task, annotations, add, send, options, composer }
}

describe('context annotations and message submission', () => {
  it('sends a captured quote without requiring or inventing a comment', async () => {
    const { annotations, add, composer, send } = setup()
    add('')
    expect(annotations.items.value).toHaveLength(1)
    await composer.sendChat()
    expect(send.mock.calls[0]![2]).toContain('const value = user.name\nreturn value')
    expect(send.mock.calls[0]![2]).toContain('行号：35–36')
    expect(send.mock.calls[0]![2]).not.toContain('修改意见：')
  })
  it('keeps quotes and comments outside the draft and submits a single combined message', async () => {
    const { annotations, add, composer, send } = setup()
    composer.chatInput.value = '请一起修复'
    add(); add('缺少超时保护')
    expect(composer.chatInput.value).toBe('请一起修复')
    await composer.sendChat()
    expect(send).toHaveBeenCalledTimes(1)
    expect(send.mock.calls[0]![2]).toContain('请一起修复\n\n')
    expect(send.mock.calls[0]![2]).toContain('文件：repo/src/client.ts\n版本：modified（modified）\n行号：35–36')
    expect(send.mock.calls[0]![2]).toContain('缺少超时保护')
    expect(annotations.items.value).toHaveLength(0)
    expect(composer.chatInput.value).toBe('')
  })
  it('can send annotations alone and retains them on a rejected request', async () => {
    const { annotations, add, composer, send } = setup()
    add(); send.mockResolvedValueOnce(false)
    await composer.sendChat()
    expect(annotations.items.value).toHaveLength(1)
    expect(composer.chatInput.value).toBe('')
    await composer.sendChat()
    expect(annotations.items.value).toHaveLength(0)
  })
  it('sends edited comments and excludes deleted annotations', async () => {
    const { annotations, add, composer, send } = setup()
    add('旧意见'); add('删除这个意见')
    annotations.update(annotations.items.value[0]!.id, '修改后的意见')
    annotations.remove(annotations.items.value[1]!.id)
    await composer.sendChat()
    expect(send.mock.calls[0]![2]).toContain('修改后的意见')
    expect(send.mock.calls[0]![2]).not.toMatch(/旧意见|删除这个意见/)
  })
  it('isolates tasks, drops stale selections, and consumes only the submitted snapshot', async () => {
    const { annotations, task, add, composer, send } = setup()
    add('任务 A')
    let accept!: (value: boolean) => void
    send.mockImplementationOnce(() => new Promise(resolve => { accept = resolve }))
    const pending = composer.sendChat()
    task.value = 'task-b'; annotations.add('不能沿用 A 的选择'); expect(annotations.items.value).toHaveLength(0)
    add('任务 B')
    accept(true); await pending
    expect(annotations.items.value[0]?.comment).toBe('任务 B')
    task.value = 'task-a'; expect(annotations.items.value).toHaveLength(0)
  })
  it('preserves annotations added or edited during submission', async () => {
    const { annotations, add, composer, send } = setup()
    add('原意见')
    let accept!: (value: boolean) => void
    send.mockImplementationOnce(() => new Promise(resolve => { accept = resolve }))
    const pending = composer.sendChat()
    annotations.update(annotations.items.value[0]!.id, '新意见'); add('后来添加')
    accept(true); await pending
    expect(annotations.items.value.map(item => item.comment)).toEqual(['新意见', '后来添加'])
  })
  it('retains the package when blocked and leaves it out of unrelated quick actions', async () => {
    const { annotations, add, composer, send, options } = setup()
    add(); options.collaborationBlocked = () => true
    await composer.sendChat(); expect(send).not.toHaveBeenCalled(); expect(annotations.items.value).toHaveLength(1)
    options.collaborationBlocked = () => false
    await composer.sendChatContent('快捷操作')
    expect(send.mock.calls[0]![2]).toBe('快捷操作'); expect(annotations.items.value).toHaveLength(1)
  })
  it('uses the same package when resuming an interrupted task', async () => {
    const { annotations, add, composer, options } = setup()
    add(); options.task.isTaskInterrupted.value = true
    await composer.sendChat()
    expect(options.resumeInterruptedTask).toHaveBeenCalledWith('task-a', expect.objectContaining({ prompt: expect.stringContaining('行号：35–36') }))
    expect(annotations.items.value).toHaveLength(0)
  })
  it('does not submit to a task opened while returning from anchored history', async () => {
    const { annotations, task, add, composer, send, options } = setup()
    add(); options.isHistoryAnchored = () => true
    options.returnToLatest = async () => { task.value = 'task-b' }
    await composer.sendChat()
    expect(send).not.toHaveBeenCalled()
    task.value = 'task-a'; expect(annotations.items.value).toHaveLength(1)
  })
  it('preserves nested code fences in a quote', () => {
    const result = formatAnnotationMessage('', [{ id: '1', source: { kind: 'message', messageId: 'reply-id', startOffset: 4, endOffset: 18 }, selectedText: '```ts\ncode\n```', comment: '方案不正确' }])
    expect(result).toContain('````\n```ts\ncode\n```\n````')
    expect(result).toContain('消息 ID：reply-id')
    expect(result).toContain('文字位置：4–18')
  })
  it('shares annotation-only sending with CLI and keeps annotations out of CLI commands', async () => {
    const { annotations, add } = setup()
    const sendChatContent = vi.fn().mockResolvedValueOnce(false).mockResolvedValue(true)
    const terminal = useChatTerminalController({ annotations, sendChatContent, currentTask: { id: 'task-a' }, engineRunning: false, messages: [], terminalLogs: [], t: (key: string) => key } as unknown as ChatTerminalBridge)
    add()
    terminal.inputValue.value = '/status'; await terminal.submitInput()
    expect(sendChatContent).not.toHaveBeenCalled(); expect(annotations.items.value).toHaveLength(1)
    terminal.inputValue.value = ''; await terminal.submitInput()
    expect(sendChatContent).toHaveBeenCalledWith(expect.stringContaining('行号：35–36'))
    expect(annotations.items.value).toHaveLength(1)
    await terminal.submitInput(); expect(annotations.items.value).toHaveLength(0)
  })
})

const patch = 'diff --git a/src/a.ts b/src/a.ts\n--- a/src/a.ts\n+++ b/src/a.ts\n@@ -35,2 +80,3 @@\n-old()\n+new()\n+guard()\n done()'
describe('diff and message anchors', () => {
  it('uses real hunk coordinates on either side, including mixed selections', () => {
    const lines = parseUnifiedDiff(patch)
    expect(unifiedDiffSelection(lines.slice(4, 5))?.source).toMatchObject({ side: 'original', lineStart: 35, lineEnd: 35 })
    expect(unifiedDiffSelection(lines.slice(5, 7))).toMatchObject({ source: { side: 'modified', lineStart: 80, lineEnd: 81 }, selectedText: 'new()\nguard()' })
    expect(unifiedDiffSelection(lines.slice(4, 8))?.source).toMatchObject({ side: 'unified', lineStart: 80, lineEnd: 82, oldLineStart: 35, oldLineEnd: 36 })
  })
  it('rejects cross-file selections and metadata-only selections', () => {
    expect(unifiedDiffSelection(parseUnifiedDiff(patch + '\n' + patch.replaceAll('src/a.ts', 'src/b.ts')))).toBeNull()
    expect(unifiedDiffSelection(parseUnifiedDiff(patch).slice(0, 4))).toBeNull()
  })
  it('preserves deleted files, spaced paths, and code that starts with diff markers', () => {
    const lines = parseUnifiedDiff('diff --git a/a b.ts b/a b.ts\n--- a/a b.ts\n+++ /dev/null\n@@ -42 +0,0 @@\n--- actual code')
    expect(unifiedDiffSelection(lines)).toMatchObject({ source: { filePath: 'a b.ts', side: 'original', lineStart: 42 }, selectedText: '-- actual code' })
  })
  it('decodes Git octal-quoted UTF-8 paths', () => {
    const path = String.raw`"b/\344\270\255.ts"`
    const lines = parseUnifiedDiff(`diff --git ${path.replace('b/', 'a/')} ${path}\n+++ ${path}\n@@ -0,0 +1 @@\n+code`)
    expect(unifiedDiffSelection(lines)?.source).toMatchObject({ filePath: '中.ts', lineStart: 1 })
  })
  it('anchors repeated message text to the actual selected occurrence and rejects cross-message ranges', () => {
    document.body.innerHTML = '<div id="message"><div class="msg-content">重复文字，重复文字</div></div><div id="other">其他消息</div>'
    const root = document.getElementById('message')!
    const text = root.querySelector('.msg-content')!.firstChild!
    const range = document.createRange(); range.setStart(text, 5); range.setEnd(text, 9)
    range.getBoundingClientRect = vi.fn(() => ({ left: 20, bottom: 40 } as DOMRect))
    window.getSelection()!.removeAllRanges(); window.getSelection()!.addRange(range)
    expect(readMessageSelection(root, 'message-id')).toMatchObject({ selectedText: '重复文字', source: { startOffset: 5, endOffset: 9, messageId: 'message-id' } })
    range.setEnd(document.getElementById('other')!.firstChild!, 2)
    expect(readMessageSelection(root, 'message-id')).toBeNull()
  })
})
