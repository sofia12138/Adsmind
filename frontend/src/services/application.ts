/**
 * application.ts — 应用（Application）管理 API 服务
 *
 * 对应后端 /api/applications/* 路由。
 * 详见 docs/saas-transformation.md §22。
 */
import { apiFetch } from './api'

// ─────────────────────────────────────────────────────────────
// 类型定义
// ─────────────────────────────────────────────────────────────

export interface Application {
  id: number
  tenant_id: number
  slug: string
  name: string
  description?: string | null
  icon_url?: string | null
  platform_type: 'ios' | 'android' | 'web' | 'mini_program' | 'multi'
  bundle_id?: string | null
  store_url_ios?: string | null
  store_url_android?: string | null
  industry?: string | null
  status: 'active' | 'archived'
  is_default: boolean
  settings: Record<string, unknown>
  created_by?: number | null
  created_at?: string | null
  updated_at?: string | null
}

export interface ApplicationCreateInput {
  name: string
  slug?: string
  description?: string
  icon_url?: string
  platform_type?: Application['platform_type']
  bundle_id?: string
  store_url_ios?: string
  store_url_android?: string
  industry?: string
  settings?: Record<string, unknown>
}

export type ApplicationUpdateInput = Partial<ApplicationCreateInput>

export interface ApplicationMember {
  application_id: number
  user_id: number
  role: 'owner' | 'admin' | 'editor' | 'viewer'
  joined_at?: string | null
  username?: string | null
  email?: string | null
}

// ─────────────────────────────────────────────────────────────
// CRUD
// ─────────────────────────────────────────────────────────────

export async function listApplications(includeArchived = false): Promise<Application[]> {
  const qs = includeArchived ? '?include_archived=true' : ''
  return apiFetch<Application[]>(`/api/applications${qs}`)
}

export async function getApplication(id: number): Promise<Application> {
  return apiFetch<Application>(`/api/applications/${id}`)
}

export async function createApplication(input: ApplicationCreateInput): Promise<Application> {
  return apiFetch<Application>('/api/applications', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function updateApplication(
  id: number,
  input: ApplicationUpdateInput,
): Promise<Application> {
  return apiFetch<Application>(`/api/applications/${id}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
}

export async function archiveApplication(id: number): Promise<{ ok: boolean; status: string }> {
  return apiFetch(`/api/applications/${id}`, { method: 'DELETE' })
}

export async function restoreApplication(id: number): Promise<{ ok: boolean; status: string }> {
  return apiFetch(`/api/applications/${id}/restore`, { method: 'POST' })
}

// ─────────────────────────────────────────────────────────────
// 成员管理（X5 真正用，X1 暂留接口）
// ─────────────────────────────────────────────────────────────

export async function listMembers(id: number): Promise<ApplicationMember[]> {
  return apiFetch<ApplicationMember[]>(`/api/applications/${id}/members`)
}

export async function addMember(
  id: number,
  userId: number,
  role: ApplicationMember['role'] = 'editor',
): Promise<ApplicationMember> {
  return apiFetch<ApplicationMember>(`/api/applications/${id}/members`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, role }),
  })
}

export async function updateMemberRole(
  id: number,
  userId: number,
  role: ApplicationMember['role'],
): Promise<{ ok: boolean }> {
  return apiFetch(`/api/applications/${id}/members/${userId}`, {
    method: 'PUT',
    body: JSON.stringify({ user_id: userId, role }),
  })
}

export async function removeMember(id: number, userId: number): Promise<{ ok: boolean }> {
  return apiFetch(`/api/applications/${id}/members/${userId}`, { method: 'DELETE' })
}

// ─────────────────────────────────────────────────────────────
// 广告账号绑定（X3）
// ─────────────────────────────────────────────────────────────

export interface AdAccountRow {
  id: number
  platform: string
  account_id: string
  account_name: string
  currency: string
  timezone: string
  status: string
  is_default: number
  application_id?: number | null
  last_synced_at?: string | null
}

export async function listApplicationAdAccounts(applicationId: number): Promise<AdAccountRow[]> {
  return apiFetch<AdAccountRow[]>(`/api/applications/${applicationId}/ad-accounts`)
}

export async function listAvailableAdAccounts(): Promise<AdAccountRow[]> {
  return apiFetch<AdAccountRow[]>('/api/applications/ad-accounts/available')
}

export async function bindAdAccount(
  applicationId: number,
  accountRowId: number,
): Promise<{ ok: boolean; affected: number }> {
  return apiFetch(`/api/applications/${applicationId}/ad-accounts/bind`, {
    method: 'POST',
    body: JSON.stringify({ account_row_id: accountRowId }),
  })
}

export async function unbindAdAccount(
  applicationId: number,
  accountRowId: number,
): Promise<{ ok: boolean; affected: number }> {
  return apiFetch(`/api/applications/${applicationId}/ad-accounts/unbind`, {
    method: 'POST',
    body: JSON.stringify({ account_row_id: accountRowId }),
  })
}
