/* Generated from Python contracts. Do not edit. */

export type Summary = string
export type RootCause = string
/**
 * @minItems 1
 * @maxItems 50
 */
export type Evidence = [string, ...(string)[]]
/**
 * @minItems 1
 * @maxItems 50
 */
export type FixSteps = [string, ...(string)[]]
export type FixCode = (string | null)
export type FilePath = string
export type StartLine = (number | null)
export type EndLine = (number | null)
export type Snippet = (string | null)
export type Note = (string | null)
export type CodeContext = DiagnosisCodeContextItem[]
export type Title = string
export type Similarity = (string | null)
export type Summary1 = (string | null)
export type Reference = (string | null)
export type SimilarCases = DiagnosisSimilarCaseItem[]
export type Seq = (number | null)
export type Module = (string | null)
export type Function = (string | null)
export type FilePath1 = (string | null)
export type Description = (string | null)
export type CallChain = DiagnosisCallChainNode[]
export type Confidence = number

export interface DiagnosisSubmission {
summary: Summary
root_cause: RootCause
evidence: Evidence
fix_steps: FixSteps
fix_code?: FixCode
code_context?: CodeContext
similar_cases?: SimilarCases
call_chain?: CallChain
confidence?: Confidence
}
export interface DiagnosisCodeContextItem {
file_path?: FilePath
start_line?: StartLine
end_line?: EndLine
snippet?: Snippet
note?: Note
}
export interface DiagnosisSimilarCaseItem {
title?: Title
similarity?: Similarity
summary?: Summary1
reference?: Reference
}
export interface DiagnosisCallChainNode {
seq?: Seq
module?: Module
function?: Function
file_path?: FilePath1
description?: Description
}
