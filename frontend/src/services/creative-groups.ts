import { apiFetch } from './api'

export type CreativeGroupSelectionMode = 'latest' | 'pinned'

export interface CreativeGroupMaterialInput {
  material_id: number
  selection_mode: CreativeGroupSelectionMode
  selected_version_id: number | null
}

export interface CreativeGroupMaterial extends CreativeGroupMaterialInput {
  position: number
  material_name: string
  material_type: string
  material_status: 'active' | 'archived'
  reference_status: 'selected' | 'paused'
  effective_version_id: number | null
  selected_version_number: number | null
  selected_version_upload_status: string | null
  selected_version_filename: string | null
  blocking_reasons: string[]
  can_deliver: boolean
}

export interface CreativeGroup {
  id: number
  name: string
  asset_refs: CreativeGroupMaterialInput[]
  materials: CreativeGroupMaterial[]
  created_by: string
  created_at?: string
  updated_at?: string
  blocking_reasons: string[]
  can_deliver: boolean
}

export interface CreativeGroupInput {
  name: string
  materials: CreativeGroupMaterialInput[]
}

export async function fetchCreativeGroups() {
  return (await apiFetch<{ data: CreativeGroup[] }>('/api/creative-groups')).data
}

export function createCreativeGroup(body: CreativeGroupInput) {
  return apiFetch<{ data: CreativeGroup }>('/api/creative-groups', {
    method: 'POST', body: JSON.stringify(body),
  })
}

export function updateCreativeGroup(id: number, body: CreativeGroupInput) {
  return apiFetch<{ data: CreativeGroup }>(`/api/creative-groups/${id}`, {
    method: 'PUT', body: JSON.stringify(body),
  })
}

export function deleteCreativeGroup(id: number) {
  return apiFetch<{ ok: true }>(`/api/creative-groups/${id}`, { method: 'DELETE' })
}
