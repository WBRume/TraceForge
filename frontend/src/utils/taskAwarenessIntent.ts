/** Explicit user actions seed a view-local intent; snapshot loads never call this. */
export function noteTaskRunInitiated(taskId: string, requestId?: string, jobId?: string) {
  window.dispatchEvent(new CustomEvent('task-run-initiated', { detail: { taskId, requestId, jobId } }))
}
export function forgetTaskRunIntent(taskId: string, requestId?: string) {
  window.dispatchEvent(new CustomEvent('task-run-rejected', { detail: { taskId, requestId } }))
}
/** Reading a result consumes only an existing intent; it never qualifies a run. */
export function noteTaskJobObserved(job: unknown) {
  window.dispatchEvent(new CustomEvent('task-job-observed', { detail: job }))
}
