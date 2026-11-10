/* Generated from Python contracts. Do not edit. */

export type Version = number
export type AttemptCount = number
export type SchemaVersion = 2
export type Kind = string
export type Outcome = ("SUCCESS" | "FAILED" | "CANCELLED")
export type Summary = string
export type Kind1 = string
export type Id = string
export type Version1 = (string | null)
export type Artifacts = JobArtifact[]
export type Attempt = number
export type CommittedAt = string
export type Id1 = string
export type ProjectId = string
export type CreatorId = string
export type JobType = string
export type Status = ("PENDING" | "RUNNING" | "WAITING_HITL" | "INTERRUPTED" | "TERMINATING" | "ORPHANED" | "SUCCESS" | "FAILED" | "CANCELLED" | "REVERTED")
export type Progress = number
export type CancelRequested = boolean
export type Message = (string | null)
export type JobKind = (string | null)
export type TargetEndpointId = (string | null)
export type SourceUrl = (string | null)
export type EndpointsImported = (number | null)
export type CreatedCount = (number | null)
export type UpdatedCount = (number | null)
export type CancelRequested1 = (boolean | null)
export type CancelRequestedAt = (string | null)
export type Cancelled = (boolean | null)
export type CancelledAt = (string | null)
export type CreatedAt = string
export type UpdatedAt = (string | null)
export type StartedAt = (string | null)
export type FinishedAt = (string | null)

export interface ApiMockJobResponse {
version?: Version
attempt_count?: AttemptCount
completion?: (JobCompletion | null)
id: Id1
project_id: ProjectId
creator_id: CreatorId
job_type: JobType
status: Status
progress: Progress
cancel_requested?: CancelRequested
message?: Message
result_json?: (ApiMockJobResult | null)
created_at: CreatedAt
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
id: Id
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
created_count?: CreatedCount
updated_count?: UpdatedCount
cancel_requested?: CancelRequested1
cancel_requested_at?: CancelRequestedAt
cancelled?: Cancelled
cancelled_at?: CancelledAt
}
