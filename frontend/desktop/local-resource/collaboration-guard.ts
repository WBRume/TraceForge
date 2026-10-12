import * as fs from 'node:fs'
import * as path from 'node:path'
import { fail, readJson, resolved } from './filesystem'

export function rejectManagedWrite(registry: string | undefined, target: string) {
  if (!registry || !fs.existsSync(registry)) return
  const roots = readJson<string[]>(registry)
  const actual = resolved(target)
  for (const root of roots) {
    const relative = path.relative(resolved(root), actual)
    const parent = path.relative(actual, resolved(root))
    if (!relative || (relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative))
      || (parent !== '..' && !parent.startsWith('..' + path.sep) && !path.isAbsolute(parent))) {
      fail('COLLABORATION_MANAGED_DIRECTORY: 此目录由本地协同管理，请在代码协同抽屉处理，旧补丁操作不能写入')
    }
  }
}
