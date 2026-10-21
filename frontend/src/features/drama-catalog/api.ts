import { apiFetch } from '@/services/api'

export interface DramaMaster {
  id: number
  title: string
  aliases: string[]
  original_language: string
  region: string
  genres: string[]
  synopsis: string
  cover_url: string
  revision: number
  created_at?: string
  updated_at?: string
}

export interface ApplicationDrama extends Omit<DramaMaster, 'id'> {
  reference_id: number
  application_id: number
  drama_id: number
  display_title: string
  reference_status: 'active' | 'paused'
  notes: string
  attached_at?: string
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface MasterInput {
  title: string
  aliases: string[]
  original_language: string
  region: string
  genres: string[]
  synopsis: string
  cover_url: string
}

const query = (value: string) => `?query=${encodeURIComponent(value)}&page=1&page_size=100`

export const listMasters = (keyword = '') =>
  apiFetch<Page<DramaMaster>>(`/api/drama-catalog/masters${query(keyword)}`)

export const createMaster = (input: MasterInput) =>
  apiFetch<DramaMaster>('/api/drama-catalog/masters', { method: 'POST', body: JSON.stringify(input) })

export const updateMaster = (item: DramaMaster, input: MasterInput) =>
  apiFetch<DramaMaster>(`/api/drama-catalog/masters/${item.id}`, {
    method: 'PUT', body: JSON.stringify({ ...input, revision: item.revision }),
  })

export const deleteMaster = (id: number) =>
  apiFetch<{ ok: boolean }>(`/api/drama-catalog/masters/${id}`, { method: 'DELETE' })

export const listReferences = (keyword = '') =>
  apiFetch<Page<ApplicationDrama>>(`/api/drama-catalog/references${query(keyword)}`)

export const attachDrama = (dramaId: number) =>
  apiFetch<ApplicationDrama>('/api/drama-catalog/references', {
    method: 'POST', body: JSON.stringify({ drama_id: dramaId }),
  })

export const updateReference = (
  dramaId: number,
  input: { display_title: string; status: 'active' | 'paused'; notes: string },
) => apiFetch<ApplicationDrama>(`/api/drama-catalog/references/${dramaId}`, {
  method: 'PATCH', body: JSON.stringify(input),
})

export const detachDrama = (dramaId: number) =>
  apiFetch<{ ok: boolean }>(`/api/drama-catalog/references/${dramaId}`, { method: 'DELETE' })
