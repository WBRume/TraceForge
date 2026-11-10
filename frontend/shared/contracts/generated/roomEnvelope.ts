/* Generated from Python contracts. Do not edit. */

export type ContractVersion = 2
export type Type = "event"
export type Room = string
export type Epoch = string
export type Sequence = number
export type EventId = string
export type EventType = string
export type JsonValue = unknown
export type AggregateId = (string | null)
export type AggregateVersion = (number | null)
export type CreatedAt = string

export interface RoomEnvelope {
contract_version: ContractVersion
type: Type
room: Room
epoch: Epoch
sequence: Sequence
event_id: EventId
event_type: EventType
payload: JsonValue
aggregate_id: AggregateId
aggregate_version: AggregateVersion
created_at: CreatedAt
}
