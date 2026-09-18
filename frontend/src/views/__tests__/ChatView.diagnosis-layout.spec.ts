import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

/**
 * Chat 诊断摘要布局包容性回归测试。
 * ChatView 已拆分为 sections/* 区块组件，本测试按新模块边界锁定：
 * 主列收缩约束、诊断结果卡约束、撤销遮罩/确认流、初始 Prompt 可编辑。
 */
const source = (relativePath: string) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')
const layoutCss = source('../../styles/chat-view/chat-view-layout.css')
const sessionHeaderSource = source('../../components/chat/sections/SessionHeader.vue')
const chatHistoryPanelSource = source('../../components/chat/sections/ChatHistoryPanel.vue')
const taskSidebarSource = source('../../components/chat/sections/TaskSidebar.vue')
const specSidebarSource = source('../../components/chat/sections/spec/SpecSidebar.vue')
const chatMessageBubbleSource = source('../../components/chat/ChatMessageBubble.vue')
const diagnosisResultCardSource = source('../../components/chat/DiagnosisResultCard.vue')
const chatExecutionInputSource = source('../../components/chat/ChatExecutionInput.vue')
const chatViewSource = source('../ChatView.vue')
const chatStartActionsSource = source('../../composables/chat/actions/useTaskStartActions.ts')
const startTaskModalSource = source('../../components/chat/sections/StartTaskModal.vue')
const initializeTaskModalSource = source('../../components/chat/sections/InitializeTaskModal.vue')
const confirmActionModalSource = source('../../components/ConfirmActionModal.vue')

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

    const headerRule = declarations(sessionHeaderSource, '.chat-header')
    expect(headerRule).toContain('min-width: 0')
    expect(headerRule).toContain('flex-direction: column')
    expect(headerRule).toContain('align-items: stretch')
    expect(declarations(sessionHeaderSource, '.header-left')).toContain('min-width: 0')

    const actionsRule = declarations(sessionHeaderSource, '.header-actions')
    expect(actionsRule).toContain('overflow-x: auto')
    expect(actionsRule).toContain('width: 100%')
    expect(declarations(sessionHeaderSource, '.header-actions > *')).toContain('flex: 0 0 auto')
    expect(declarations(sessionHeaderSource, '.header-actions button')).toContain('white-space: nowrap')
    expect(sessionHeaderSource).toContain('@container chat-main (max-width: 900px)')
    expect(declarations(chatHistoryPanelSource, '.chat-history')).toContain('min-width: 0')
    expect(declarations(chatExecutionInputSource, '.chat-execution-row')).toContain('min-width: 0')
  })

  it('keeps the task sidebar and spec drawer constraints inside their section components', () => {
    expect(declarations(taskSidebarSource, '.task-sidebar')).toContain('width: 280px')
    expect(declarations(taskSidebarSource, '.task-filter-select:deep(.select-trigger)')).toContain('height: 32px')

    expect(declarations(specSidebarSource, '.spec-sidebar')).toContain('position: absolute')
    expect(specSidebarSource).toContain('.spec-sidebar.is-open.level-1')
    expect(specSidebarSource).toContain('.spec-body :deep(.doc-review-workbench)')
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

  it('uses the shared message action style and a frosted session-operation overlay', () => {
    expect(chatMessageBubbleSource).toContain('class="message-action-btn message-undo-btn"')
    expect(chatMessageBubbleSource).not.toContain("'is-active': isUndoingMessage")
    expect(chatMessageBubbleSource).toContain('.message-undo-btn:hover:not(:disabled)')
    expect(chatMessageBubbleSource).toContain('#fef3c7')

    const glassRule = declarations(layoutCss, '.chat-main.is-session-busy::after')
    expect(glassRule).toContain('backdrop-filter: blur(6px) saturate(0.88)')
    expect(glassRule).toContain('pointer-events: auto')
    expect(layoutCss).toContain('.chat-main.is-session-busy .chat-header')
    expect(layoutCss).toContain('.session-operation-overlay')
    expect(layoutCss).toContain('.session-operation-progress-ring')
    expect(declarations(layoutCss, '.session-operation-card')).toContain('flex-direction: column')
    expect(declarations(layoutCss, '.session-operation-card')).toContain('background: transparent')
    expect(declarations(layoutCss, '.session-operation-card')).toContain('box-shadow: none')
    const progressRingRule = declarations(layoutCss, '.session-operation-progress-ring')
    expect(progressRingRule).toContain('animation: session-operation-rotator 1.4s linear infinite')
    const progressTrackRule = declarations(layoutCss, '.session-operation-progress-track')
    expect(progressTrackRule).toContain('stroke: var(--color-primary-200, #bae6fd)')
    const progressPathRule = declarations(layoutCss, '.session-operation-progress-path')
    expect(progressPathRule).toContain('stroke-dasharray: 2 98')
    expect(progressPathRule).toContain('animation: session-operation-dash 1.4s ease-in-out infinite')
    expect(layoutCss).toContain('@keyframes session-operation-dash')
    expect(layoutCss).toContain('100% { transform: rotate(360deg); }')
    expect(chatViewSource).toContain('pathLength="100"')
    expect(layoutCss).not.toContain('session-operation-card-glow')
    expect(layoutCss).not.toContain('.session-operation-banner')
  })

  it('routes undo through the shared confirmation modal before calling the view model', () => {
    expect(chatViewSource).toContain('@undo-request="handleUndoRequest"')
    expect(chatViewSource).toContain('<ConfirmActionModal')
    expect(chatViewSource).toContain('class="session-operation-overlay"')
    expect(chatViewSource).toContain('<span class="session-operation-copy">')
    expect(chatViewSource).not.toContain('session-operation-card glass-panel')
    expect(chatViewSource).not.toContain('class="session-operation-banner"')
    expect(chatViewSource).toContain(":title=\"$t('chat.undo.confirm_title')\"")
    expect(chatViewSource).toContain('@confirm="confirmUndoMessage"')

    const confirmBlock = chatViewSource.slice(
      chatViewSource.indexOf('const confirmUndoMessage'),
      chatViewSource.indexOf('const handleStartPreInput'),
    )
    expect(confirmBlock.indexOf('pendingUndoMessage.value = null')).toBeGreaterThan(-1)
    expect(confirmBlock.indexOf('pendingUndoMessage.value = null')).toBeLessThan(
      confirmBlock.indexOf('await rawVm.undoMessage(message)'),
    )
  })

  it('allows editing the initial prompt before starting or initializing a task', () => {
    expect(startTaskModalSource).toContain('v-model="props.vm.startPrompt"')
    expect(initializeTaskModalSource).toContain('v-model="props.vm.initPrompt"')
    expect(chatStartActionsSource).toContain("const startPrompt = ref('')")
    expect(chatStartActionsSource).toContain("const initPrompt = ref('')")
    expect(chatStartActionsSource).toContain('prompt: promptText || undefined')
    expect(chatStartActionsSource).toContain('startPrompt.value = defaultInitialPromptForTask(options.getCurrentTask())')
  })

  it('keeps confirmation modal hover from changing the dialog background', () => {
    expect(confirmActionModalSource).toContain('<div class="modal" :class="toneClass">')
    expect(confirmActionModalSource).not.toContain('class="modal glass-panel"')
  })
})
