/**
 * 阶段 7 团队邀请 — 前端 service
 */
import { apiFetch } from './api'

export type InvitationStatus = 'active' | 'accepted' | 'revoked' | 'expired'

export interface Invitation {
  id: number
  tenant_id: number
  email: string
  role: 'owner' | 'admin' | 'member'
  token: string
  status: InvitationStatus
  expires_at?: string
  accepted_at?: string | null
  revoked_at?: string | null
  invited_by_user_id?: number | null
  invited_by_username?: string | null
  invited_by_display_name?: string | null
  invitation_url?: string
  created_at?: string
}

export interface InvitationPreview {
  status: InvitationStatus
  email: string
  role: 'owner' | 'admin' | 'member'
  tenant_id: number
  tenant_name?: string | null
  tenant_slug?: string | null
  inviter_name?: string | null
  expires_at?: string | null
  email_registered: boolean
}

export interface AcceptInvitationResponse {
  ok: boolean
  token: string
  user: { id: number; username: string; role: string; display_name?: string | null }
  tenant: { id: number; slug?: string | null; name?: string | null; tenant_role: string }
  application: { id: number; name?: string; slug?: string; is_default?: boolean } | null
  allowed_panels: string[]
}

export async function listInvitations(): Promise<Invitation[]> {
  return apiFetch<Invitation[]>('/api/tenant/invitations')
}

export async function createInvitation(payload: {
  email: string; role: 'owner' | 'admin' | 'member'; ttl_days?: number
}): Promise<Invitation> {
  return apiFetch<Invitation>('/api/tenant/invitations', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function revokeInvitation(id: number): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/tenant/invitations/${id}`, { method: 'DELETE' })
}

// ── 成员管理（阶段 7 #4） ───────────────────────────────────

export interface TenantMember {
  tenant_id: number
  user_id: number
  role: 'owner' | 'admin' | 'member'
  joined_at?: string
  username?: string
  display_name?: string
}

export async function listTenantMembers(): Promise<TenantMember[]> {
  return apiFetch<TenantMember[]>('/api/tenant/members')
}

export async function updateMemberRole(
  userId: number,
  role: 'owner' | 'admin' | 'member',
): Promise<TenantMember> {
  return apiFetch<TenantMember>(`/api/tenant/members/${userId}`, {
    method: 'PUT',
    body: JSON.stringify({ role }),
  })
}

export async function removeTenantMember(userId: number): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/tenant/members/${userId}`, { method: 'DELETE' })
}

// 匿名调用，不带 Authorization。直接用 fetch 以避免 apiFetch 写 X-Application-Id。
export async function previewInvitation(token: string): Promise<InvitationPreview> {
  const res = await fetch(`/api/auth/invitation/${encodeURIComponent(token)}`)
  if (!res.ok) {
    const j = await res.json().catch(() => ({}))
    throw new Error(j?.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

export async function acceptInvitation(token: string, payload: {
  password?: string; display_name?: string
}): Promise<AcceptInvitationResponse> {
  // 接受邀请可在匿名或已登录两种状态下调用
  const tokenAuth = localStorage.getItem('auth_token')
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (tokenAuth) headers.Authorization = `Bearer ${tokenAuth}`
  const res = await fetch(`/api/auth/invitation/${encodeURIComponent(token)}/accept`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  })
  const json = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = json?.detail
    if (detail && typeof detail === 'object') {
      const e = new Error(detail.message || `HTTP ${res.status}`) as Error & { code?: string }
      e.code = detail.code
      throw e
    }
    throw new Error(detail ?? `HTTP ${res.status}`)
  }
  return json
}
