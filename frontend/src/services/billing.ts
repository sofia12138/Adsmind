import { apiFetch } from './api'

export interface UpgradeRequest {
  id: number
  tenant_id: number
  tenant_name?: string
  tenant_slug?: string
  from_plan_id: string
  to_plan_id: string
  contact_email: string
  message?: string | null
  status: 'pending' | 'approved' | 'rejected' | 'canceled'
  requested_by_username?: string | null
  admin_note?: string | null
  created_at?: string
  processed_at?: string | null
}

export async function createUpgradeRequest(payload: {
  to_plan_id: string
  contact_email: string
  message?: string
}): Promise<UpgradeRequest> {
  return apiFetch<UpgradeRequest>('/api/billing/upgrade-request', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function listMyUpgradeRequests(): Promise<UpgradeRequest[]> {
  return apiFetch<UpgradeRequest[]>('/api/billing/upgrade-requests')
}

export async function cancelUpgradeRequest(id: number): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/billing/upgrade-request/${id}/cancel`, {
    method: 'POST',
  })
}

export async function adminListUpgradeRequests(status?: string): Promise<UpgradeRequest[]> {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  return apiFetch<UpgradeRequest[]>(`/api/billing/admin/upgrade-requests${q}`)
}

export async function adminApproveUpgrade(id: number, adminNote?: string): Promise<UpgradeRequest> {
  return apiFetch<UpgradeRequest>(`/api/billing/admin/upgrade-requests/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ admin_note: adminNote ?? '' }),
  })
}

export async function adminRejectUpgrade(id: number, adminNote?: string): Promise<UpgradeRequest> {
  return apiFetch<UpgradeRequest>(`/api/billing/admin/upgrade-requests/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ admin_note: adminNote ?? '' }),
  })
}
