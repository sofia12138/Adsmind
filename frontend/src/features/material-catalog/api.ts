import { apiFetch } from '@/services/api'

export type MaterialType = 'video' | 'image' | 'audio' | 'other'

export interface MaterialVersion {
  id: number
  tenant_id: number
  material_id: number
  version_number: number
  source_filename: string
  mime_type: string
  size_bytes: number
  checksum_sha256?: string | null
  width?: number | null
  height?: number | null
  duration_ms?: number | null
  storage_backend: string
  storage_key?: string | null
  upload_status: 'pending_upload' | 'uploaded' | 'failed'
  notes: string
  upload?: { available: boolean; status: string; reason: string; upload_url?: string | null }
}

export interface MaterialMaster {
  id: number
  drama_id?: number | null
  drama_title?: string | null
  name: string
  material_type: MaterialType
  description: string
  tags: string[]
  status: 'active' | 'archived'
  latest_version_number: number
  revision: number
  versions?: MaterialVersion[]
}

export interface ApplicationMaterial {
  reference_id: number
  material_id: number
  selected_version_id?: number | null
  selection_mode: 'latest' | 'pinned'
  reference_status: 'selected' | 'paused'
  notes: string
  name: string
  material_type: MaterialType
  latest_version_number: number
  selected_version_number?: number | null
  selected_version_upload_status?: string | null
}

export interface MasterInput {
  name: string
  material_type: MaterialType
  drama_id?: number | null
  description: string
  tags: string[]
  status: 'active' | 'archived'
}

export interface VersionInput {
  source_filename: string
  mime_type: string
  size_bytes: number
  checksum_sha256?: string | null
  width?: number | null
  height?: number | null
  duration_ms?: number | null
  notes: string
  metadata?: Record<string, unknown>
}

export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export const listMaterials = (keyword = '') => apiFetch<Page<MaterialMaster>>(`/api/material-catalog/masters?query=${encodeURIComponent(keyword)}&page=1&page_size=100`)
export const getMaterial = (id: number) => apiFetch<MaterialMaster>(`/api/material-catalog/masters/${id}`)
export const createMaterial = (input: MasterInput) => apiFetch<MaterialMaster>('/api/material-catalog/masters', { method: 'POST', body: JSON.stringify(input) })
export const updateMaterial = (item: MaterialMaster, input: MasterInput) => apiFetch<MaterialMaster>(`/api/material-catalog/masters/${item.id}`, { method: 'PUT', body: JSON.stringify({ ...input, revision: item.revision }) })
export const registerVersion = (id: number, input: VersionInput) => apiFetch<MaterialVersion>(`/api/material-catalog/masters/${id}/versions`, { method: 'POST', body: JSON.stringify(input) })
export const listMaterialReferences = () => apiFetch<Page<ApplicationMaterial>>('/api/material-catalog/references?page=1&page_size=100')
export const attachMaterial = (materialId: number) => apiFetch<ApplicationMaterial>('/api/material-catalog/references', { method: 'POST', body: JSON.stringify({ material_id: materialId, selection_mode: 'latest', status: 'selected' }) })
export const detachMaterial = (materialId: number) => apiFetch<{ ok: true }>(`/api/material-catalog/references/${materialId}`, { method: 'DELETE' })
