import { apiFetch } from './api'

export interface BlockingReason {
  code: string
  message: string
  field?: string
  platform?: string
  account_id?: string
}

export interface ResolvedAccount {
  platform: string
  account_id: string
  account_name: string
  currency: string
  timezone: string
  status: string
}

export interface NamePreview {
  platform: string
  account_id: string
  account_name: string
  campaign_name: string
  adgroup_name: string
  creative_name: string
}

export interface CreativeSnapshotMaterial {
  material_id: number
  material_name: string
  selection_mode: 'latest' | 'pinned'
  selected_version_id: number | null
  effective_version_id: number | null
  upload_status: string | null
}

export interface AdCreationDraft {
  id: string
  title: string
  status: 'DRAFT' | 'READY'
  revision: number
  created_by: string
  account_group_id: number
  naming_rule_id: number
  creative_group_id: number
  naming_values: Record<string, string>
  resolved_accounts: ResolvedAccount[]
  name_previews: NamePreview[]
  creative_snapshot: { id: number; name: string; can_deliver: boolean; materials: CreativeSnapshotMaterial[] }
  blocking_reasons: BlockingReason[]
  execution_snapshot: Record<string, unknown> | null
  execution_snapshot_hash: string | null
  ready_at: string | null
  updated_at: string
}

export interface DraftInput {
  request_key?: string
  title: string
  account_group_id: number
  naming_rule_id: number
  creative_group_id: number
  naming_values: Record<string, string>
}

export async function listAdCreationDrafts() {
  return (await apiFetch<{ data: AdCreationDraft[] }>('/api/ad-creation-drafts')).data
}

export async function getAdCreationDraft(id: string) {
  return (await apiFetch<{ data: AdCreationDraft }>(`/api/ad-creation-drafts/${id}`)).data
}

export async function createAdCreationDraft(input: DraftInput) {
  return (await apiFetch<{ data: AdCreationDraft }>('/api/ad-creation-drafts', {
    method: 'POST', body: JSON.stringify(input),
  })).data
}

export async function updateAdCreationDraft(id: string, input: DraftInput & { revision: number }) {
  return (await apiFetch<{ data: AdCreationDraft }>(`/api/ad-creation-drafts/${id}`, {
    method: 'PUT', body: JSON.stringify(input),
  })).data
}

export async function checkAdCreationDraft(id: string) {
  return (await apiFetch<{ data: AdCreationDraft }>(`/api/ad-creation-drafts/${id}/check`, { method: 'POST' })).data
}

export async function markAdCreationDraftReady(id: string, revision: number) {
  return (await apiFetch<{ data: AdCreationDraft }>(`/api/ad-creation-drafts/${id}/ready`, {
    method: 'POST', body: JSON.stringify({ revision }),
  })).data
}
