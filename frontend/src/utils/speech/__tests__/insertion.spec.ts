import { describe, expect, it } from 'vitest'
import { SpeechInsertion } from '../insertion'

describe('dictation in the input field', () => {
  it('replaces selected text and corrects interim text in place, retaining the suffix', () => {
    const insertion = new SpeechInsertion('前文旧内容后文', 2, 5)
    expect(insertion.update('前文旧内容后文', '你好')).toEqual({ value: '前文你好后文', caret: 4 })
    expect(insertion.update('前文你好后文', '您好。')).toEqual({ value: '前文您好。后文', caret: 5 })
    expect(insertion.update('前文您好。后文', '您好。')?.value).toBe('前文您好。后文')
  })

  it('preserves typing before and after the active speech range', () => {
    const insertion = new SpeechInsertion('前文后文', 2)
    insertion.update('前文后文', '你')
    expect(insertion.rebase('新增前文你后文')).toBe(true)
    expect(insertion.update('新增前文你后文补充', '你好。')?.value).toBe('新增前文你好。后文补充')
  })

  it('lets a manual edit inside recognized text take precedence', () => {
    const insertion = new SpeechInsertion('原文', 2)
    insertion.update('原文', '你好')
    expect(insertion.update('原文您好', '你好。')).toBeUndefined()
  })

  it('follows typing before the first speech result', () => {
    const insertion = new SpeechInsertion('原文', 2)
    expect(insertion.update('原文新增', '语音')?.value).toBe('原文新增语音')
  })
})
