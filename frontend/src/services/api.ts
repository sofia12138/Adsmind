const BASE = ''

export class AuthError extends Error {
  constructor() {
    super('需要登录')
    this.name = 'AuthError'
  }
}

export class ApiError extends Error {
  readonly status: number
  readonly code?: string | number
  readonly requestId?: string
  constructor(status: number, payload: unknown) {
    const body = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {}
    const detail = body.detail
    const nested = detail && typeof detail === 'object' && !Array.isArray(detail) ? detail as Record<string, unknown> : {}
    const error = body.error && typeof body.error === 'object' ? body.error as Record<string, unknown> : {}
    const validation = Array.isArray(detail) ? detail.map(item => {
      const field = Array.isArray(item.loc) ? item.loc.filter((part: unknown) => part !== 'body' && part !== 'query').join('.') : ''
      return `${field ? field + '：' : ''}${item.msg ?? '参数不正确'}`
    }).join('；') : undefined
    const message = [body.message, nested.message, error.message, typeof detail === 'string' ? detail : validation].find(v => typeof v === 'string' && v.trim())
    const code = body.code ?? nested.code ?? error.code
    const requestId = body.request_id ?? body.fbtrace_id ?? nested.request_id
    const fallback: Record<number, string> = { 403: '没有权限执行此操作', 404: '请求的资源不存在', 429: '请求过于频繁，请稍后重试', 500: '服务暂时异常，请稍后重试', 502: '上游服务暂时不可用', 503: '服务暂时不可用，请稍后重试' }
    super(`${message ?? fallback[status] ?? '请求失败'}${code != null ? `（错误码：${code}）` : ''}${requestId ? ` · 请求编号：${requestId}` : ''}`)
    this.name = 'ApiError'
    this.status = status
    this.code = typeof code === 'string' || typeof code === 'number' ? code : undefined
    this.requestId = typeof requestId === 'string' ? requestId : undefined
  }
}

/**
 * 阶段 7 配额限流：后端在配额超限时返回 HTTP 422 + detail={ code, message, used, limit, plan_id }
 * 前端业务侧应捕获此错误展示"升级套餐"提示，而不是泛化的 "API 422"。
 */
export class QuotaExceededError extends Error {
  code: string
  used: number
  limit: number
  planId: string
  upgradeHint?: string
  constructor(detail: {
    code: string; message: string; used: number; limit: number;
    plan_id: string; upgrade_hint?: string;
  }) {
    super(detail.message)
    this.name = 'QuotaExceededError'
    this.code = detail.code
    this.used = detail.used
    this.limit = detail.limit
    this.planId = detail.plan_id
    this.upgradeHint = detail.upgrade_hint
  }
}

/**
 * 阶段 4 X1：所有 API 请求自动带 X-Application-Id 头。
 * 当前应用 ID 从 localStorage.current_application_id 读取（由 AuthContext 维护）。
 * 后端已验证的隔离中间件据此把请求绑定到具体应用上下文。
 * 缺省时不发送该 header，后端会兜底到该租户的 default application。
 */
function getCurrentApplicationId(): string | null {
  return localStorage.getItem('current_application_id')
}

// ── _hint 全局事件总线 ────────────────────────────────────────
// 阶段 4 X3-filter Round 2/3 的 PoC：当后端 biz 接口因当前应用未绑定账号
// 决定 skip_query 时，会在响应里返回 `_hint` 文案。前端通过 CustomEvent
// 把它转成顶部 banner 引导用户去绑账号。
export const APPLICATION_HINT_EVENT = 'app:application-hint'

export type ApplicationHint = {
  hint: string
  applicationId?: number
  path: string
  at: number
}

function pickHint(payload: unknown, key: string): string | undefined {
  if (!payload || typeof payload !== 'object') return undefined
  const v = (payload as Record<string, unknown>)[key]
  return typeof v === 'string' && v.length > 0 ? v : undefined
}

function pickApplicationId(payload: unknown): number | undefined {
  if (!payload || typeof payload !== 'object') return undefined
  const v = (payload as Record<string, unknown>)['_application_id']
  return typeof v === 'number' ? v : undefined
}

function broadcastHintFrom(payload: unknown, path: string) {
  // 候选位置：payload._hint、payload.data._hint
  const top = pickHint(payload, '_hint')
  const nestedData = (payload as { data?: unknown })?.data
  const inData = pickHint(nestedData, '_hint')
  const hint = top ?? inData
  if (!hint) return
  const applicationId =
    pickApplicationId(payload) ?? pickApplicationId(nestedData)
  const detail: ApplicationHint = { hint, applicationId, path, at: Date.now() }
  window.dispatchEvent(new CustomEvent<ApplicationHint>(APPLICATION_HINT_EVENT, { detail }))
}

export async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const token = localStorage.getItem('auth_token') ?? ''
  const appId = getCurrentApplicationId()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(appId ? { 'X-Application-Id': appId } : {}),
  }
  const mergedHeaders = new Headers(headers)
  new Headers(opts?.headers).forEach((value, key) => mergedHeaders.set(key, value))
  const res = await fetch(`${BASE}${path}`, { ...opts, headers: mergedHeaders })
  if (res.status === 401) {
    localStorage.removeItem('auth_token')
    throw new AuthError()
  }
  if (!res.ok) {
    let payload: unknown
    try { payload = await res.json() } catch { payload = null }
    const detail = (payload as { detail?: { code?: string } } | null)?.detail
    if (res.status === 422 && detail && typeof detail.code === 'string' && detail.code.startsWith('QUOTA_EXCEEDED')) {
      throw new QuotaExceededError(detail as ConstructorParameters<typeof QuotaExceededError>[0])
    }
    throw new ApiError(res.status, payload)
  }
  const json = await res.json()
  try {
    broadcastHintFrom(json, path)
  } catch {
    /* 广播失败不影响业务 */
  }
  return json as T
}
