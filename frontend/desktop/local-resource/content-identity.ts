/** Line-ending independent file identity; raw bytes stay the transfer form. */
import { Buffer } from 'node:buffer'
import { gitRaw, hash } from './filesystem'

const BINARY_PROBE = 8000

/** Git's own heuristic: a NUL byte in the leading block makes a file binary. */
export const isBinary = (data: Buffer) => data.subarray(0, BINARY_PROBE).includes(0)

/** Repository form of text: CRLF, CR and LF all become LF. */
export function normalizeEol(data: Buffer): Buffer {
  let pairs = 0, lone = 0
  for (let index = 0; index < data.length; index++) {
    if (data[index] !== 13) continue
    if (data[index + 1] === 10) pairs++
    else lone++
  }
  if (!pairs && !lone) return data
  // A CRLF pair loses one byte; a lone CR is replaced one for one.
  const output = Buffer.allocUnsafe(data.length - pairs)
  let offset = 0
  for (let index = 0; index < data.length; index++) {
    if (data[index] !== 13) { output[offset++] = data[index]!; continue }
    if (data[index + 1] === 10) index++
    output[offset++] = 10
  }
  return output
}

/** Identity of the content: binary bytes as-is, text normalized to LF. */
export const contentHash = (data: Buffer) => hash(isBinary(data) ? data : normalizeEol(data))

export type CheckoutForm = 'lf' | 'crlf'

/** Bytes a checkout of this repository places in the working tree. */
export function checkoutBytes(data: Buffer, form: CheckoutForm | undefined): Buffer {
  if (!form || isBinary(data)) return data
  const normalized = normalizeEol(data)
  if (form === 'lf') return normalized
  let breaks = 0
  for (const byte of normalized) if (byte === 10) breaks++
  if (!breaks) return normalized
  const output = Buffer.allocUnsafe(normalized.length + breaks)
  let offset = 0
  for (const byte of normalized) {
    if (byte === 10) output[offset++] = 13
    output[offset++] = byte
  }
  return output
}

const config = (root: string, key: string) => gitRaw(root, ['config', '--get', key], {}, false).toString().trim().toLowerCase()

/**
 * Checkout form of every text-converted path in this repository.
 *
 * Only explicit conversions are honored: an `eol` attribute, or text files in a
 * repository configured with `core.autocrlf`. Anything else keeps repository
 * bytes, so a Windows checkout without that configuration never rewrites LF
 * files behind the user's back.
 */
export function checkoutForms(root: string, names: string[]): Map<string, CheckoutForm> {
  const scoped = [...new Set(names)].filter(name => !!name).sort()
  const forms = new Map<string, CheckoutForm>()
  if (!scoped.length) return forms
  const raw = gitRaw(root, ['check-attr', '-z', '--stdin', 'text', 'eol'], {}, true, Buffer.from(scoped.join('\0') + '\0')).toString()
  const values = raw.replace(/\0$/, '').split('\0')
  const attributes = new Map<string, { text?: string; eol?: string }>()
  for (let index = 0; index + 2 < values.length; index += 3) {
    const entry = attributes.get(values[index]!) ?? {}
    entry[values[index + 1] as 'text' | 'eol'] = values[index + 2]
    attributes.set(values[index]!, entry)
  }
  const autocrlf = config(root, 'core.autocrlf')
  const defaultText = autocrlf === 'true' || autocrlf === 'input'
  for (const name of scoped) {
    const attribute = attributes.get(name) ?? {}
    const text = attribute.text ?? 'unspecified'
    if (text === 'unset') continue
    if (!(text === 'set' || text === 'auto' || (text === 'unspecified' && defaultText))) continue
    const eol = attribute.eol ?? 'unspecified'
    forms.set(name, eol === 'crlf' || (eol !== 'lf' && eol !== 'crlf' && autocrlf === 'true') ? 'crlf' : 'lf')
  }
  return forms
}
