import { apiFetch } from './api'

export type ReadinessEntityType = 'material' | 'creative_group' | 'draft' | 'preflight'

export interface ReadinessReason {
  code: string
  message: string
  [key: string]: unknown
}

export interface ReadinessItem {
  entity_type: ReadinessEntityType
  entity_id: string
  name: string
  status: string
  status_label: string
  reasons: ReadinessReason[]
  last_changed_at: string | null
  trace_url: string
  metadata: Record<string, unknown>
}

export interface ReadinessSummary {
  materials: Record<'uploaded' | 'pending_upload' | 'uploading' | 'failed' | 'missing' | 'unknown', number>
  creative_groups: Record<'deliverable' | 'blocked' | 'unknown', number>
  drafts: Record<'ready' | 'blocked' | 'pending' | 'unknown', number>
  preflights: Record<'passed' | 'blocked' | 'not_run' | 'unknown', number>
  preflight_blocking_reasons: Array<{ code: string; count: number }>
  pending_total: number
  last_changed_at: string | null
}

export interface ReadinessDetailsResponse {
  contract: 'readiness_analytics.v1'
  scope: { tenant_id: number; application_id: number }
  read_only: true
  disclaimer: string
  summary: ReadinessSummary
  source_freshness: {
    materials: string | null
    creative_groups: string | null
    drafts: string | null
    preflights: string | null
  }
  data: ReadinessItem[]
  total: number
  page: number
  page_size: number
}

export interface ReadinessFilters {
  entityType?: ReadinessEntityType
  status?: string
  reasonCode?: string
  query?: string
  page?: number
  pageSize?: number
}

export function buildReadinessDetailsPath(filters: ReadinessFilters = {}) {
  const params = new URLSearchParams()
  if (filters.entityType) params.set('entity_type', filters.entityType)
  if (filters.status) params.set('status', filters.status)
  if (filters.reasonCode) params.set('reason_code', filters.reasonCode)
  if (filters.query?.trim()) params.set('query', filters.query.trim())
  if (filters.page && filters.page !== 1) params.set('page', String(filters.page))
  if (filters.pageSize && filters.pageSize !== 50) params.set('page_size', String(filters.pageSize))
  const query = params.toString()
  return `/api/readiness-analytics/details${query ? `?${query}` : ''}`
}

export async function getReadinessDetails(filters: ReadinessFilters = {}) {
  return apiFetch<ReadinessDetailsResponse>(buildReadinessDetailsPath(filters))
}
