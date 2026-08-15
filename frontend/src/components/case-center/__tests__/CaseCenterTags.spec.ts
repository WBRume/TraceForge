import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

import CaseStatusPill from '@/components/case-center/CaseStatusPill.vue'
import CaseCategoryTag from '@/components/case-center/CaseCategoryTag.vue'
import CasePriorityTag from '@/components/case-center/CasePriorityTag.vue'

describe('CaseCenterTags', () => {
  it('renders status pill with translated label and status class', () => {
    const wrapper = mount(CaseStatusPill, { props: { status: 'PENDING_REVIEW' } })
    expect(wrapper.text()).toBe('case_center.status.PENDING_REVIEW')
    expect(wrapper.classes()).toContain('case-status-pill')
    expect(wrapper.classes()).toContain('case-status-pending_review')
  })

  it('renders category tag with translated label and category class', () => {
    const wrapper = mount(CaseCategoryTag, { props: { category: 'PRODUCT' } })
    expect(wrapper.text()).toBe('case_center.category.PRODUCT')
    expect(wrapper.classes()).toContain('case-cat-product')
  })

  it('renders priority tag with priority class', () => {
    const wrapper = mount(CasePriorityTag, { props: { priority: 'P0' } })
    expect(wrapper.text()).toBe('P0')
    expect(wrapper.classes()).toContain('case-prio-p0')
  })

  it('handles unknown statuses without crashing', () => {
    const wrapper = mount(CaseStatusPill, { props: { status: 'UNKNOWN' } })
    expect(wrapper.classes()).toContain('case-status-unknown')
  })
})
