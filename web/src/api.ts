import type {
  HistoryEntry,
  Job,
  JobSubmission,
  ModelInfo,
  ServerSettings,
} from './types'

const TOKEN_KEY = 'ytexplain-token'

/**
 * A response the server refused, as opposed to a request that never arrived.
 * The distinction drives the UI: a status means the server is alive and has an
 * opinion, while a thrown TypeError from fetch means the connection failed.
 */
export class ApiError extends Error {
  status: number
  retryAfter?: number

  constructor(status: number, message: string, retryAfter?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.retryAfter = retryAfter
  }
}

export const token = {
  // sessionStorage, not localStorage: a shared password should not outlive the tab.
  read: () => sessionStorage.getItem(TOKEN_KEY) ?? '',
  write: (value: string) => sessionStorage.setItem(TOKEN_KEY, value),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
}

/** A sentence to show for anything thrown by this module or by fetch itself. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message
  // fetch rejects with a TypeError when the request never reached the server.
  if (error instanceof TypeError) return 'Could not reach the server.'
  return error instanceof Error ? error.message : String(error)
}

function withAuth(headers: HeadersInit = {}): HeadersInit {
  const current = token.read()
  return current ? { ...headers, 'X-Access-Token': current } : headers
}

async function toError(response: Response): Promise<ApiError> {
  let message = `${response.status} ${response.statusText}`
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') message = body.detail
  } catch {
    // A proxy or a crash can answer with something that is not JSON.
  }
  const retryAfter = Number(response.headers.get('Retry-After')) || undefined
  return new ApiError(response.status, message, retryAfter)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: withAuth(init?.headers) })
  if (!response.ok) throw await toError(response)
  return (await response.json()) as T
}

export const api = {
  settings: () => request<ServerSettings>('/api/settings'),
  models: () => request<ModelInfo[]>('/api/models'),
  history: () => request<HistoryEntry[]>('/api/history'),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  submit: (body: JobSubmission) =>
    request<Job>('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  /**
   * Fetch a PDF as an object URL.
   *
   * An <iframe src> cannot carry the access token header, so the file is fetched
   * with the header and handed to the iframe as a blob instead. That also keeps
   * the token out of URLs, where it would end up in history and logs.
   */
  async fileUrl(path: string): Promise<string> {
    const response = await fetch(path, { headers: withAuth() })
    if (!response.ok) throw await toError(response)
    return URL.createObjectURL(await response.blob())
  },
}
