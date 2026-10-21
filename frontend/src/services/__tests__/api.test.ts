import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiFetch, AuthError, QuotaExceededError } from '../api'
afterEach(() => vi.unstubAllGlobals())
function requestEnvironment(response: Response) {
  const storage = new Map([['auth_token', 'local-token'], ['current_application_id', '12']])
  vi.stubGlobal('localStorage', { getItem: (key: string) => storage.get(key), removeItem: (key: string) => storage.delete(key) })
  const fetch = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetch)
  return { storage, fetch }
}
describe('API failure explanations', () => {
  it('preserves platform messages, error codes and diagnostic trace IDs', () => {
    expect(new ApiError(400, { message: '素材未就绪', code: 40104, request_id: 'trace-123' }).message).toContain('素材未就绪（错误码：40104） · 请求编号：trace-123')
    expect(new ApiError(400, { message: '权限不足', fbtrace_id: 'meta-trace' }).requestId).toBe('meta-trace')
    expect(new ApiError(422, { detail: [{ loc: ['body', 'budget'], msg: '必须大于零' }] }).message).toBe('budget：必须大于零')
  })
  it('supports ordinary FastAPI detail strings and non-JSON errors', async () => {
    requestEnvironment(new Response(JSON.stringify({ detail: '账户不属于当前应用' }), { status: 403 }))
    await expect(apiFetch('/test')).rejects.toThrow('账户不属于当前应用')
    requestEnvironment(new Response('<html>Bad Gateway</html>', { status: 502 }))
    await expect(apiFetch('/test')).rejects.toThrow('上游服务暂时不可用')
  })
  it('retains authentication and application headers alongside caller headers', async () => {
    const { fetch } = requestEnvironment(new Response('{}', { status: 200 }))
    await apiFetch('/test', { headers: { 'X-Test': 'custom' } })
    const headers = fetch.mock.calls[0][1].headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer local-token')
    expect(headers.get('X-Application-Id')).toBe('12')
    expect(headers.get('X-Test')).toBe('custom')
  })
  it('retains quota errors and clears expired authentication', async () => {
    requestEnvironment(new Response(JSON.stringify({ detail: { code: 'QUOTA_EXCEEDED_ADS', message: '超出配额', used: 10, limit: 10, plan_id: 'free' } }), { status: 422 }))
    await expect(apiFetch('/test')).rejects.toBeInstanceOf(QuotaExceededError)
    const { storage } = requestEnvironment(new Response('{}', { status: 401 }))
    await expect(apiFetch('/test')).rejects.toBeInstanceOf(AuthError)
    expect(storage.has('auth_token')).toBe(false)
  })
})
