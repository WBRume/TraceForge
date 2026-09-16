import { describe, expect, it } from 'vitest'
import { buildAvatarSvg, scopeAvatarSvgIds } from '../avatar'

const gradientIdOf = (svg: string) => svg.match(/<linearGradient id="([^"]+)"/)?.[1]

describe('buildAvatarSvg', () => {
  it('uses a seed based gradient id instead of the shared "bg" id', () => {
    const svg = buildAvatarSvg({ displayName: 'test', email: 'test@example.com', userId: 'u1' })
    const gradientId = gradientIdOf(svg)

    expect(gradientId).toBeDefined()
    expect(gradientId).not.toBe('bg')
    expect(svg).toContain(`url(#${gradientId})`)
    expect(svg).not.toContain('url(#bg)')
  })

  it('gives different users different gradient ids', () => {
    const first = buildAvatarSvg({ displayName: 'test', email: 'test@example.com', userId: 'u1' })
    const second = buildAvatarSvg({ displayName: 'test2', email: 'test2@example.com', userId: 'u2' })

    expect(gradientIdOf(first)).toBeDefined()
    expect(gradientIdOf(second)).toBeDefined()
    expect(gradientIdOf(first)).not.toBe(gradientIdOf(second))
  })

  it('is deterministic for the same user', () => {
    const first = buildAvatarSvg({ displayName: 'test', email: 'test@example.com', userId: 'u1' })
    const second = buildAvatarSvg({ displayName: 'test', email: 'test@example.com', userId: 'u1' })
    expect(first).toBe(second)
  })

  it('applies the unique id to the soft template as well', () => {
    const svg = buildAvatarSvg({
      displayName: 'test',
      email: 'test@example.com',
      userId: 'u1',
      style: 'soft',
    })
    const gradientId = gradientIdOf(svg)

    expect(gradientId).toBeDefined()
    expect(gradientId).not.toBe('bg')
    expect(svg).toContain(`url(#${gradientId})`)
  })
})

describe('scopeAvatarSvgIds', () => {
  const legacySvg = (
    '<svg xmlns="http://www.w3.org/2000/svg">'
    + '<defs><linearGradient id="bg"><stop offset="0%" stop-color="#8b5cf6"/></linearGradient></defs>'
    + '<rect width="64" height="64" fill="url(#bg)"/>'
    + '<use href="#bg"/>'
    + '</svg>'
  )

  it('rewrites ids and internal references to a per-call scope', () => {
    const scoped = scopeAvatarSvgIds(legacySvg)
    const scopedId = gradientIdOf(scoped)

    expect(scopedId).toBeDefined()
    expect(scopedId).not.toBe('bg')
    expect(scoped).toContain(`url(#${scopedId})`)
    expect(scoped).toContain(`href="#${scopedId}"`)
    expect(scoped).not.toContain('url(#bg)')
  })

  it('gives every call a distinct scope', () => {
    expect(scopeAvatarSvgIds(legacySvg)).not.toBe(scopeAvatarSvgIds(legacySvg))
  })

  it('leaves svgs without ids untouched', () => {
    const svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="64" height="64"/></svg>'
    expect(scopeAvatarSvgIds(svg)).toBe(svg)
  })

  it('does not rewrite hex colors that look like an id', () => {
    const svg = (
      '<svg xmlns="http://www.w3.org/2000/svg">'
      + '<defs><linearGradient id="ffffff"/></defs>'
      + '<rect width="64" height="64" fill="#ffffff"/>'
      + '</svg>'
    )
    expect(scopeAvatarSvgIds(svg)).toContain('fill="#ffffff"')
  })
})
