import { apiFetch } from './api'
export interface DistributionChannel {
  id: string; name: string; channel_id: string; language: string; timezone: string; authorization_status: 'NOT_CONNECTED'
}
export interface DistributionPayload {
  drama_name: string; version: string; language: string; material_id: string; file_name: string
  channel_id: string; title: string; description: string; thumbnail_url: string; subtitle_note: string
  audience: 'unset' | 'kids' | 'general'; publish_mode: 'immediate' | 'scheduled'; scheduled_at: string | null
  full_drama_confirmed: boolean; rights_confirmed: boolean
}
export interface DistributionDraft { id: string; revision: number; status: 'DRAFT'; payload: DistributionPayload; created_at: string; updated_at: string }
export interface DistributionCheck { ok: boolean; checks: { label: string; ok: boolean }[]; notice: string }
export const emptyDistribution: DistributionPayload = {
  drama_name: '', version: '', language: '', material_id: '', file_name: '', channel_id: '', title: '', description: '', thumbnail_url: '', subtitle_note: '',
  audience: 'unset', publish_mode: 'immediate', scheduled_at: null, full_drama_confirmed: false, rights_confirmed: false,
}
export const listDistributionChannels = () => apiFetch<{ data: DistributionChannel[] }>('/api/distribution/channels').then(r => r.data)
export const addDistributionChannel = (body: Pick<DistributionChannel, 'name' | 'channel_id' | 'language' | 'timezone'>) => apiFetch('/api/distribution/channels', { method: 'POST', body: JSON.stringify(body) })
export const listDistributionDrafts = (page: number) => apiFetch<{ data: { list: DistributionDraft[]; total: number } }>(`/api/distribution/drafts?page=${page}`).then(r => r.data)
export const saveDistributionDraft = (payload: DistributionPayload, draft?: DistributionDraft) => apiFetch<{ data: DistributionDraft }>(`/api/distribution/drafts${draft ? '/' + draft.id : ''}`, {
  method: draft ? 'PUT' : 'POST', body: JSON.stringify({ ...payload, ...(draft ? { revision: draft.revision } : {}) }),
}).then(r => r.data)
export const checkDistributionDraft = (id: string) => apiFetch<{ data: DistributionCheck }>(`/api/distribution/drafts/${id}/check`, { method: 'POST' }).then(r => r.data)
