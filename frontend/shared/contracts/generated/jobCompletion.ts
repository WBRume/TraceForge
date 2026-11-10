/* Generated from Python contracts. Do not edit. */

export type SchemaVersion = 2
export type Kind = string
export type Outcome = ("SUCCESS" | "FAILED" | "CANCELLED")
export type Summary = string
export type Kind1 = string
export type Id = string
export type Version = (string | null)
export type Artifacts = JobArtifact[]
export type Attempt = number
export type CommittedAt = string

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
version?: Version
}
