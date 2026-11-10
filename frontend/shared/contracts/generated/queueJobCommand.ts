/* Generated from Python contracts. Do not edit. */

export type ContractVersion = 2
export type CommandId = string
export type ExpectedVersion = number

export interface QueueJobCommand {
contract_version: ContractVersion
command_id: CommandId
expected_version: ExpectedVersion
}
