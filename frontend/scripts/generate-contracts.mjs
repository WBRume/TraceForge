import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { compile } from 'json-schema-to-typescript'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../shared/contracts')
await mkdir(resolve(root, 'generated'), { recursive: true })
const names = []
for (const file of (await readdir(resolve(root, 'schemas'))).sort()) {
  const name = file.replace(/\.json$/, '')
  const schema = JSON.parse(await readFile(resolve(root, 'schemas', file), 'utf8'))
  const types = await compile(schema, name, { bannerComment: '/* Generated from Python contracts. Do not edit. */', additionalProperties: false, maxItems: -1, format: false })
  await writeFile(resolve(root, 'generated', name + '.ts'), types)
  names.push(name)
}
await writeFile(resolve(root, 'schemas.ts'), '/* Generated schema registry. */\n' + names.map(name => `import ${name} from './schemas/${name}.json'`).join('\n') + '\nexport const schemas = { ' + names.join(', ') + ' } as const\n')
