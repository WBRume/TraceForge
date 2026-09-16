import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import UserAvatar from '@/components/user/UserAvatar.vue'

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
})
