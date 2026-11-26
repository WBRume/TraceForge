import { mount } from '@vue/test-utils'
import { nextTick, reactive } from 'vue'
import { expect, it, vi } from 'vitest'
import type { ChatViewVm } from '@/composables/chat/useChatViewModel'
import SpecSidebar from '../SpecSidebar.vue'

vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('@/composables/useDiagnosisDocs', () => ({ useDiagnosisDocs: () => ({}) }))
vi.mock('@/components/doc-review/DocReviewWorkbench.vue', () => ({
  __esModule: true,
  default: {
    props: ['taskId'],
    template: '<article class="review-probe">{{ taskId }}</article>',
  },
}))

it('opens review only for the selected document and keeps it mounted until the task changes', async () => {
  const vm = reactive({
    route: { params: { wsId: 'workspace' } },
    currentTask: { id: 'first-task' },
    currentTaskHasSpec: true,
    isSpecDrawerAvailable: true,
    isSpecPanelOpen: false,
    isDiagnosisTask: false,
    specDrawerLevel: 0,
    specDrawerTab: 'spec_doc',
  })
  const wrapper = mount(SpecSidebar, {
    props: { vm: vm as unknown as ChatViewVm },
    global: { stubs: { PlanDocsPanel: true } },
  })

  try {
    expect(wrapper.find('.review-probe').exists()).toBe(false)

    vm.isSpecPanelOpen = true
    vm.specDrawerTab = 'plan_docs'
    await nextTick()
    expect(wrapper.find('.review-probe').exists()).toBe(false)

    vm.specDrawerTab = 'spec_doc'
    await nextTick()
    await vi.dynamicImportSettled()
    const review = wrapper.get('.review-probe')
    expect(review.text()).toBe('first-task')

    vm.isSpecPanelOpen = false
    await nextTick()
    expect(review.isVisible()).toBe(false)
    vm.isSpecPanelOpen = true
    await nextTick()
    expect(wrapper.get('.review-probe').element).toBe(review.element)

    vm.isSpecPanelOpen = false
    vm.currentTask = { id: 'second-task' }
    await nextTick()
    expect(wrapper.find('.review-probe').exists()).toBe(false)

    vm.isSpecPanelOpen = true
    await nextTick()
    expect(wrapper.get('.review-probe').text()).toBe('second-task')
  } finally {
    wrapper.unmount()
  }
})
