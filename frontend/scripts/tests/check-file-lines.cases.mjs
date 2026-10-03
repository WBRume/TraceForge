import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, unlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

const checkerSource = fileURLToPath(new URL('../check-file-lines.mjs', import.meta.url))

function inProject(run) {
  const repository = mkdtempSync(join(tmpdir(), 'traceforge-vue-lines-'))
  try {
    execFileSync('git', ['init', '-q', repository], { windowsHide: true })
    const project = join(repository, 'frontend')
    const scripts = join(project, 'scripts')
    mkdirSync(scripts, { recursive: true })
    const checker = join(scripts, 'check-file-lines.mjs')
    copyFileSync(checkerSource, checker)
    run({
      repository,
      writeSource(name, content) {
        const path = join(project, name)
        writeFileSync(path, content)
        return path
      },
      gate() {
        return spawnSync(process.execPath, [checker], {
          cwd: repository, encoding: 'utf8', windowsHide: true,
        })
      },
    })
  } finally {
    rmSync(repository, { recursive: true, force: true })
  }
}

test('allows 1500 physical lines with LF/CRLF/CR and an optional final newline', () => {
  inProject(({ writeSource, gate }) => {
    for (const ending of ['\n', '\r\n', '\r']) {
      for (const trailing of [true, false]) {
        writeSource('模块 with spaces.vue', `${'<!-- comment -->'.concat(ending).repeat(1499)}<!-- final -->${trailing ? ending : ''}`)
        const result = gate()
        assert.equal(result.status, 0, result.stderr)
      }
    }
  })
})

test('rejects 1501 lines including blanks, comments, template, script and style', () => {
  inProject(({ writeSource, gate }) => {
    for (const ending of ['\n', '\r\n', '\r']) {
      for (const trailing of [true, false]) {
        const content = ['<template></template>', '<script setup></script>', '<style></style>', ...Array(1498).fill('')].join(ending)
        writeSource('oversized.vue', content + (trailing ? ending : '<!-- final -->'))
        const result = gate()
        assert.equal(result.status, 1)
        assert.match(result.stderr, /frontend\/oversized.vue: 1501 行/)
        assert.match(result.stderr, /需要重构/)
      }
    }
  })
})

test('checks every supported source extension', () => {
  inProject(({ writeSource, gate }) => {
    const extensions = ['vue', 'ts', 'tsx', 'mts', 'cts', 'js', 'jsx', 'mjs', 'cjs', 'css', 'scss', 'sass', 'less', 'html']
    for (const extension of extensions) writeSource(`oversized.${extension}`, '\n'.repeat(1501))
    const result = gate()
    assert.equal(result.status, 1)
    for (const extension of extensions) assert.ok(result.stderr.includes(`frontend/oversized.${extension}: 1501 行`))
  })
})

test('includes tracked and new sources, ignores dependencies and scopes the project', () => {
  inProject(({ repository, writeSource, gate }) => {
    writeFileSync(join(repository, '.gitignore'), 'frontend/ignored.vue\nfrontend/tracked-ignored.ts\n')
    writeSource('tracked-ignored.ts', '\n'.repeat(1501))
    execFileSync('git', ['add', '-f', 'frontend/tracked-ignored.ts'], { cwd: repository, windowsHide: true })
    writeSource('新的模块 with spaces.vue', '\n'.repeat(1501))
    writeSource('ignored.vue', '\n'.repeat(1501))
    writeSource('notes.json', '\n'.repeat(1501))
    const backend = join(repository, 'backend')
    mkdirSync(backend)
    writeFileSync(join(backend, 'unrelated.ts'), '\n'.repeat(1501))
    const result = gate()
    assert.equal(result.status, 1)
    assert.ok(result.stderr.includes('frontend/tracked-ignored.ts: 1501 行'))
    assert.ok(result.stderr.includes('frontend/新的模块 with spaces.vue: 1501 行'))
    assert.ok(!result.stderr.includes('frontend/ignored.vue:'))
    assert.ok(!result.stderr.includes('notes.json'))
    assert.ok(!result.stderr.includes('unrelated.ts'))
  })
})

test('skips deleted tracked files', () => {
  inProject(({ repository, writeSource, gate }) => {
    const path = writeSource('deleted.vue', '\n'.repeat(1501))
    execFileSync('git', ['add', 'frontend/deleted.vue'], { cwd: repository, windowsHide: true })
    unlinkSync(path)
    const result = gate()
    assert.equal(result.status, 0, result.stderr)
  })
})

test('empty files and Unicode line separators use physical line counting', () => {
  inProject(({ writeSource, gate }) => {
    writeSource('empty.vue', '')
    writeSource('unicode.ts', '// 文本\u2028'.repeat(1501))
    const result = gate()
    assert.equal(result.status, 0, result.stderr)
  })
})

test('blocks the gate when the Git inventory is unavailable', () => {
  const directory = mkdtempSync(join(tmpdir(), 'traceforge-no-git-'))
  try {
    const scripts = join(directory, 'scripts')
    mkdirSync(scripts)
    const checker = join(scripts, 'check-file-lines.mjs')
    copyFileSync(checkerSource, checker)
    const result = spawnSync(process.execPath, [checker], { cwd: directory, encoding: 'utf8', windowsHide: true })
    assert.equal(result.status, 1)
    assert.match(result.stderr, /无法完成检查/)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})
