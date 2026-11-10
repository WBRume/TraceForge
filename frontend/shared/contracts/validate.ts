import Ajv2020 from 'ajv/dist/2020'
import addFormats from 'ajv-formats'
import { schemas } from './schemas'

const ajv = new Ajv2020({ strict: false, allErrors: true, coerceTypes: false, useDefaults: false, removeAdditional: false, validateFormats: true })
addFormats(ajv)
const validators = new Map<string, ReturnType<typeof ajv.compile>>()

export const supportsApplicationMessage = (kind: string) => Object.hasOwn(schemas.applicationMessage.discriminator.mapping, kind)

export function parseContract<T = unknown>(name: keyof typeof schemas, value: unknown): T {
  let validate = validators.get(name)
  if (!validate) { validate = ajv.compile(schemas[name]); validators.set(name, validate) }
  if (!validate(value)) throw new Error(`CONTRACT_INVALID:${name}:` + ajv.errorsText(validate.errors?.slice(0, 4)))
  return value as T
}

export function validateResourceResult(kind: string, action: string | undefined, result: unknown) {
  const key = `resourceResult_${kind}${action ? '_' + action : ''}`
  if (!(key in schemas)) throw new Error('UNKNOWN_RESOURCE_RESULT')
  parseContract(key as keyof typeof schemas, result)
}
