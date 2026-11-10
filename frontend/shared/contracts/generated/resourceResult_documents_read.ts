/* Generated from Python contracts. Do not edit. */

export type TaskId = string
export type Section = ("plans" | "specs")
export type Name = string
export type SectionPath = string
export type RelativePath = string
export type Size = number
export type UpdatedAt = string
export type Content = string

export interface DocumentContent {
task_id: TaskId
section: Section
name: Name
section_path: SectionPath
relative_path: RelativePath
size: Size
updated_at: UpdatedAt
content: Content
}
