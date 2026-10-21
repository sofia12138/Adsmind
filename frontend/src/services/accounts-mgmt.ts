import { apiFetch } from './api'

export interface AdAccount {
  id: number
  platform: string
  account_id: string
  account_name: string
  currency: string
  timezone: string
  status: string
  access_token_masked: string
  app_id: string
  app_secret_masked: string
  is_default: number
  last_synced_at: string | null
  created_at: string
  updated_at: string
}

export interface VerifyResult {
  valid: boolean
  error?: string
  accounts: {
    account_id: string
    account_name: string
    currency?: string
    timezone?: string
    status?: string
  }[]
}

export function fetchAdAccounts(platform?: string) {
  const params = new URLSearchParams()
  if (platform) params.set('platform', platform)
  const qs = params.toString()
  return apiFetch<{ data: AdAccount[] }>(`/api/ad-accounts/${qs ? `?${qs}` : ''}`)
}

export function fetchAdAccount(id: number) {
  return apiFetch<{ data: AdAccount }>(`/api/ad-accounts/${id}`)
}

export function verifyToken(body: {
  platform: string
  access_token: string
  app_id?: string
  app_secret?: string
}) {
  return apiFetch<VerifyResult>('/api/ad-accounts/verify', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function addAdAccount(body: {
  platform: string
  account_id: string
  account_name?: string
  access_token: string
  app_id?: string
  app_secret?: string
  currency?: string
  timezone?: string
}) {
  return apiFetch<{ data: AdAccount }>('/api/ad-accounts/connect', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function updateAdAccount(
  id: number,
  body: {
    account_name?: string
    access_token?: string
    app_id?: string
    app_secret?: string
    status?: string
  },
) {
  return apiFetch<{ data: AdAccount }>(`/api/ad-accounts/${id}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export function deleteAdAccount(id: number) {
  return apiFetch<{ ok: boolean }>(`/api/ad-accounts/${id}`, { method: 'DELETE' })
}

export function setDefaultAccount(id: number) {
  return apiFetch<{ data: AdAccount }>(`/api/ad-accounts/${id}/default`, { method: 'POST' })
}
