import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import TaskStatusIcon from '@/components/chat/TaskStatusIcon.vue'
import { CheckCircle2, Flag } from '@/components/icons'

describe('TaskStatusIcon', () => {
  it('uses a flag for round completion and a check circle for final completion', () => {
    const roundCompleted = mount(TaskStatusIcon, { props: { status: 'ROUND_COMPLETED' } })
    expect(roundCompleted.findComponent(Flag).exists()).toBe(true)
    expect(roundCompleted.findComponent(CheckCircle2).exists()).toBe(false)

    const completed = mount(TaskStatusIcon, { props: { status: 'COMPLETED' } })
    expect(completed.findComponent(Flag).exists()).toBe(false)
    expect(completed.findComponent(CheckCircle2).exists()).toBe(true)
  })
})
