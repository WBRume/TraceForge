/* Generated from Python contracts. Do not edit. */

export type ContractVersion = 2
export type OperationId = string
export type ResourceId = string
export type TaskId = string
export type Kind = ("initialize" | "skills" | "documents" | "snapshot" | "provision" | "materialize" | "provider_fork" | "release" | "repository_details" | "generate_patch" | "apply_patch")
export type State = ("RUNNING" | "SUCCEEDED" | "FAILED" | "UNKNOWN")
export type JsonValue = unknown

export interface OperationReceipt {
contract_version: ContractVersion
operation_id: OperationId
resource_id: ResourceId
task_id: TaskId
kind: Kind
state: State
result: JsonValue
}
