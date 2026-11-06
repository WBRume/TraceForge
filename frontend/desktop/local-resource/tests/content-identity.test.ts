import { afterEach, beforeEach, describe, expect, test } from 'bun:test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { tmpdir } from 'node:os'
import { checkoutBytes, checkoutForms, contentHash, isBinary, normalizeEol } from '../content-identity'
import { git, hash } from '../filesystem'

let root: string
beforeEach(() => {
  root = fs.mkdtempSync(path.join(tmpdir(), 'tf-content-identity-'))
  git(root, 'init', '-b', 'main'); git(root, 'config', 'user.name', 'Test'); git(root, 'config', 'user.email', 'test@example.com')
  git(root, 'config', 'core.autocrlf', 'false')
})
afterEach(() => { fs.rmSync(root, { recursive: true, force: true }) })

describe('content identity', () => {
  test('ignores line endings but keeps real edits and binary bytes apart', () => {
    expect(contentHash(Buffer.from('a\r\nb\r\n'))).toBe(contentHash(Buffer.from('a\nb\n')))
    expect(contentHash(Buffer.from('a\rb'))).toBe(contentHash(Buffer.from('a\nb')))
    expect(contentHash(Buffer.from('a\nb'))).not.toBe(contentHash(Buffer.from('a\nc')))
    const binary = Buffer.from([0, 255, 13, 10])
    expect(isBinary(binary)).toBe(true)
    expect(normalizeEol(binary)).toEqual(binary)
    expect(contentHash(binary)).not.toBe(contentHash(Buffer.from([0, 255, 10, 10])))
  })
  test('installs the checkout form without losing mixed line endings', () => {
    expect(checkoutBytes(Buffer.from('a\nb\n'), 'crlf')).toEqual(Buffer.from('a\r\nb\r\n'))
    expect(checkoutBytes(Buffer.from('a\r\nb\n'), 'crlf')).toEqual(Buffer.from('a\r\nb\r\n'))
    expect(checkoutBytes(Buffer.from('a\r\nb\n'), 'lf')).toEqual(Buffer.from('a\nb\n'))
    expect(checkoutBytes(Buffer.from('a\r\nb\n'), undefined)).toEqual(Buffer.from('a\r\nb\n'))
    expect(checkoutBytes(Buffer.from([0, 13, 10]), 'crlf')).toEqual(Buffer.from([0, 13, 10]))
    expect(contentHash(checkoutBytes(Buffer.from('a\nb\n'), 'crlf'))).toBe(contentHash(Buffer.from('a\nb\n')))
  })
  test('reuses a raw digest only when normalization leaves bytes unchanged', () => {
    for (const bytes of [Buffer.from('a\nb\n'), Buffer.from('a\r\nb\r\n'), Buffer.from('a\rb'), Buffer.from([0, 13, 10])]) {
      expect(contentHash(bytes, hash(bytes))).toBe(contentHash(bytes))
    }
  })
  test('honors explicit eol attributes and core.autocrlf without guessing', () => {
    fs.writeFileSync(path.join(root, '.gitattributes'), '*.cmd text eol=crlf\n*.lf text eol=lf\n*.bin -text\n')
    expect([...checkoutForms(root, ['start.cmd', 'readme.txt', 'keep.bin', 'notes.lf'])]).toEqual([['notes.lf', 'lf'], ['start.cmd', 'crlf']])
    git(root, 'config', 'core.autocrlf', 'true')
    expect([...checkoutForms(root, ['start.cmd', 'readme.txt', 'keep.bin', 'notes.lf'])]).toEqual([['notes.lf', 'lf'], ['readme.txt', 'crlf'], ['start.cmd', 'crlf']])
    git(root, 'config', 'core.autocrlf', 'false')
    git(root, 'config', 'core.eol', 'crlf')
    expect([...checkoutForms(root, ['readme.txt'])]).toEqual([])
  })
})
