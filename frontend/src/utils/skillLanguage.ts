const EXTENSION_LANGUAGE_MAP: Record<string, string> = {
  md: 'markdown',
  markdown: 'markdown',
  mdx: 'markdown',
  mkd: 'markdown',
  txt: 'plaintext',
  log: 'plaintext',
  conf: 'ini',
  cfg: 'ini',
  ini: 'ini',
  toml: 'ini',
  env: 'shell',
  py: 'python',
  sh: 'shell',
  bash: 'shell',
  zsh: 'shell',
  fish: 'shell',
  ksh: 'shell',
  bat: 'bat',
  cmd: 'bat',
  ps1: 'powershell',
  psm1: 'powershell',
  psd1: 'powershell',
  js: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  ts: 'typescript',
  mts: 'typescript',
  cts: 'typescript',
  jsx: 'javascript',
  tsx: 'typescript',
  json: 'json',
  json5: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  xml: 'xml',
  html: 'html',
  htm: 'html',
  css: 'css',
  scss: 'scss',
  less: 'less',
  sql: 'sql',
  csv: 'plaintext',
  tsv: 'plaintext',
  dot: 'plaintext',
  j2: 'plaintext',
  jinja: 'plaintext',
  jinja2: 'plaintext',
  tpl: 'plaintext',
  tmpl: 'plaintext',
  mustache: 'plaintext',
  hbs: 'plaintext',
  handlebars: 'plaintext',
  properties: 'ini',
  gitignore: 'plaintext',
  gitattributes: 'plaintext',
  gitmodules: 'ini',
  dockerignore: 'plaintext',
  rst: 'plaintext',
  license: 'plaintext',
}

const FILE_NAME_LANGUAGE_MAP: Record<string, string> = {
  dockerfile: 'dockerfile',
  makefile: 'plaintext',
  'cmakelists.txt': 'plaintext',
  justfile: 'plaintext',
  license: 'plaintext',
  readme: 'markdown',
  changelog: 'markdown',
  contributing: 'markdown',
}

export const resolveSkillFileLanguage = (rawPath: string): string => {
  const normalized = String(rawPath || '').trim().replace(/\\/g, '/')
  if (!normalized) return 'plaintext'

  const lowerPath = normalized.toLowerCase()
  const fileName = lowerPath.split('/').pop() || lowerPath

  if (FILE_NAME_LANGUAGE_MAP[fileName]) {
    return FILE_NAME_LANGUAGE_MAP[fileName]
  }

  if (
    fileName === '.env'
    || fileName.startsWith('.env.')
    || fileName === '.bashrc'
    || fileName === '.zshrc'
    || fileName === '.profile'
  ) {
    return 'shell'
  }

  if (fileName === '.editorconfig' || fileName === '.npmrc') {
    return 'ini'
  }

  const dotIndex = fileName.lastIndexOf('.')
  if (dotIndex <= 0 || dotIndex === fileName.length - 1) {
    return 'plaintext'
  }

  const extension = fileName.slice(dotIndex + 1)
  return EXTENSION_LANGUAGE_MAP[extension] || 'plaintext'
}
