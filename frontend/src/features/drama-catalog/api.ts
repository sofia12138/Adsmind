import { apiFetch } from '@/services/api'

export type CatalogType = 'self_operated' | 'distribution'

export interface DramaMaster {
  id: number
  catalog_type: CatalogType
  title: string
  chinese_title: string
  language: string
  launched_at: string | null
  revision: number
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface MasterInput {
  catalog_type: CatalogType
  title: string
  chinese_title: string
  language: string
  launched_at: string | null
}

export const listMasters = (catalogType: CatalogType, keyword = '') => {
  const params = new URLSearchParams({ catalog_type: catalogType, query: keyword, page: '1', page_size: '100' })
  return apiFetch<Page<DramaMaster>>(`/api/drama-catalog/masters?${params}`)
}

export const createMaster = (input: MasterInput) =>
  apiFetch<DramaMaster>('/api/drama-catalog/masters', { method: 'POST', body: JSON.stringify(input) })

export const updateMaster = (item: DramaMaster, input: MasterInput) =>
  apiFetch<DramaMaster>(`/api/drama-catalog/masters/${item.id}`, {
    method: 'PUT', body: JSON.stringify({ ...input, revision: item.revision }),
  })

export const deleteMaster = (id: number) =>
  apiFetch<{ ok: boolean }>(`/api/drama-catalog/masters/${id}`, { method: 'DELETE' })
