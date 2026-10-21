import { apiFetch } from './api'

// ---------------------------------------------------------------------------
// 公共参数类型
// ---------------------------------------------------------------------------

export interface BizDateRange {
  startDate: string            // YYYY-MM-DD
  endDate: string              // YYYY-MM-DD
  platform?: string            // tiktok | meta, 缺省 = 全部
  account_id?: string
}

// ---------------------------------------------------------------------------
// BIZ Campaigns (status / account_id from synced data)
// ---------------------------------------------------------------------------

export interface BizCampaign {
  id: number
  platform: string
  account_id: string
  campaign_id: string
  campaign_name: string
  objective: string
  buying_type: string
  status: string
  is_active: number
  raw_json: Record<string, unknown> | null
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

export interface BizOverview {
  total_spend: number
  total_revenue: number
  total_impressions: number
  total_clicks: number
  total_installs: number
  total_conversions: number
  total_registrations?: number
  /**
   * Attribution 数仓侧自报的 spend 总和。仅 source=blend/auto 返回。
   * normalized 端 spend>0 但 attribution_spend≈0 → 数仓未采集该账号广告事件，
   * 此时 total_revenue / avg_roas 不可信，前端应给出"无归因数据"警示。
   */
  attribution_spend?: number
  avg_ctr: number | null
  avg_cpc: number | null
  avg_cpm: number | null
  avg_cpi: number | null
  avg_cpa: number | null
  avg_roas: number | null
  /** 阶段 4 X3-filter：后端因当前应用未绑定账号 / 多账号未指定时返回的友好提示。 */
  _hint?: string
  /** 阶段 4 X3-filter：当前请求落在哪个 application。 */
  _application_id?: number
}

// ---------------------------------------------------------------------------
// Top Campaigns
// ---------------------------------------------------------------------------

export interface BizTopCampaign {
  platform: string
  account_id: string
  campaign_id: string
  campaign_name: string
  total_spend: number
  total_impressions: number
  total_clicks: number
  total_installs: number
  total_conversions: number
  total_registrations?: number
  total_revenue: number
  avg_roas: number | null
}

export interface TopCampaignsParams extends BizDateRange {
  metric?: string              // spend | revenue | clicks | roas …
  limit?: number
}

// ---------------------------------------------------------------------------
// Campaign Daily
// ---------------------------------------------------------------------------

export interface BizCampaignDaily {
  platform: string
  account_id: string
  campaign_id: string
  campaign_name: string
  stat_date: string
  spend: number
  impressions: number
  clicks: number
  installs: number
  conversions: number
  registrations?: number
  revenue: number
  ctr: number | null
  cpc: number | null
  cpm: number | null
  cpi: number | null
  cpa: number | null
  roas: number | null
}

export interface CampaignDailyParams extends BizDateRange {
  page?: number
  page_size?: number
  order_by?: string
  order_dir?: 'asc' | 'desc'
}

// ---------------------------------------------------------------------------
// Adgroup Daily
// ---------------------------------------------------------------------------

export interface BizAdgroupDaily {
  platform: string
  account_id: string
  campaign_id: string
  campaign_name: string
  adgroup_id: string
  adgroup_name: string
  stat_date: string
  spend: number
  impressions: number
  clicks: number
  installs: number
  conversions: number
  revenue: number
  ctr: number | null
  cpc: number | null
  cpm: number | null
  cpi: number | null
  cpa: number | null
  roas: number | null
}

export interface AdgroupDailyParams extends BizDateRange {
  name_filter?: string
  page?: number
  page_size?: number
  order_by?: string
  order_dir?: 'asc' | 'desc'
}

// ---------------------------------------------------------------------------
// Ad Daily
// ---------------------------------------------------------------------------

export interface BizAdDaily {
  platform: string
  account_id: string
  campaign_id: string
  campaign_name: string
  adgroup_id: string
  adgroup_name: string
  ad_id: string
  ad_name: string
  stat_date: string
  spend: number
  impressions: number
  clicks: number
  installs: number
  conversions: number
  revenue: number
  ctr: number | null
  cpc: number | null
  cpm: number | null
  cpi: number | null
  cpa: number | null
  roas: number | null
}

export interface AdDailyParams extends BizDateRange {
  name_filter?: string
  page?: number
  page_size?: number
  order_by?: string
  order_dir?: 'asc' | 'desc'
}

export interface PaginatedResult<T> {
  total: number
  list: T[]
  page: number
  page_size: number
}

// ---------------------------------------------------------------------------
// Aggregated types (grouped, no per-day split)
// ---------------------------------------------------------------------------

export interface AggRow {
  platform: string
  account_id: string
  status?: string
  budget?: number | null
  campaign_id: string
  campaign_name: string
  adgroup_id?: string
  adgroup_name?: string
  ad_id?: string
  ad_name?: string
  total_spend: number
  total_revenue: number
  total_impressions: number
  total_clicks: number
  total_installs: number
  total_conversions: number
  total_registrations?: number
  /** Attribution 数仓侧自报 spend；详见 BizOverview.attribution_spend 注释。 */
  attribution_spend?: number
  ctr: number | null
  cpc: number | null
  cpm: number | null
  cpi: number | null
  cpa: number | null
  roas: number | null
}

export interface AggParams extends BizDateRange {
  campaign_id?: string
  adgroup_id?: string
  order_by?: string
  order_dir?: 'asc' | 'desc'
}

// ---------------------------------------------------------------------------
// 内部工具
// ---------------------------------------------------------------------------

interface ApiResp<T> { code: number; message: string; data: T }

function qs(params: Record<string, string | number | undefined | null>): string {
  const parts: string[] = []
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== '') parts.push(`${k}=${encodeURIComponent(v)}`)
  }
  return parts.length ? `?${parts.join('&')}` : ''
}

// ---------------------------------------------------------------------------
// API 函数（唯一出口）
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// BIZ Adgroups (status / account_id from synced data)
// ---------------------------------------------------------------------------

export interface BizAdgroup {
  id: number
  platform: string
  account_id: string
  campaign_id: string
  adgroup_id: string
  adgroup_name: string
  status: string
  is_active: number
  raw_json: Record<string, unknown> | null
}

// ---------------------------------------------------------------------------
// BIZ Ads (status / account_id from synced data)
// ---------------------------------------------------------------------------

export interface BizAd {
  id: number
  platform: string
  account_id: string
  campaign_id: string
  adgroup_id: string
  ad_id: string
  ad_name: string
  status: string
  is_active: number
  raw_json: Record<string, unknown> | null
}

export async function updateBizEntityStatus(
  platform: string,
  entityType: 'campaign' | 'adgroup' | 'ad',
  entityId: string,
  status: string,
): Promise<void> {
  await apiFetch<ApiResp<unknown>>(
    `/api/biz/update-status${qs({ platform, entity_type: entityType, entity_id: entityId, status })}`,
    { method: 'POST' },
  )
}

export async function fetchBizAdgroups(platform?: string): Promise<BizAdgroup[]> {
  const r = await apiFetch<ApiResp<BizAdgroup[]>>(
    `/api/biz/adgroups${qs({ platform })}`,
  )
  return r.data
}

export async function fetchBizAds(platform?: string): Promise<BizAd[]> {
  const r = await apiFetch<ApiResp<BizAd[]>>(
    `/api/biz/ads${qs({ platform })}`,
  )
  return r.data
}

export async function fetchBizCampaigns(platform?: string): Promise<BizCampaign[]> {
  const r = await apiFetch<ApiResp<BizCampaign[]>>(
    `/api/biz/campaigns${qs({ platform })}`,
  )
  return r.data
}

export async function fetchBizOverview(p: BizDateRange): Promise<BizOverview> {
  const r = await apiFetch<ApiResp<BizOverview>>(
    `/api/biz/overview${qs({
      start_date: p.startDate,
      end_date: p.endDate,
      platform: p.platform,
      account_id: p.account_id,
    })}`,
  )
  return r.data
}

export async function fetchBizTopCampaigns(p: TopCampaignsParams): Promise<BizTopCampaign[]> {
  const r = await apiFetch<ApiResp<BizTopCampaign[]>>(
    `/api/biz/top-campaigns${qs({
      start_date: p.startDate,
      end_date: p.endDate,
      platform: p.platform,
      account_id: p.account_id,
      metric: p.metric,
      limit: p.limit,
    })}`,
  )
  return r.data
}

export async function fetchBizCampaignDaily(p: CampaignDailyParams): Promise<PaginatedResult<BizCampaignDaily>> {
  const r = await apiFetch<ApiResp<PaginatedResult<BizCampaignDaily>>>(
    `/api/biz/campaign-daily${qs({
      start_date: p.startDate,
      end_date: p.endDate,
      platform: p.platform,
      account_id: p.account_id,
      page: p.page,
      page_size: p.page_size,
      order_by: p.order_by,
      order_dir: p.order_dir,
    })}`,
  )
  return r.data
}

export async function fetchBizAdgroupDaily(p: AdgroupDailyParams): Promise<PaginatedResult<BizAdgroupDaily>> {
  const r = await apiFetch<ApiResp<PaginatedResult<BizAdgroupDaily>>>(
    `/api/biz/adgroup-daily${qs({
      start_date: p.startDate,
      end_date: p.endDate,
      platform: p.platform,
      account_id: p.account_id,
      name_filter: p.name_filter,
      page: p.page,
      page_size: p.page_size,
      order_by: p.order_by,
      order_dir: p.order_dir,
    })}`,
  )
  return r.data
}

export async function fetchBizAdDaily(p: AdDailyParams): Promise<PaginatedResult<BizAdDaily>> {
  const r = await apiFetch<ApiResp<PaginatedResult<BizAdDaily>>>(
    `/api/biz/ad-daily${qs({
      start_date: p.startDate,
      end_date: p.endDate,
      platform: p.platform,
      account_id: p.account_id,
      name_filter: p.name_filter,
      page: p.page,
      page_size: p.page_size,
      order_by: p.order_by,
      order_dir: p.order_dir,
    })}`,
  )
  return r.data
}

// ---------------------------------------------------------------------------
// Aggregated fetches (for hierarchical expand)
// ---------------------------------------------------------------------------

export async function fetchCampaignAgg(p: AggParams): Promise<AggRow[]> {
  const r = await apiFetch<ApiResp<AggRow[]>>(
    `/api/biz/campaign-agg${qs({
      start_date: p.startDate,
      end_date: p.endDate,
      platform: p.platform,
      account_id: p.account_id,
      order_by: p.order_by,
      order_dir: p.order_dir,
    })}`,
  )
  return r.data
}

export async function fetchAdgroupAgg(p: AggParams): Promise<AggRow[]> {
  const r = await apiFetch<ApiResp<AggRow[]>>(
    `/api/biz/adgroup-agg${qs({
      start_date: p.startDate,
      end_date: p.endDate,
      platform: p.platform,
      account_id: p.account_id,
      campaign_id: p.campaign_id,
      order_by: p.order_by,
      order_dir: p.order_dir,
    })}`,
  )
  return r.data
}

export async function fetchAdAgg(p: AggParams): Promise<AggRow[]> {
  const r = await apiFetch<ApiResp<AggRow[]>>(
    `/api/biz/ad-agg${qs({
      start_date: p.startDate,
      end_date: p.endDate,
      platform: p.platform,
      account_id: p.account_id,
      campaign_id: p.campaign_id,
      adgroup_id: p.adgroup_id,
      order_by: p.order_by,
      order_dir: p.order_dir,
    })}`,
  )
  return r.data
}

// ── 素材分析 ──

export interface CreativeItem {
  ad_id: string
  ad_name: string
  platform: string
  impressions: number
  clicks: number
  spend: number | null
  revenue: number | null
  installs: number
  conversions: number
  ctr: number | null
  roas: number | null
}

export interface CreativeOverview {
  total_creatives: number
  avg_ctr: number | null
  avg_completion_rate: number | null
  avg_roas: number | null
  total_spend: number
  total_revenue: number
}

export interface CreativeAnalysisData {
  overview: CreativeOverview
  top: CreativeItem[]
  low: CreativeItem[]
  list: CreativeItem[]
}

export async function fetchCreativeAnalysis(params: {
  startDate: string; endDate: string; platform?: string;
  minSpend?: number; topN?: number
}): Promise<CreativeAnalysisData> {
  const r = await apiFetch<ApiResp<CreativeAnalysisData>>(
    `/api/biz/creative-analysis${qs({
      start_date: params.startDate,
      end_date: params.endDate,
      platform: params.platform,
      min_spend: params.minSpend,
      top_n: params.topN,
    })}`,
  )
  return r.data
}


export interface ConsoleParams extends AggParams { q?: string; page?: number; page_size?: number }
export function fetchConsolePage(level: 'campaign' | 'adgroup' | 'ad', p: ConsoleParams): Promise<PaginatedResult<AggRow>> {
  return apiFetch<ApiResp<PaginatedResult<AggRow>>>(`/api/biz/console/${level}${qs({
    start_date: p.startDate, end_date: p.endDate, platform: p.platform, account_id: p.account_id,
    campaign_id: p.campaign_id, adgroup_id: p.adgroup_id, order_by: p.order_by, order_dir: p.order_dir,
    q: p.q, page: p.page, page_size: p.page_size,
  })}`).then(r => r.data)
}

export async function fetchConsoleChildren(level: 'adgroup' | 'ad', p: AggParams): Promise<AggRow[]> {
  const rows: AggRow[] = []
  let page = 1
  while (true) {
    const result = await fetchConsolePage(level, { ...p, page, page_size: 200 })
    rows.push(...result.list)
    if (!result.list.length || rows.length >= result.total || result.page < page) return rows
    page++
  }
}
