import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const source = (relativePath: string) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')
const layoutCss = source('../../styles/chat-view/chat-view-layout.css')
const pinnedHistoryCss = source('../../styles/chat-view/chat-view-pinned-history.css')
const chatMessageBubbleSource = source('../../components/chat/ChatMessageBubble.vue')
const diagnosisResultCardSource = source('../../components/chat/DiagnosisResultCard.vue')
const chatExecutionInputSource = source('../../components/chat/ChatExecutionInput.vue')

function declarations(source: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const matches = [...source.matchAll(new RegExp(`${escaped}\\s*\\{([^}]+)\\}`, 'g'))]
  expect(matches.length, `missing CSS rule for ${selector}`).toBeGreaterThan(0)
  return matches.map(match => String(match[1] || '')).join(' ').replace(/\s+/g, ' ')
}

describe('ChatView diagnosis summary layout containment', () => {
  it('allows the main chat column and its fixed rows to shrink inside the viewport', () => {
    const mainRule = declarations(layoutCss, '.chat-main')
    expect(mainRule).toContain('min-width: 0')
    expect(mainRule).toContain('container-name: chat-main')
    expect(mainRule).toContain('container-type: inline-size')

    const headerRule = declarations(layoutCss, '.chat-header')
    expect(headerRule).toContain('min-width: 0')
    expect(headerRule).toContain('flex-direction: column')
    expect(headerRule).toContain('align-items: stretch')
    expect(declarations(layoutCss, '.header-left')).toContain('min-width: 0')

    const actionsRule = declarations(layoutCss, '.header-actions')
    expect(actionsRule).toContain('overflow-x: auto')
    expect(actionsRule).toContain('width: 100%')
    expect(declarations(layoutCss, '.header-actions > *')).toContain('flex: 0 0 auto')
    expect(declarations(layoutCss, '.header-actions button')).toContain('white-space: nowrap')
    expect(layoutCss).toContain('@container chat-main (max-width: 900px)')
    expect(declarations(pinnedHistoryCss, '.chat-history')).toContain('min-width: 0')
    expect(declarations(chatExecutionInputSource, '.chat-execution-row')).toContain('min-width: 0')
  })

  it('bounds diagnosis result messages even when generated content has unbroken paths', () => {
    expect(chatMessageBubbleSource).toContain("'is-diagnosis-result': isDiagnosisResult")
    expect(declarations(chatMessageBubbleSource, '.message-wrapper.is-diagnosis-result')).toContain('width: min(78%, 720px)')

    const cardRule = declarations(diagnosisResultCardSource, '.diagnosis-card')
    expect(cardRule).toContain('width: 100%')
    expect(cardRule).toContain('max-width: 640px')
    expect(cardRule).toContain('min-width: 0')
    expect(cardRule).toContain('box-sizing: border-box')
    expect(declarations(diagnosisResultCardSource, '.dc-code')).toContain('max-width: 100%')
    expect(declarations(diagnosisResultCardSource, '.dc-item-note')).toContain('overflow-wrap: anywhere')
  })
})
