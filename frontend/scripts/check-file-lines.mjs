import { execFileSync } from 'node:child_process'
import { readFileSync, statSync } from 'node:fs'
import { basename, extname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const MAX_FILE_LINES = 1500
export const PROJECT_ROOT = fileURLToPath(new URL('../', import.meta.url))
const SOURCE_EXTENSIONS = new Set([
  '.vue', '.ts', '.tsx', '.mts', '.cts', '.js', '.jsx', '.mjs', '.cjs',
  '.css', '.scss', '.sass', '.less', '.html',
])

export function countLines(content) {
  const breaks = content.match(/\r\n|\n|\r/g)?.length ?? 0
  return breaks + Number(content.length > 0 && !/[\r\n]$/.test(content))
}

export function sourceFiles(projectRoot) {
  const output = execFileSync('git', [
    'ls-files', '--cached', '--others', '--exclude-standard', '-z',
  ], { cwd: projectRoot, encoding: 'utf8', windowsHide: true })
  return [...new Set(output.split('\0').filter(Boolean))]
    .sort()
    .filter(name => SOURCE_EXTENSIONS.has(extname(name).toLowerCase()))
    .map(name => join(projectRoot, name))
    .filter(path => {
      try {
        return statSync(path).isFile()
      } catch (error) {
        if (error.code === 'ENOENT') return false
        throw error
      }
    })
}

export function checkFileLines(projectRoot = PROJECT_ROOT) {
  let files
  const violations = []
  try {
    files = sourceFiles(projectRoot)
    for (const path of files) {
      const lines = countLines(readFileSync(path, 'utf8'))
      if (lines > MAX_FILE_LINES) violations.push({ path, lines })
    }
  } catch (error) {
    console.error(`[单文件行数门禁] Vue 项目无法完成检查：${error.message}`)
    return 1
  }

  if (violations.length) {
    console.error(`[单文件行数门禁] Vue 项目检查失败，上限 ${MAX_FILE_LINES} 行。`)
    for (const { path, lines } of violations) {
      const name = `${basename(projectRoot)}/${relative(projectRoot, path).split('\\').join('/')}`
      console.error(`  ${name}: ${lines} 行，超过 ${MAX_FILE_LINES} 行，需要重构。`)
    }
    console.error('请按职责拆分组件、composable 或样式，重构到 1500 行以内后重新运行检查。')
    return 1
  }

  console.log(`[单文件行数门禁] Vue 项目通过：检查 ${files.length} 个源文件，上限 ${MAX_FILE_LINES} 行。`)
  return 0
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = checkFileLines()
}
