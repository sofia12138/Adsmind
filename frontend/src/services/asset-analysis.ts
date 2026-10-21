import { apiFetch } from './api'

export type AnalysisDimension = 'material' | 'drama'
export type CoverageStatus = 'complete' | 'delayed' | 'partial' | 'unmapped' | 'not_uploaded' | 'missing_version' | 'no_platform_data'

export interface AnalysisMetrics {
  currency: 'USD'
  spend: string | null
  revenue_attributed: string | null
  impressions: number | null
  clicks: number | null
  installs: number | null
  conversions: number | null
  ctr: string | null
  roi: string | null
  roi_reason: string | null
  fact_rows: number
  account_count: number
  ad_count: number
  data_cutoff_at: string | null
}

export interface AnalysisItem {
  entity_type: AnalysisDimension
  entity_id: string
  name: string
  drama_id: string | null
  drama_title: string | null
  coverage_status: CoverageStatus
  coverage_reasons: Array<{ code: string; message: string; [key: string]: unknown }>
  source_filename?: string | null
  version_id?: number | null
  version_number?: number | null
  upload_status?: string | null
  material_count?: number
  complete_material_count?: number
  mapping_count: number
  matched_mapping_count: number
  platforms: string[]
  account_currencies: string[]
  account_timezones: string[]
  metrics: AnalysisMetrics
  creative_groups?: Array<{ id: string; name: string; status: string }>
  drafts?: Array<{ id: string; title: string; status: string; snapshot: string }>
  materials?: Array<{ id: string; name: string; coverage_status: CoverageStatus; spend: string | null }>
}

export interface AnalysisReport {
  contract: 'asset_analysis.v1'
  scope: { tenant_id: number; application_id: number }
  read_only: true
  dimension: AnalysisDimension
  date_from: string
  date_to: string
  currency_policy: string
  items: AnalysisItem[]
  total: number
  page: number
  page_size: number
  trend: Array<{ date: string } & AnalysisMetrics>
  coverage: {
    states: Record<string, number>
    material_total: number
    mapping_total: number
    matched_mapping_total: number
    fact_rows_total: number
    mapped_fact_rows: number
    unmapped_fact_rows: number
    ambiguous_fact_rows: number
    data_cutoff_at: string | null
    sources: string[]
    notes: string[]
  }
}

export interface AnalysisFilters {
  dimension: AnalysisDimension
  dateFrom: string
  dateTo: string
  platform?: string
  accountId?: string
  coverageStatus?: string
  query?: string
  page?: number
  pageSize?: number
}

export function buildAssetAnalysisPath(filters: AnalysisFilters) {
  const params = new URLSearchParams({ dimension: filters.dimension, date_from: filters.dateFrom, date_to: filters.dateTo })
  if (filters.platform) params.set('platform', filters.platform)
  if (filters.accountId) params.set('account_id', filters.accountId)
  if (filters.coverageStatus) params.set('coverage_status', filters.coverageStatus)
  if (filters.query?.trim()) params.set('query', filters.query.trim())
  if (filters.page && filters.page !== 1) params.set('page', String(filters.page))
  if (filters.pageSize && filters.pageSize !== 50) params.set('page_size', String(filters.pageSize))
  return `/api/asset-analysis/report?${params.toString()}`
}

export function getAssetAnalysis(filters: AnalysisFilters) {
  return apiFetch<AnalysisReport>(buildAssetAnalysisPath(filters))
}
