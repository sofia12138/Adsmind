import { apiFetch } from './api'

export interface LaunchResponse { data?: unknown; error?: string; draft_saved?: boolean }
export interface LaunchDraft {
  id: string; name: string; template_name?: string; platform: string; status: 'DRAFT' | 'RUNNING' | 'SUCCEEDED' | 'PARTIAL' | 'FAILED' | 'UNKNOWN'
  revision: number; payload: Record<string, unknown>; result?: LaunchResponse; last_error?: string; created_at: string
  budget_mode?: 'CBO' | 'ABO'
}
export interface Precheck { ok: boolean; checks: { code: string; ok: boolean; message: string }[]; notice: string }
export async function saveLaunchDraft(payload: Record<string, unknown>, requestKey: string) {
  return apiFetch<{ data: LaunchDraft; precheck: Precheck }>('/api/launch-drafts', { method: 'POST', body: JSON.stringify({ request_key: requestKey, payload }) })
}
export async function executeLaunchDraft(draft: LaunchDraft) {
  return apiFetch<{ data: LaunchDraft }>(`/api/launch-drafts/${draft.id}/execute`, { method: 'POST', body: JSON.stringify({ revision: draft.revision }) }).then(r => r.data)
}
export function listLaunchDrafts(page: number) {
  return apiFetch<{ data: { list: LaunchDraft[]; total: number; page: number } }>(`/api/launch-drafts?page=${page}`).then(r => r.data)
}
export const DRAFT_STATUS_LABEL: Record<LaunchDraft['status'], string> = {
  DRAFT: '已保存草稿', RUNNING: '创建中或等待核对', SUCCEEDED: '创建完成', PARTIAL: '部分创建成功', FAILED: '创建失败', UNKNOWN: '结果尚未确认',
}

export function checkLaunchDraft(id: string) {
  return apiFetch<{ data: LaunchDraft; precheck: Precheck }>(`/api/launch-drafts/${id}/check`, { method: 'POST' })
}

export function updateLaunchDraft(draft: LaunchDraft, changes: { campaign_name: string; budget: string; adset_budgets: string[] }) {
  return apiFetch<{ data: LaunchDraft }>(`/api/launch-drafts/${draft.id}`, { method: 'PATCH', body: JSON.stringify({ ...changes, revision: draft.revision }) })
}
