/* Generated from Python contracts. Do not edit. */

export type ApplicationMessage = (ToolUseMessage | ToolResultMessage | ThinkingMessage | ResultMessage | StatusMessage | ChatMessageMessage | LogMessage | JobUpdateMessage | JobDoneMessage)
export type EventType = "tool_use"
export type TaskId = string
export type ToolName = string
export type ToolUseId = string
export type ContractVersion = 2
export type EventType1 = "tool_result"
export type TaskId1 = string
export type ToolUseId1 = string
export type Output = string
export type IsError = boolean
export type Content = {
[k: string]: unknown
}[]
export type ContractVersion1 = 2
export type EventType2 = "thinking"
export type TaskId2 = string
export type Content1 = string
export type Sequence = number
export type Delta = (string | null)
export type Final = boolean
export type ContractVersion2 = 2
export type EventType3 = "result"
export type TaskId3 = string
export type Success = boolean
export type SessionGeneration = (number | null)
export type SessionRevision = (number | null)
export type Result = string
export type JobId = (string | null)
export type DurationMs = (number | null)
export type CostUsd = (number | null)
export type ContractVersion3 = 2
export type EventType4 = "status"
export type TaskId4 = string
export type Status = string
export type SessionGeneration1 = (number | null)
export type SessionRevision1 = (number | null)
export type SubTask = (string | null)
export type Message = string
export type JobId1 = (string | null)
export type Model = (string | null)
export type DurationMs1 = (number | null)
export type CostUsd1 = (number | null)
export type ContractVersion4 = 2
export type EventType5 = "chat_message"
export type TaskId5 = string
export type Role = string
export type Content2 = string
export type MessageType = string
export type Metadata = ({
[k: string]: unknown
} | null)
export type Id = (string | null)
export type ClientMessageId = (string | null)
export type CreatorId = (string | null)
export type CreatorDisplayName = (string | null)
export type CreatorIsWorkspaceExpert = (boolean | null)
export type CreatorAvatarUrl = (string | null)
export type CreatorAvatarSvg = (string | null)
export type CreatedAt = (string | null)
export type SessionTurnId = (string | null)
export type SessionGeneration2 = (number | null)
export type CanUndo = (boolean | null)
export type ReadingItemKey = (string | null)
export type ReadingChangeSeq = (string | null)
export type ContractVersion5 = 2
export type EventType6 = "log"
export type TaskId6 = string
export type Phase = (string | null)
export type LogType = string
export type Content3 = string
export type ContractVersion6 = 2
export type EventType7 = "job_update"
export type Type = ("job_update" | "job_done")
export type ProjectId = string
export type Version = number
export type AttemptCount = number
export type SchemaVersion = 2
export type Kind = string
export type Outcome = ("SUCCESS" | "FAILED" | "CANCELLED")
export type Summary = string
export type Kind1 = string
export type Id1 = string
export type Version1 = (string | null)
export type Artifacts = JobArtifact[]
export type Attempt = number
export type CommittedAt = string
export type Id2 = string
export type ProjectId1 = string
export type CreatorId1 = string
export type JobType = string
export type Status1 = ("PENDING" | "RUNNING" | "WAITING_HITL" | "INTERRUPTED" | "TERMINATING" | "ORPHANED" | "SUCCESS" | "FAILED" | "CANCELLED" | "REVERTED")
export type Progress = number
export type CancelRequested = boolean
export type Message1 = (string | null)
export type JobKind = (string | null)
export type TargetEndpointId = (string | null)
export type SourceUrl = (string | null)
export type EndpointsImported = (number | null)
export type CasesCreated = (number | null)
export type CreatedCount = (number | null)
export type UpdatedCount = (number | null)
export type CancelRequested1 = (boolean | null)
export type CancelRequestedAt = (string | null)
export type Cancelled = (boolean | null)
export type CancelledAt = (string | null)
export type CreatedAt1 = string
export type UpdatedAt = (string | null)
export type StartedAt = (string | null)
export type FinishedAt = (string | null)
export type ContractVersion7 = 2
export type EventType8 = "job_done"
export type ContractVersion8 = 2

export interface ToolUseMessage {
event_type: EventType
payload: WSToolUsePayloadContract
contract_version: ContractVersion
}
export interface WSToolUsePayloadContract {
task_id: TaskId
tool_name: ToolName
tool_input?: ToolInput
tool_use_id: ToolUseId
}
export interface ToolInput {
[k: string]: unknown
}
export interface ToolResultMessage {
event_type: EventType1
payload: WSToolResultPayloadContract
contract_version: ContractVersion1
}
export interface WSToolResultPayloadContract {
task_id: TaskId1
tool_use_id: ToolUseId1
output?: Output
is_error?: IsError
structured_content?: StructuredContent
content?: Content
}
export interface StructuredContent {
[k: string]: unknown
}
export interface ThinkingMessage {
event_type: EventType2
payload: WSThinkingPayloadContract
contract_version: ContractVersion2
}
export interface WSThinkingPayloadContract {
task_id: TaskId2
content: Content1
sequence?: Sequence
delta?: Delta
final?: Final
}
export interface ResultMessage {
event_type: EventType3
payload: WSResultPayloadContract
contract_version: ContractVersion3
}
export interface WSResultPayloadContract {
task_id: TaskId3
success: Success
session_generation?: SessionGeneration
session_revision?: SessionRevision
result?: Result
job_id?: JobId
duration_ms?: DurationMs
cost_usd?: CostUsd
}
export interface StatusMessage {
event_type: EventType4
payload: WSStatusPayloadContract
contract_version: ContractVersion4
}
export interface WSStatusPayloadContract {
task_id: TaskId4
status: Status
session_generation?: SessionGeneration1
session_revision?: SessionRevision1
sub_task?: SubTask
message: Message
job_id?: JobId1
model?: Model
duration_ms?: DurationMs1
cost_usd?: CostUsd1
}
export interface ChatMessageMessage {
event_type: EventType5
payload: WSChatPayloadContract
contract_version: ContractVersion5
}
export interface WSChatPayloadContract {
task_id: TaskId5
role: Role
content: Content2
message_type?: MessageType
metadata?: Metadata
id?: Id
client_message_id?: ClientMessageId
creator_id?: CreatorId
creator_display_name?: CreatorDisplayName
creator_is_workspace_expert?: CreatorIsWorkspaceExpert
creator_avatar_url?: CreatorAvatarUrl
creator_avatar_svg?: CreatorAvatarSvg
created_at?: CreatedAt
session_turn_id?: SessionTurnId
session_generation?: SessionGeneration2
can_undo?: CanUndo
reading_item_key?: ReadingItemKey
reading_change_seq?: ReadingChangeSeq
}
export interface LogMessage {
event_type: EventType6
payload: WSLogPayloadContract
contract_version: ContractVersion6
}
export interface WSLogPayloadContract {
task_id: TaskId6
phase?: Phase
log_type?: LogType
content: Content3
}
export interface JobUpdateMessage {
event_type: EventType7
payload: ApiMockJobEventContract
contract_version: ContractVersion7
}
export interface ApiMockJobEventContract {
type: Type
project_id: ProjectId
job: ApiMockJobResponse
}
export interface ApiMockJobResponse {
version?: Version
attempt_count?: AttemptCount
completion?: (JobCompletion | null)
id: Id2
project_id: ProjectId1
creator_id: CreatorId1
job_type: JobType
status: Status1
progress: Progress
cancel_requested?: CancelRequested
message?: Message1
result_json?: (ApiMockJobResult | null)
created_at: CreatedAt1
updated_at?: UpdatedAt
started_at?: StartedAt
finished_at?: FinishedAt
}
export interface JobCompletion {
schema_version: SchemaVersion
kind: Kind
outcome: Outcome
summary: Summary
artifacts?: Artifacts
attempt: Attempt
committed_at: CommittedAt
}
export interface JobArtifact {
kind: Kind1
id: Id1
version?: Version1
}
/**
 * Business result and cancellation metadata, shared by HTTP and WebSocket.
 */
export interface ApiMockJobResult {
job_kind?: JobKind
target_endpoint_id?: TargetEndpointId
source_url?: SourceUrl
endpoints_imported?: EndpointsImported
cases_created?: CasesCreated
created_count?: CreatedCount
updated_count?: UpdatedCount
cancel_requested?: CancelRequested1
cancel_requested_at?: CancelRequestedAt
cancelled?: Cancelled
cancelled_at?: CancelledAt
}
export interface JobDoneMessage {
event_type: EventType8
payload: ApiMockJobEventContract
contract_version: ContractVersion8
}
