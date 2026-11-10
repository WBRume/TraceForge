/* Generated from Python contracts. Do not edit. */

export type JsonValue = unknown
export type Repositories = {
[k: string]: JsonValue
}[]
export type Status = ("applied" | "conflict")

export interface AppliedPatch {
repositories: Repositories
status: Status
}
