/* Generated from Python contracts. Do not edit. */

export type WorkspaceReply = (WorkspaceDirectory | WorkspaceFile | ToolFailure)
export type Kind = "directory"
/**
 * @maxItems 1000
 */
export type Entries = string[]
export type Truncated = boolean
export type Kind1 = "file"
export type Path = string
export type StartLine = number
export type TotalLines = number
export type Text = string
export type Kind2 = "error"
export type Code = string
export type Category = ("input" | "condition" | "conflict" | "revoked" | "transient" | "uncertain" | "internal")
export type Message = string
export type Action = ("correct_arguments" | "read_context" | "stop" | "query_receipt" | "execution_policy" | "report_defect")
export type RunId = string
export type CallId = string
export type DiagnosticId = (string | null)
export type Path1 = (string | number)[]
export type Code1 = string
export type Message1 = string
/**
 * @maxItems 100
 */
export type Issues = FieldIssue[]

export interface WorkspaceDirectory {
kind?: Kind
entries: Entries
truncated: Truncated
}
export interface WorkspaceFile {
kind?: Kind1
path: Path
start_line: StartLine
total_lines: TotalLines
text: Text
}
export interface ToolFailure {
kind?: Kind2
code: Code
category: Category
message: Message
action: Action
run_id: RunId
call_id: CallId
diagnostic_id?: DiagnosticId
issues?: Issues
}
export interface FieldIssue {
path: Path1
code: Code1
message: Message1
}
