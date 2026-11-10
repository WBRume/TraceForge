/* Generated from Python contracts. Do not edit. */

export type ContractVersion = 2
export type EventType = ("tool_use" | "tool_result")
export type EventId = string
export type JsonValue = unknown

export interface TerminalRecord {
contract_version: ContractVersion
event_type: EventType
event_id: EventId
payload: JsonValue
}
