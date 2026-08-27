import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatTaskListItem from '@/components/chat/ChatTaskListItem.vue'

vi.mock('@/components/DeleteActionButton.vue', () => ({
  default: {
    name: 'DeleteActionButton',
    emits: ['click'],
    template: '<button class="delete-action" @click="$emit(\'click\', $event)">delete</button>',
  },
}))

const task = {
  id: 'task-1',
  name: '定位任务列表标题被状态标签挤压的问题',
  status: 'INTERRUPTED',
  task_type: 'DIAGNOSIS',
  creator_name: 'xfc',
  created_at: '2026-08-27T14:08:58Z',
}

const mountItem = () => mount(ChatTaskListItem, {
  props: { task, active: true, canDelete: true },
  global: {
    mocks: {
      $t: (key: string) => key,
    },
  },
})

describe('ChatTaskListItem', () => {
  it('gives the title its own row and separates task state from metadata', () => {
    const wrapper = mountItem()

    expect(wrapper.find('.task-name').text()).toBe(task.name)
    expect(wrapper.find('.task-state-row').text()).toContain('task_types.diagnosis')
    expect(wrapper.find('.task-state-row').text()).toContain('INTERRUPTED')
    expect(wrapper.find('.task-meta').text()).toContain('xfc')
    expect(wrapper.find('.task-select').attributes('aria-current')).toBe('page')
  })

  it('emits select and delete without selecting again from the delete action', async () => {
    const wrapper = mountItem()

    await wrapper.find('.task-select').trigger('click')
    expect(wrapper.emitted('select')?.[0]).toEqual([task])

    await wrapper.find('.delete-action').trigger('click')
    expect(wrapper.emitted('delete')?.[0]).toEqual([task])
    expect(wrapper.emitted('select')).toHaveLength(1)
  })
})
