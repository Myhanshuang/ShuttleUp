let csrfToken: string | null = null

export function setCsrf(value: string | null) { csrfToken = value }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public body: unknown) { super(message) }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (csrfToken && options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrfToken)
  const response = await fetch(`/api/v1${path}`, { ...options, headers, credentials: 'same-origin' })
  if (response.status === 204) return undefined as T
  const body = await response.json()
  if (!response.ok) {
    const error = body.error ?? body.detail ?? {}
    throw new ApiError(response.status, error.code ?? 'REQUEST_FAILED', error.message ?? '操作失败', body)
  }
  return body as T
}

