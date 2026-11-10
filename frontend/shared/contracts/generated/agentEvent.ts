/* Generated from Python contracts. Do not edit. */

export type AgentEvent = (SessionStartedEvent | ModelEvent | TextEvent | TextDeltaEvent | ThinkingEvent | ToolUseEvent | ToolResultEvent | ToolProgressEvent | ResultEvent | ErrorEvent | UsageEvent | LogEvent | AskUserEvent | AskUserResolvedEvent | ContextCompactedEvent)
export type Type = "session_started"
export type ProviderSessionId = string
export type Model = (string | null)
export type Directory = (string | null)
export type Provider = (string | null)
export type Provider1 = string
export type ContractVersion = 2
export type Type1 = "model"
export type Model1 = string
export type Source = (string | null)
export type Provider2 = (string | null)
export type Provider3 = string
export type ContractVersion1 = 2
export type Type2 = "text"
export type Text = string
export type Delta = (string | null)
export type Provider4 = (string | null)
export type Model2 = (string | null)
export type Usage = ({
[k: string]: JsonValue
} | null)
export type JsonValue = unknown
export type Provider5 = string
export type ContractVersion2 = 2
export type Type3 = "text_delta"
export type Delta1 = string
export type Text1 = (string | null)
export type Provider6 = (string | null)
export type Provider7 = string
export type ContractVersion3 = 2
export type Type4 = "thinking"
export type Provider8 = string
export type ContractVersion4 = 2
export type Type5 = "tool_use"
export type ToolUseId = string
export type ToolName = string
export type Provider9 = (string | null)
export type Provider10 = string
export type ContractVersion5 = 2
export type Type6 = "tool_result"
export type ToolUseId1 = string
export type Output = string
export type IsError = boolean
export type Content = {
[k: string]: JsonValue
}[]
export type ProviderReplay = boolean
export type Provider11 = (string | null)
export type Provider12 = string
export type ContractVersion6 = 2
export type Type7 = "tool_progress"
export type ToolUseId2 = string
export type Message = string
export type Provider13 = string
export type ContractVersion7 = 2
export type Type8 = "result"
export type Success = boolean
export type Result = string
export type SessionId = (string | null)
export type DurationMs = (number | null)
export type CostUsd = (number | null)
export type FinishReason = (string | null)
export type Provider14 = (string | null)
export type Provider15 = string
export type ContractVersion8 = 2
export type Type9 = "error"
export type Provider16 = string
export type ContractVersion9 = 2
export type Type10 = "usage"
export type InputTokens = (number | null)
export type OutputTokens = (number | null)
export type CacheReadTokens = (number | null)
export type CacheCreationTokens = (number | null)
export type ThinkingTokens = (number | null)
export type TotalTokens = (number | null)
export type ToolIoTokens = (number | null)
export type ToolOutputTokens = (number | null)
export type Provider17 = (string | null)
export type Provider18 = string
export type ContractVersion10 = 2
export type Type11 = "log"
export type Level = ("trace" | "debug" | "info" | "warning" | "warn" | "error" | "critical")
export type Message1 = string
export type Provider19 = string
export type ContractVersion11 = 2
export type Type12 = "ask_user"
export type AskUserId = string
export type Kind = (string | null)
export type Question = (string | null)
export type Prompt = (string | null)
export type Provider20 = string
export type ContractVersion12 = 2
export type Type13 = "ask_user_resolved"
export type AskUserId1 = string
export type Status = ("answered" | "cancelled" | "approved" | "rejected" | "closed")
export type Provider21 = string
export type ContractVersion13 = 2
export type Type14 = "context_compacted"
export type Summary = (string | null)
export type Subtype = (string | null)
export type EventType = (string | null)
export type Source1 = (string | null)
export type TokenBefore = (number | null)
export type TokenAfter = (number | null)
export type Provider22 = string
export type ContractVersion14 = 2

export interface SessionStartedEvent {
type: Type
payload: SessionPayload
provider: Provider1
contract_version: ContractVersion
}
export interface SessionPayload {
provider_session_id: ProviderSessionId
model?: Model
directory?: Directory
provider?: Provider
}
export interface ModelEvent {
type: Type1
payload: ModelPayload
provider: Provider3
contract_version: ContractVersion1
}
export interface ModelPayload {
model: Model1
source?: Source
provider?: Provider2
}
export interface TextEvent {
type: Type2
payload: TextPayload
provider: Provider5
contract_version: ContractVersion2
}
export interface TextPayload {
text: Text
delta?: Delta
provider?: Provider4
model?: Model2
usage?: Usage
}
export interface TextDeltaEvent {
type: Type3
payload: DeltaPayload
provider: Provider7
contract_version: ContractVersion3
}
export interface DeltaPayload {
delta: Delta1
text?: Text1
provider?: Provider6
}
export interface ThinkingEvent {
type: Type4
payload: TextPayload
provider: Provider8
contract_version: ContractVersion4
}
export interface ToolUseEvent {
type: Type5
payload: ToolUsePayload
provider: Provider10
contract_version: ContractVersion5
}
export interface ToolUsePayload {
tool_use_id: ToolUseId
tool_name: ToolName
tool_input: JsonValue
provider?: Provider9
}
export interface ToolResultEvent {
type: Type6
payload: ToolResultPayload
provider: Provider12
contract_version: ContractVersion6
}
export interface ToolResultPayload {
tool_use_id: ToolUseId1
output: Output
is_error: IsError
content?: Content
structured_content?: {
[k: string]: unknown
}
provider_replay?: ProviderReplay
provider?: Provider11
}
export interface ToolProgressEvent {
type: Type7
payload: ToolProgressPayload
provider: Provider13
contract_version: ContractVersion7
}
export interface ToolProgressPayload {
tool_use_id: ToolUseId2
message: Message
}
export interface ResultEvent {
type: Type8
payload: ResultPayload
provider: Provider15
contract_version: ContractVersion8
}
export interface ResultPayload {
success: Success
result: Result
session_id?: SessionId
duration_ms?: DurationMs
cost_usd?: CostUsd
finish_reason?: FinishReason
usage?: {
[k: string]: unknown
}
provider?: Provider14
}
export interface ErrorEvent {
type: Type9
payload: ResultPayload
provider: Provider16
contract_version: ContractVersion9
}
export interface UsageEvent {
type: Type10
payload: UsagePayload
provider: Provider18
contract_version: ContractVersion10
}
export interface UsagePayload {
input_tokens?: InputTokens
output_tokens?: OutputTokens
cache_read_tokens?: CacheReadTokens
cache_creation_tokens?: CacheCreationTokens
thinking_tokens?: ThinkingTokens
total_tokens?: TotalTokens
tool_io_tokens?: ToolIoTokens
tool_output_tokens?: ToolOutputTokens
raw_usage?: {
[k: string]: unknown
}
provider?: Provider17
}
export interface LogEvent {
type: Type11
payload: LogPayload
provider: Provider19
contract_version: ContractVersion11
}
export interface LogPayload {
level: Level
message: Message1
}
export interface AskUserEvent {
type: Type12
payload: QuestionPayload
provider: Provider20
contract_version: ContractVersion12
}
export interface QuestionPayload {
ask_user_id: AskUserId
kind?: Kind
question?: Question
prompt?: Prompt
fields?: {
[k: string]: unknown
}
options?: {
[k: string]: unknown
}
resource?: {
[k: string]: unknown
}
resources?: {
[k: string]: unknown
}
permission_request?: {
[k: string]: unknown
}
}
export interface AskUserResolvedEvent {
type: Type13
payload: ResolutionPayload
provider: Provider21
contract_version: ContractVersion13
}
export interface ResolutionPayload {
ask_user_id: AskUserId1
status: Status
answer?: {
[k: string]: unknown
}
}
export interface ContextCompactedEvent {
type: Type14
payload: CompactionPayload
provider: Provider22
contract_version: ContractVersion14
}
export interface CompactionPayload {
summary?: Summary
subtype?: Subtype
event_type?: EventType
source?: Source1
token_before?: TokenBefore
token_after?: TokenAfter
}
