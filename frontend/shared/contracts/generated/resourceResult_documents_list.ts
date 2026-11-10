/* Generated from Python contracts. Do not edit. */

export type TaskId = string
export type RootRelativePath = string
export type Configured = boolean
export type BaselineAvailable = boolean
export type JsonValue = unknown
export type Plans = {
[k: string]: JsonValue
}[]
export type Specs = {
[k: string]: JsonValue
}[]

export interface DocumentList {
task_id: TaskId
root_relative_path: RootRelativePath
configured: Configured
baseline_available: BaselineAvailable
plans: Plans
specs: Specs
}
