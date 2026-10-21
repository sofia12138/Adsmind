import { useQuery } from '@tanstack/react-query'
import {
  fetchBizOverview,
  fetchBizTopCampaigns,
  fetchBizCampaignDaily,
  fetchBizCampaigns,
  fetchBizAdgroups,
  fetchBizAds,
  fetchBizAdgroupDaily,
  fetchBizAdDaily,
  type BizDateRange,
  type TopCampaignsParams,
  type CampaignDailyParams,
  type AdgroupDailyParams,
  type AdDailyParams,
  type BizOverview,
  type BizTopCampaign,
  type BizCampaignDaily,
  type BizAdgroupDaily,
  type BizAdDaily,
  type BizCampaign,
  type BizAdgroup,
  type BizAd,
  type PaginatedResult,
} from '@/services/biz'

const DEFAULT_START = '2025-01-01'
const DEFAULT_END   = '2026-12-31'

function defaults(p?: Partial<BizDateRange>): BizDateRange {
  return {
    startDate: p?.startDate ?? DEFAULT_START,
    endDate:   p?.endDate   ?? DEFAULT_END,
    platform:  p?.platform,
    account_id: p?.account_id,
  }
}

// ---------------------------------------------------------------------------
// useBizOverview
// ---------------------------------------------------------------------------

export function useBizOverview(params?: Partial<BizDateRange>) {
  const p = defaults(params)
  return useQuery<BizOverview>({
    queryKey: ['biz', 'overview', p.startDate, p.endDate, p.platform, p.account_id],
    queryFn: () => fetchBizOverview(p),
  })
}

// ---------------------------------------------------------------------------
// useBizTopCampaigns
// ---------------------------------------------------------------------------

export function useBizTopCampaigns(params?: Partial<TopCampaignsParams>) {
  const p: TopCampaignsParams = {
    ...defaults(params),
    metric: params?.metric,
    limit:  params?.limit,
  }
  return useQuery<BizTopCampaign[]>({
    queryKey: ['biz', 'top-campaigns', p.startDate, p.endDate, p.platform, p.metric, p.limit],
    queryFn: () => fetchBizTopCampaigns(p),
  })
}

// ---------------------------------------------------------------------------
// useBizCampaigns — campaign list with status from BIZ DB
// ---------------------------------------------------------------------------

export function useBizCampaigns(platform?: string) {
  return useQuery<BizCampaign[]>({
    queryKey: ['biz', 'campaigns', platform],
    queryFn: () => fetchBizCampaigns(platform),
    staleTime: 30_000,
  })
}

export function useBizAdgroups(platform?: string) {
  return useQuery<BizAdgroup[]>({
    queryKey: ['biz', 'adgroups', platform],
    queryFn: () => fetchBizAdgroups(platform),
    staleTime: 30_000,
  })
}

export function useBizAds(platform?: string) {
  return useQuery<BizAd[]>({
    queryKey: ['biz', 'ads', platform],
    queryFn: () => fetchBizAds(platform),
    staleTime: 30_000,
  })
}

// ---------------------------------------------------------------------------
// useCampaignDaily
// ---------------------------------------------------------------------------

export function useCampaignDaily(params?: Partial<CampaignDailyParams>) {
  const p: CampaignDailyParams = {
    ...defaults(params),
    page:      params?.page,
    page_size: params?.page_size,
    order_by:  params?.order_by,
    order_dir: params?.order_dir,
  }
  return useQuery<PaginatedResult<BizCampaignDaily>>({
    queryKey: ['biz', 'campaign-daily', p.startDate, p.endDate, p.platform, p.page, p.page_size, p.order_by, p.order_dir],
    queryFn: () => fetchBizCampaignDaily(p),
  })
}

// ---------------------------------------------------------------------------
// useAdgroupDaily
// ---------------------------------------------------------------------------

export function useAdgroupDaily(params?: Partial<AdgroupDailyParams>) {
  const p: AdgroupDailyParams = {
    ...defaults(params),
    name_filter: params?.name_filter,
    page:        params?.page,
    page_size:   params?.page_size,
    order_by:    params?.order_by,
    order_dir:   params?.order_dir,
  }
  return useQuery<PaginatedResult<BizAdgroupDaily>>({
    queryKey: ['biz', 'adgroup-daily', p.startDate, p.endDate, p.platform, p.name_filter, p.page, p.page_size, p.order_by, p.order_dir],
    queryFn: () => fetchBizAdgroupDaily(p),
  })
}

// ---------------------------------------------------------------------------
// useAdDaily
// ---------------------------------------------------------------------------

export function useAdDaily(params?: Partial<AdDailyParams>) {
  const p: AdDailyParams = {
    ...defaults(params),
    name_filter: params?.name_filter,
    page:        params?.page,
    page_size:   params?.page_size,
    order_by:    params?.order_by,
    order_dir:   params?.order_dir,
  }
  return useQuery<PaginatedResult<BizAdDaily>>({
    queryKey: ['biz', 'ad-daily', p.startDate, p.endDate, p.platform, p.name_filter, p.page, p.page_size, p.order_by, p.order_dir],
    queryFn: () => fetchBizAdDaily(p),
  })
}
