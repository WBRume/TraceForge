import type { DefaultTreeAdapterTypes } from 'parse5'

export type HtmlAssetResolver = (reference: string, signal: AbortSignal) => Promise<ArrayBuffer | undefined>
type HtmlElement = DefaultTreeAdapterTypes.Element

const framePolicy = [
  "default-src 'none'",
  "script-src 'unsafe-inline' data:",
  "style-src 'unsafe-inline' data:",
  'img-src data: blob:',
  'media-src data: blob:',
  'font-src data: blob:',
  "base-uri 'none'",
  "form-action 'none'",
].join('; ')

const imageTypes: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif',
  webp: 'image/webp', svg: 'image/svg+xml', avif: 'image/avif',
}

function toDataUrl(bytes: ArrayBuffer, type: string) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(new Blob([bytes], { type }))
  })
}

/** Resolve direct HTML asset references before handing the document to an opaque sandbox. */
export async function prepareHtml(bytes: ArrayBuffer, signal: AbortSignal, resolveAsset?: HtmlAssetResolver) {
  const { defaultTreeAdapter, html, parse, serialize } = await import('parse5')
  signal.throwIfAborted()
  const document = parse(new TextDecoder().decode(bytes))
  const elements: HtmlElement[] = []
  function visit(parent: DefaultTreeAdapterTypes.ParentNode) {
    for (const node of parent.childNodes) {
      if (!defaultTreeAdapter.isElementNode(node)) continue
      elements.push(node)
      visit(node)
    }
  }
  visit(document)
  for (const node of elements) {
    if (node.tagName === 'base' || (node.tagName === 'meta' && node.attrs.some(attr => attr.name === 'http-equiv' && attr.value.toLowerCase() === 'refresh'))) {
      defaultTreeAdapter.detachNode(node)
    }
  }
  const head = elements.find(node => node.tagName === 'head')!
  const policy = defaultTreeAdapter.createElement('meta', html.NS.HTML, [
    { name: 'http-equiv', value: 'Content-Security-Policy' },
    { name: 'content', value: framePolicy },
  ])
  if (head.childNodes.length) defaultTreeAdapter.insertBefore(head, policy, head.childNodes[0]!)
  else defaultTreeAdapter.appendChild(head, policy)
  if (resolveAsset) {
    const assets = new Map<string, string>()
    let remaining = 12 * 1024 * 1024
    for (const element of elements) {
      signal.throwIfAborted()
      const stylesheet = element.tagName === 'link' && element.attrs.some(attr => attr.name === 'rel' && attr.value.toLowerCase() === 'stylesheet')
      if (!stylesheet && element.tagName !== 'img' && element.tagName !== 'script') continue
      const attribute = element.attrs.find(attr => attr.name === (stylesheet ? 'href' : 'src'))
      const reference = attribute?.value.trim()
      if (!reference || /^(?:[a-z][a-z0-9+.-]*:|\/\/|#)/i.test(reference)) continue
      const extension = /\.([a-z0-9]+)(?:[?#].*)?$/i.exec(reference)?.[1].toLowerCase() || ''
      const type = element.tagName === 'script' ? 'text/javascript' : stylesheet ? 'text/css' : imageTypes[extension]
      if (!type) continue
      const key = `${type}:${reference}`
      if (!assets.has(key)) {
        if (assets.size >= 32 || remaining <= 0) break
        const data = await resolveAsset(reference, signal).catch(() => undefined)
        if (!data || data.byteLength > remaining) { assets.set(key, ''); continue }
        remaining -= data.byteLength
        assets.set(key, await toDataUrl(data, type))
      }
      const url = assets.get(key)
      if (url && attribute) attribute.value = url
    }
  }
  defaultTreeAdapter.setDocumentType(document, 'html', '', '')
  return serialize(document)
}
