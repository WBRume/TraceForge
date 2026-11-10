/* Generated from Python contracts. Do not edit. */

export type SubmissionReply = (SubmissionAccepted | ToolFailure)
export type Kind = "accepted"
export type RunId = string
export type CallId = string
export type ReceiptId = string
export type Stage = "accepted"
export type Kind1 = "error"
export type Code = string
export type Category = ("input" | "condition" | "conflict" | "revoked" | "transient" | "uncertain" | "internal")
export type Message = string
export type Action = ("correct_arguments" | "read_context" | "stop" | "query_receipt" | "execution_policy" | "report_defect")
export type RunId1 = string
export type CallId1 = string
export type DiagnosticId = (string | null)
export type Path = (string | number)[]
export type Code1 = string
export type Message1 = string
/**
 * @maxItems 100
 */
export type Issues = FieldIssue[]

export interface SubmissionAccepted {
kind?: Kind
run_id: RunId
call_id: CallId
receipt_id: ReceiptId
stage?: Stage
}
export interface ToolFailure {
kind?: Kind1
code: Code
category: Category
message: Message
action: Action
run_id: RunId1
call_id: CallId1
diagnostic_id?: DiagnosticId
issues?: Issues
}
export interface FieldIssue {
path: Path
code: Code1
message: Message1
}
