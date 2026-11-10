/* Generated from Python contracts. Do not edit. */

export type TaskId = string
export type TaskRoot = string
export type JsonValue = unknown
export type RepositoriesInput = {
[k: string]: JsonValue
}[]
export type Repositories = {
[k: string]: JsonValue
}[]

export interface Provisioned {
task_id: TaskId
task_root: TaskRoot
repositories_input: RepositoriesInput
repositories: Repositories
}
