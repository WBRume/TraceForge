import { describe, expect, it } from 'vitest'
import {
  hitlOptionLabel,
  hitlOptionValue,
  statusMessageText,
  statusModelText,
} from '../presenters'

describe('chat cards presenters', () => {
  it('strips the trailing model annotation from status messages', () => {
    expect(statusMessageText('正在执行 (model: gpt-x)')).toBe('正在执行')
    expect(statusMessageText('  正在执行  (MODEL: GPT-X)  ')).toBe('正在执行')
    expect(statusMessageText('无标注消息')).toBe('无标注消息')
    expect(statusMessageText(null)).toBe('')
  })

  it('prefers the explicit model field over the message annotation', () => {
    expect(statusModelText({ model: 'claude-x', message: 'run (model: gpt-y)' })).toBe('claude-x')
    expect(statusModelText({ model: null, message: 'run (model: gpt-y)' })).toBe('gpt-y')
    expect(statusModelText({ model: '', message: 'no annotation' })).toBe('')
    expect(statusModelText(null)).toBe('')
  })

  it('normalizes HITL options given either as objects or plain strings', () => {
    expect(hitlOptionValue({ value: 'v1', label: '选项一' })).toBe('v1')
    expect(hitlOptionValue({ label: '仅标签' })).toBe('仅标签')
    expect(hitlOptionValue('plain')).toBe('plain')
    expect(hitlOptionValue(null)).toBe('')

    expect(hitlOptionLabel({ value: 'v1', label: '选项一' })).toBe('选项一')
    expect(hitlOptionLabel({ value: '仅值' })).toBe('仅值')
    expect(hitlOptionLabel('plain')).toBe('plain')
    expect(hitlOptionLabel(undefined)).toBe('')
  })
})
