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
  upload_status: 'pending_upload' | 'uploading' | 'uploaded' | 'failed'
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
  material_status: 'active' | 'archived'
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

export interface UploadSession {
  id: string
  material_id: number
  version_id: number
  idempotency_key: string
  upload_mode: 'direct' | 'multipart'
  status: 'prepared' | 'uploading' | 'verifying' | 'uploaded' | 'failed' | 'expired'
  expected_size_bytes: number
  received_size_bytes: number
  part_size_bytes?: number | null
  part_count?: number | null
  progress: number
  error_message?: string | null
  upload: { direct_url?: string | null; part_url_template?: string | null; complete_url: string }
}

export const listMaterials = (keyword = '') => apiFetch<Page<MaterialMaster>>(`/api/material-catalog/masters?query=${encodeURIComponent(keyword)}&page=1&page_size=100`)
export const getMaterial = (id: number) => apiFetch<MaterialMaster>(`/api/material-catalog/masters/${id}`)
export const createMaterial = (input: MasterInput) => apiFetch<MaterialMaster>('/api/material-catalog/masters', { method: 'POST', body: JSON.stringify(input) })
export const updateMaterial = (item: MaterialMaster, input: MasterInput) => apiFetch<MaterialMaster>(`/api/material-catalog/masters/${item.id}`, { method: 'PUT', body: JSON.stringify({ ...input, revision: item.revision }) })
export const registerVersion = (id: number, input: VersionInput) => apiFetch<MaterialVersion>(`/api/material-catalog/masters/${id}/versions`, { method: 'POST', body: JSON.stringify(input) })
export const prepareUpload = (materialId: number, versionId: number, idempotencyKey: string) => apiFetch<UploadSession>('/api/material-uploads/prepare', { method: 'POST', body: JSON.stringify({ material_id: materialId, version_id: versionId, idempotency_key: idempotencyKey, mode: 'auto' }) })
export const retryUpload = (uploadId: string) => apiFetch<UploadSession>(`/api/material-uploads/${uploadId}/retry`, { method: 'POST' })
export const completeUpload = (session: UploadSession) => apiFetch<UploadSession>(session.upload.complete_url, { method: 'POST', body: JSON.stringify({ idempotency_key: session.idempotency_key }) })
export const listUploads = (materialId?: number) => apiFetch<{ items: UploadSession[] }>(`/api/material-uploads${materialId ? `?material_id=${materialId}` : ''}`)

const putBlob = (url: string, blob: Blob, onProgress: (loaded: number) => void) => new Promise<void>((resolve, reject) => {
  const request = new XMLHttpRequest()
  request.open('PUT', url)
  const token = localStorage.getItem('auth_token')
  const applicationId = localStorage.getItem('current_application_id')
  if (token) request.setRequestHeader('Authorization', `Bearer ${token}`)
  if (applicationId) request.setRequestHeader('X-Application-Id', applicationId)
  request.setRequestHeader('Content-Type', blob.type || 'application/octet-stream')
  request.upload.onprogress = event => onProgress(event.loaded)
  request.onload = () => request.status >= 200 && request.status < 300 ? resolve() : reject(new Error(`上传失败（HTTP ${request.status}）`))
  request.onerror = () => reject(new Error('上传网络错误'))
  request.send(blob)
})

export async function uploadFile(session: UploadSession, file: File, onProgress: (percent: number) => void) {
  if (session.status === 'failed' || session.status === 'expired') session = await retryUpload(session.id)
  if (session.upload_mode === 'direct') {
    await putBlob(session.upload.direct_url!, file, loaded => onProgress(Math.round(loaded * 95 / file.size)))
  } else {
    const partSize = session.part_size_bytes!
    const count = session.part_count!
    for (let number = 1; number <= count; number += 1) {
      const start = (number - 1) * partSize
      const part = file.slice(start, Math.min(file.size, start + partSize))
      await putBlob(session.upload.part_url_template!.replace('{part_number}', String(number)), part, loaded => onProgress(Math.round((start + loaded) * 95 / file.size)))
    }
  }
  onProgress(97)
  const completed = await completeUpload(session)
  onProgress(100)
  return completed
}
export const listMaterialReferences = () => apiFetch<Page<ApplicationMaterial>>('/api/material-catalog/references?page=1&page_size=100')
export const attachMaterial = (materialId: number) => apiFetch<ApplicationMaterial>('/api/material-catalog/references', { method: 'POST', body: JSON.stringify({ material_id: materialId, selection_mode: 'latest', status: 'selected' }) })
export const detachMaterial = (materialId: number) => apiFetch<{ ok: true }>(`/api/material-catalog/references/${materialId}`, { method: 'DELETE' })
