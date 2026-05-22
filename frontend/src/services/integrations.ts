import { apiFetch } from './api'

export interface OAuthStartResult {
  platform: string
  mock_mode: boolean
  authorize_url: string
  state: string
  application_id?: number | null
  hint?: string
}

export interface CredentialItem {
  id: number
  platform: string
  external_id: string
  expires_at?: string | null
  scopes?: string[] | null
}

export interface IntegrationOverviewItem {
  platform: string
  configured: boolean
  mock_available: boolean
  credentials: {
    total: number
    valid: number
    expiring: number
    expired: number
  }
}

export interface IntegrationOverview {
  tenant_id: number
  items: IntegrationOverviewItem[]
  redirect_base?: string | null
}

export async function startOAuth(
  platform: 'tiktok' | 'meta',
  applicationId: number,
  opts?: { forceMock?: boolean },
): Promise<OAuthStartResult> {
  const params = new URLSearchParams()
  params.set('application_id', String(applicationId))
  if (opts?.forceMock) params.set('force_mock', '1')
  return apiFetch<OAuthStartResult>(
    `/api/integrations/${platform}/oauth/start?${params.toString()}`,
  )
}

export async function listCredentials(platform?: string): Promise<{ items: CredentialItem[] }> {
  const q = platform ? `?platform=${platform}` : ''
  return apiFetch<{ items: CredentialItem[] }>(`/api/integrations/credentials${q}`)
}

export async function getIntegrationOverview(): Promise<IntegrationOverview> {
  return apiFetch<IntegrationOverview>('/api/integrations/overview')
}

export async function revokeCredential(platform: string, externalId: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(
    `/api/integrations/${platform}/credentials/${encodeURIComponent(externalId)}`,
    { method: 'DELETE' },
  )
}

/** 打开 OAuth 窗口并监听 postMessage 完成事件 */
export function openOAuthWindow(authorizeUrl: string): Promise<{ platform: string; mock?: boolean }> {
  return new Promise((resolve, reject) => {
    const w = window.open(authorizeUrl, 'oauth', 'width=520,height=720')
    if (!w) {
      reject(new Error('无法打开弹窗，请允许浏览器弹出窗口'))
      return
    }
    const timer = window.setTimeout(() => {
      window.removeEventListener('message', onMsg)
      reject(new Error('授权超时，请重试'))
    }, 5 * 60 * 1000)
    function onMsg(ev: MessageEvent) {
      const d = ev.data
      if (!d || d.type !== 'oauth_complete') return
      window.clearTimeout(timer)
      window.removeEventListener('message', onMsg)
      resolve({ platform: d.platform, mock: d.mock })
    }
    window.addEventListener('message', onMsg)
  })
}
