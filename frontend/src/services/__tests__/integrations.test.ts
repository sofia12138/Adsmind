import { afterEach, describe, expect, it, vi } from 'vitest'
import { startOAuth, getPlatformAuthorization, finishPlatformAuthorization } from '../integrations'

afterEach(() => vi.unstubAllGlobals())

function environment(payload: unknown, status = 200) {
  vi.stubGlobal('localStorage', { getItem: (key: string) => key === 'auth_token' ? 'local-token' : '99' })
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

describe('official platform authorization API', () => {
  for (const platform of ['tiktok', 'meta'] as const) {
    it(`starts ${platform} authorization with the selected application and no mock fallback`, async () => {
      const payload = { platform, mock_mode: false, authorize_url: 'https://example.test/authorize', application_id: 12 }
      const fetch = environment(payload)
      expect(await startOAuth(platform, 12)).toEqual(payload)
      const [path, options] = fetch.mock.calls[0]
      expect(path).toBe(`/api/integrations/${platform}/oauth/start?application_id=12`)
      expect(options.headers.get('X-Application-Id')).toBe('12')
      expect(options.headers.get('Authorization')).toBe('Bearer local-token')
      expect(options.cache).toBe('no-store')
    })
  }

  it('reads session accounts without caching and sends only the selected account on completion', async () => {
    const payload = { application_id: 12, accounts: [{ account_id: '11', account_name: 'Example', currency: 'USD', timezone: 'UTC' }] }
    const fetch = environment(payload)
    expect(await getPlatformAuthorization('tiktok', 'session/one', 12)).toEqual(payload)
    expect(fetch.mock.calls[0][0]).toBe('/api/integrations/tiktok/authorization/session%2Fone')
    expect(fetch.mock.calls[0][1].cache).toBe('no-store')
    expect(fetch.mock.calls[0][1].headers.get('X-Application-Id')).toBe('12')
    fetch.mockResolvedValueOnce(new Response('{"data":{"id":1}}', { status: 200 }))
    await finishPlatformAuthorization('tiktok', 'session/one', '11', 12)
    const [path, options] = fetch.mock.calls[1]
    expect(path).toBe('/api/integrations/tiktok/authorization/session%2Fone')
    expect(options.method).toBe('POST')
    expect(JSON.parse(options.body)).toEqual({ account_id: '11' })
    expect(options.headers.get('X-Application-Id')).toBe('12')
  })

  it('preserves unavailable-platform and expired-session errors without alternate requests', async () => {
    const fetch = environment({ detail: '平台授权应用尚未配置，请联系系统管理员' }, 503)
    await expect(startOAuth('meta', 12)).rejects.toThrow('平台授权应用尚未配置')
    expect(fetch).toHaveBeenCalledTimes(1)
    environment({ detail: '授权会话无效或已过期，请重新连接' }, 404)
    await expect(getPlatformAuthorization('meta', 'expired', 12)).rejects.toThrow('授权会话无效或已过期')
  })
})
