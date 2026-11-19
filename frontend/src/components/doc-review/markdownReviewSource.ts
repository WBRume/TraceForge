import type { ElementContent, Root, RootContent } from 'hast'
import { defaultSchema, sanitize } from 'hast-util-sanitize'
import { toHtml } from 'hast-util-to-html'
import { fromMarkdown } from 'mdast-util-from-markdown'
import { gfmFromMarkdown } from 'mdast-util-gfm'
import { toHast } from 'mdast-util-to-hast'
import { gfm } from 'micromark-extension-gfm'
import { decodeString } from 'micromark-util-decode-string'

type Piece = { starts: number[]; ends: number[] }

/** Associate each rendered UTF-16 code unit with its exact span in the source. */
function mapText(source: string, value: string, offset: number, code: boolean): Piece | undefined {
  const starts: number[] = []
  const ends: number[] = []
  const tokenPattern = /\r\n?|\n|\\[!-/:-@[-`{-~]|&(?:#[xX][\da-fA-F]+|#\d+|[a-zA-Z][a-zA-Z\d]*);/y
  let i = 0
  let j = 0
  while (j < value.length && i < source.length) {
    tokenPattern.lastIndex = i
    const match = tokenPattern.exec(source)?.[0]
    const rawToken = match && (!code || /^[\r\n]/.test(match)) ? match : source[i]!
    let rendered = /^[\r\n]/.test(rawToken) && rawToken.length <= 2
      ? (code && value[j] === ' ' ? ' ' : '\n')
      : code ? rawToken : decodeString(rawToken)
    if (!value.startsWith(rendered, j)) {
      // A line inside a list, quote or indented code block can have a source-only prefix.
      if (j === 0 || value[j - 1] === '\n') {
        const prefix = /^[ \t>]+/.exec(source.slice(i))?.[0]
        if (prefix) {
          i += prefix.length
          continue
        }
      }
      rendered = rawToken
      if (!value.startsWith(rendered, j)) return
    }
    for (let k = 0; k < rendered.length; k++) {
      starts.push(offset + i)
      ends.push(offset + i + rawToken.length)
    }
    i += rawToken.length
    j += rendered.length
  }
  if (j === value.length) return { starts, ends }
}

function codeBounds(source: string, start: number, end: number, fenced: boolean): [number, number] {
  const fragment = source.slice(start, end)
  if (!fenced) {
    const ticks = /^`+/.exec(fragment)?.[0].length || 0
    let first = start + ticks
    let last = end - ticks
    const inner = source.slice(first, last)
    if (/^[ \r\n].*[^ \r\n].*[ \r\n]$/s.test(inner)) {
      first += /^\r\n/.test(inner) ? 2 : 1
      last -= /\r\n$/.test(inner) ? 2 : 1
    }
    return [first, last]
  }
  const fence = /^[ \t]*(?:`{3,}|~{3,})[^\r\n]*(?:\r\n|\r|\n)/.exec(fragment)
  return [start + (fence?.[0].length ?? 0), end]
}

export function renderMarkdownReview(source: string) {
  const mdast = fromMarkdown(source, { extensions: [gfm()], mdastExtensions: [gfmFromMarkdown()] })
  // toHast already prefixes generated footnote IDs and their links.
  const tree = sanitize(toHast(mdast), { ...defaultSchema, clobberPrefix: '' }) as Root
  const pieces: Piece[] = []

  function annotate(node: RootContent, inPre = false): RootContent {
    if (node.type !== 'element') return node
    node.children = node.children.map(child => {
      if (child.type !== 'text') return annotate(child, inPre || node.tagName === 'pre') as ElementContent
      if (!child.value) return child
      const code = node.tagName === 'code'
      const position = child.position ?? (code ? node.position : undefined)
      let start = position?.start.offset
      let end = position?.end.offset
      if (start == null || end == null) return child
      if (code) [start, end] = codeBounds(source, start, end, inPre)
      const piece = mapText(source.slice(start, end), child.value, start, code)
      if (!piece) return child
      const index = pieces.push(piece) - 1
      return { type: 'element', tagName: 'span', properties: { dataSourcePiece: index }, children: [child] }
    })
    return node
  }

  tree.children = tree.children.map(node => annotate(node))
  return { html: toHtml(tree), pieces }
}
