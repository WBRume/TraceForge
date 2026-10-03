import axios from 'axios'

let nativeFetch: typeof globalThis.fetch | undefined

export function configureNativeHttp(fetch: typeof globalThis.fetch): void {
  // The Tauri plugin reads cancellation from init, while Axios puts it on Request.
  nativeFetch = async (input, init) => {
    const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined)
    try {
      return await fetch(input, signal ? { ...init, signal } : init)
    } catch (error) {
      if (signal?.aborted) throw signal.reason
      throw error instanceof Error ? error : new Error(String(error))
    }
  }
  // All Axios clients inherit the native transport before Vue modules load.
  axios.defaults.adapter = 'fetch'
  axios.defaults.env = { ...axios.defaults.env, fetch: nativeFetch }
}

export function backendFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return (nativeFetch ?? globalThis.fetch)(input, init)
}
