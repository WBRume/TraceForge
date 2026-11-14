/* Generated from Python contracts. Do not edit. */

export type ContractVersion = 2
export type CommandId = string
export type Outcome = ("accepted" | "applied")
export type Ok = boolean
export type Action = ("stop" | "retry")
export type Source = ("provision" | "api_mock" | "bootstrap" | "skill_analysis" | "agent")
export type JobId = string
export type Message = (string | null)
export type NewJobId = (string | null)

export interface QueueJobActionResponse {
contract_version: ContractVersion
command_id: CommandId
outcome: Outcome
ok?: Ok
action: Action
source: Source
job_id: JobId
message?: Message
new_job_id?: NewJobId
}
