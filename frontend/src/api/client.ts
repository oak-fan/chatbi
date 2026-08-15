type ApiEnvelope<T> = {
  timestamp: number
  code: number
  message: string
  data: T
  requestId?: string
}

export class ApiError extends Error {
  code?: number
  status?: number
  data?: unknown

  constructor(
    message: string,
    options: { code?: number; status?: number; data?: unknown } = {},
  ) {
    super(message)
    this.code = options.code
    this.status = options.status
    this.data = options.data
  }
}

export type RequestOptions = Omit<RequestInit, 'body'> & {
  body?: unknown
  basePathOverride?: string | null
  timeoutMs?: number
}

const CHATBI_API_BASE = '/api/v1'

const resolveRequestUrl = (path: string, basePathOverride?: string | null) => {
  if (/^https?:\/\//i.test(path)) return path
  const base = basePathOverride || CHATBI_API_BASE
  const normalizedBase = base.replace(/\/$/, '')
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${normalizedBase}${normalizedPath}`
}

const generateRequestId = () =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `req_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`

async function executeRequest(path: string, options: RequestOptions = {}) {
  const headers = new Headers(options.headers || {})
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData
  const hasBody = typeof options.body !== 'undefined'

  if (!isFormData && hasBody && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (!headers.has('X-Request-ID')) {
    headers.set('X-Request-ID', generateRequestId())
  }

  const timeoutMs = options.timeoutMs ?? 0
  const shouldUseTimeout = timeoutMs > 0
  const abortController = shouldUseTimeout ? new AbortController() : undefined
  let didTimeout = false
  let timeoutId: ReturnType<typeof setTimeout> | undefined

  if (abortController && options.signal) {
    if (options.signal.aborted) {
      abortController.abort()
    } else {
      options.signal.addEventListener('abort', () => abortController.abort(), { once: true })
    }
  }

  if (abortController && shouldUseTimeout) {
    timeoutId = setTimeout(() => {
      didTimeout = true
      abortController.abort()
    }, timeoutMs)
  }

  try {
    const { body: _body, basePathOverride: _bpo, timeoutMs: _tmo, ...restOptions } = options
    const requestOptions: RequestInit = {
      ...restOptions,
      headers,
      signal: abortController ? abortController.signal : options.signal,
    }

    if (typeof options.body !== 'undefined') {
      requestOptions.body = isFormData ? (options.body as FormData) : JSON.stringify(options.body)
    }

    const response = await fetch(resolveRequestUrl(path, options.basePathOverride), requestOptions)
    return { response }
  } catch (error) {
    if (didTimeout) throw new ApiError('请求超时', { code: 408, status: 408 })
    throw new ApiError(error instanceof Error ? error.message : '网络请求失败', { code: 0 })
  } finally {
    if (timeoutId) clearTimeout(timeoutId)
  }
}

async function readJsonPayload<T>(response: Response): Promise<{ payload: ApiEnvelope<T> | null; parseFailed: boolean }> {
  let rawText = ''
  try {
    rawText = await response.text()
  } catch {
    return { payload: null, parseFailed: true }
  }
  if (!rawText.trim()) return { payload: null, parseFailed: false }
  try {
    return { payload: JSON.parse(rawText) as ApiEnvelope<T>, parseFailed: false }
  } catch {
    return { payload: null, parseFailed: true }
  }
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { response } = await executeRequest(path, options)

  if (response.status === 204) return undefined as T

  const { payload, parseFailed } = await readJsonPayload<T>(response)
  if (parseFailed) {
    throw new ApiError('无法解析服务器响应', { status: response.status })
  }
  if (!payload) {
    if (!response.ok) throw new ApiError('请求失败', { status: response.status })
    return undefined as T
  }

  if (!response.ok) {
    throw new ApiError(payload.message || '请求失败', {
      code: payload.code,
      status: response.status,
      data: payload.data,
    })
  }

  if (payload.code !== 200) {
    throw new ApiError(payload.message || '请求失败', {
      code: payload.code,
      status: response.status,
      data: payload.data,
    })
  }

  return payload.data
}

export async function apiRequestStream(path: string, options: RequestOptions = {}): Promise<Response> {
  const { response } = await executeRequest(path, options)

  if (!response.ok) {
    const { payload } = await readJsonPayload<never>(response)
    throw new ApiError(payload?.message || '请求失败', {
      code: payload?.code || response.status,
      status: response.status,
    })
  }

  return response
}
