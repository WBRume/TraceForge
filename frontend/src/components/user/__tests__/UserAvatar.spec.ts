import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import UserAvatar from '@/components/user/UserAvatar.vue'
import { getApiServerUrl } from '@/utils/api'

const legacyAvatarSvg = (color: string) => (
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
  + '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
  + `<stop offset="0%" stop-color="${color}"/>`
  + '</linearGradient></defs>'
  + '<rect width="64" height="64" fill="url(#bg)"/>'
  + '<text>T</text>'
  + '</svg>'
)

const mountAvatar = (color: string) => mount(UserAvatar, {
  props: { displayName: 'test', avatarSvg: legacyAvatarSvg(color) },
})

const renderedSvg = (wrapper: ReturnType<typeof mountAvatar>) =>
  wrapper.find('.avatar-svg').element.innerHTML
const idOf = (html: string) => html.match(/<linearGradient id="([^"]+)"/i)?.[1]

describe('UserAvatar', () => {
  it('scopes duplicated svg ids per instance so gradients do not leak between avatars', () => {
    const firstId = idOf(renderedSvg(mountAvatar('#8b5cf6')))
    const secondId = idOf(renderedSvg(mountAvatar('#22c55e')))

    expect(firstId).toBeDefined()
    expect(secondId).toBeDefined()
    expect(firstId).not.toBe(secondId)
  })

  it('rewrites internal references to the scoped ids', () => {
    const html = renderedSvg(mountAvatar('#8b5cf6'))
    const gradientId = idOf(html)

    expect(gradientId).not.toBe('bg')
    expect(html).toContain(`url(#${gradientId})`)
    expect(html).not.toContain('url(#bg)')
  })

  it('loads a local photo from the configured backend and falls back when it fails', async () => {
    const path = '/api/auth/avatars/u1/photo.webp'
    const wrapper = mount(UserAvatar, { props: { displayName: 'Alice', avatarUrl: path } })
    expect(wrapper.get('img').attributes('src')).toBe(`${getApiServerUrl()}${path}`)

    await wrapper.get('img').trigger('error')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toBe('A')

    await wrapper.setProps({ avatarUrl: path.replace('photo', 'new-photo') })
    expect(wrapper.get('img').attributes('src')).toContain('new-photo.webp')
    wrapper.unmount()
  })

  it('shows a saved vector avatar as an image with the original crop around it', () => {
    const path = '/api/auth/avatars/u1/vector.svg'
    const wrapper = mount(UserAvatar, { props: { displayName: 'Alice', avatarUrl: `${path}#crop=120,80,32,12,40` } })
    const image = wrapper.get('img')
    expect(image.attributes('src')).toBe(`${getApiServerUrl()}${path}`)
    expect(image.attributes('style')).toContain('width: 300%')
    expect(image.attributes('style')).toContain('height: 200%')
    expect(image.attributes('style')).toContain('left: -80%')
    expect(image.attributes('style')).toContain('top: -30%')
    expect(wrapper.find('.avatar-svg').exists()).toBe(false)
    wrapper.unmount()
  })
})
