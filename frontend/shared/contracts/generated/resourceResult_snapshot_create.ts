/* Generated from Python contracts. Do not edit. */

export type Root = string
export type JsonValue = unknown

export interface CheckpointCreated {
root: Root
worktree: Worktree
provider: Provider
}
export interface Worktree {
[k: string]: JsonValue
}
export interface Provider {
[k: string]: JsonValue
}
