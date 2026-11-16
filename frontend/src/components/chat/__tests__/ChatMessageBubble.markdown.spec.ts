import { mount } from '@vue/test-utils'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import i18n from '@/i18n'
import ChatMessageBubble from '../ChatMessageBubble.vue'
import markdownFixture from './fixtures/message.md?raw'

function bubbleProps(role: 'user' | 'assistant' | 'system', content: string, streaming = false) {
  return {
    msg: { id: `markdown-${role}`, role, content, message_type: 'text', streaming },
    vm: {
      messageAuthorLabel: () => role,
      formatMessageTime: () => '10:00',
      isMessageWorkspaceExpert: () => false,
      isMessageFromCurrentUser: () => role === 'user',
      canMarkMessageAsDecision: () => false,
    },
  }
}

function mountBubble(role: 'user' | 'assistant' | 'system', content: string, streaming = false) {
  return mount(ChatMessageBubble, {
    props: bubbleProps(role, content, streaming),
    global: { plugins: [i18n] },
  })
}

describe('task chat Markdown', () => {
  it.each(['user', 'assistant'] as const)('renders CommonMark and GFM inside the %s bubble', role => {
    const wrapper = mountBubble(role, markdownFixture)
    const body = wrapper.get('.msg-content')
    expect(body.findAll('h1,h2,h3,h4,h5,h6').slice(0, 7).map(node => node.text())).toEqual([
      'Markdown 渲染验收', '二级标题', '三级标题', '四级标题', '五级标题', '六级标题', 'Setext 标题',
    ])
    expect(body.get('strong').text()).toBe('粗体')
    expect(body.get('em').text()).toBe('斜体')
    expect(body.get('em strong').text()).toBe('粗斜体')
    expect(body.get('del').text()).toBe('删除线')
    expect(body.get('p > code').text()).toBe('a < b')
    expect(body.get('p').text()).toContain('转义 *星号*，实体 &。')
    expect(body.find('p br').exists()).toBe(true)
    expect(body.get('blockquote blockquote').text()).toBe('内层引用含 强调。')
    expect(body.get('ol').attributes('start')).toBe('3')
    expect(body.get('ol li > ul > li').text()).toBe('无序子项')
    expect(body.findAll<HTMLInputElement>('input[type=checkbox]').map(node => [node.element.disabled, node.element.checked]))
      .toEqual([[true, true], [true, false]])
    expect(body.find('hr').exists()).toBe(true)
    expect(body.findAll('pre code')[0].text()).toContain("'<tag> **not bold**'")
    expect(body.get('pre code.language-text').text()).toBe('波浪号围栏')
    expect(body.findAll('pre code')[2].text()).toBe('缩进代码块')
    expect(body.findAll('th').map(node => node.attributes('align'))).toEqual(['left', 'center', 'right'])
    expect(body.get('td').text()).toBe('a | b')
    const primaryLink = body.get('a[title="链接标题"]')
    expect(primaryLink.attributes('href')).toBe('https://example.com')
    expect(primaryLink.attributes('target')).toBe('_blank')
    expect(primaryLink.attributes('rel')).toBe('noopener noreferrer')
    for (const href of ['/docs', 'https://example.com/docs', 'https://example.org', 'https://example.net', 'mailto:team@example.com']) {
      expect(body.find(`a[href="${href}"]`).exists()).toBe(true)
    }
    expect(body.get('img[alt="TraceForge 图标"]').attributes('src')).toBe('/favicon.svg')
    expect(body.findAll('a[data-footnote-ref]')).toHaveLength(2)
    expect(body.get('.footnotes li em').text()).toBe('斜体')
    expect(body.findAll('a[data-footnote-backref]')).toHaveLength(2)
    expect(body.find('[data-markdown-example]').exists()).toBe(false)
    expect(body.text()).toContain('<b data-markdown-example="literal">原样标签</b>')
    wrapper.unmount()
  })

  it('re-renders one streaming bubble as Markdown blocks arrive', async () => {
    const wrapper = mountBubble('assistant', '# 第一段\n\n```ts\nconst n', true)
    expect(wrapper.attributes('aria-busy')).toBe('true')
    expect(wrapper.get('h1').text()).toBe('第一段')
    expect(wrapper.get('pre code').text()).toBe('const n')

    const done = '# 第一段\n\n```ts\nconst n = 1\n```\n\n**第二段**'
    await wrapper.setProps({ msg: { ...wrapper.props('msg'), content: done, streaming: false } })
    expect(wrapper.attributes('data-message-id')).toBe('markdown-assistant')
    expect(wrapper.attributes('aria-busy')).toBeUndefined()
    expect(wrapper.get('pre code').text()).toBe('const n = 1')
    expect(wrapper.get('strong').text()).toBe('第二段')
    wrapper.unmount()
  })

  it('treats unsafe URLs and HTML as inert content', () => {
    const wrapper = mountBubble('assistant', [
      '<img src="/logo" onerror="void(0)">',
      '',
      '[unsafe](javascript:void%280%29) [local](file:///example.md) ![inert](data:text/html,example)',
    ].join('\n'))
    const body = wrapper.get('.msg-content')
    expect(body.text()).toContain('<img src="/logo" onerror="void(0)">')
    expect(body.find('[onerror]').exists()).toBe(false)
    expect(body.find('a[href], img[src]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('generates distinct footnote targets for repeated messages', () => {
    const wrapper = mount({
      render: () => h('div', [
        h(ChatMessageBubble, bubbleProps('user', markdownFixture)),
        h(ChatMessageBubble, bubbleProps('assistant', markdownFixture)),
      ]),
    }, { global: { plugins: [i18n] } })
    const ids = wrapper.findAll('.message-markdown').map(bubble => {
      const reference = bubble.get('a[data-footnote-ref]')
      const target = bubble.get('.footnotes li').attributes('id')
      expect(reference.attributes('href')).toBe(`#${target}`)
      expect(reference.attributes('aria-describedby')).toBe(bubble.get('.footnotes h2').attributes('id'))
      return target
    })
    expect(ids).toHaveLength(2)
    expect(ids[0]).not.toBe(ids[1])
    wrapper.unmount()
  })

  it('renders both hard-break forms without adding a second newline', () => {
    const wrapper = mountBubble('user', '第一行  \r\n第二行\\\r\n第三行')
    const paragraph = wrapper.get('.msg-content p').element
    expect([...paragraph.childNodes].map(node => node.nodeName === 'BR' ? 'BR' : node.textContent))
      .toEqual(['第一行', 'BR', '第二行', 'BR', '第三行'])
    wrapper.unmount()
  })

  it('handles both GFM strikethrough delimiters', () => {
    const wrapper = mountBubble('user', '~单波浪号~ 与 ~~双波浪号~~')
    expect(wrapper.findAll('del').map(node => node.text())).toEqual(['单波浪号', '双波浪号'])
    wrapper.unmount()
  })

  it('copies the source and preserves plain rendering for system messages', async () => {
    const source = '**带格式的正文**\n\n- 列表'
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const user = mountBubble('user', source)
    const system = mountBubble('system', source)
    try {
      await user.get('.message-copy-btn').trigger('click')
      expect(writeText).toHaveBeenCalledWith(source)
      expect(system.get('.msg-content').text()).toBe(source)
      expect(system.find('strong, ul').exists()).toBe(false)
    } finally {
      user.unmount()
      system.unmount()
      vi.unstubAllGlobals()
    }
  })
})
