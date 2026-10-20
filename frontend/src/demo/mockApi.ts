/**
 * 浏览器内 /api 替身。数据全部虚构，状态只留在本次页面内存里。
 */
import { DEMO_PANELS } from './constants'

type Json = Record<string, unknown>

const TENANT = {
  id: 1,
  slug: 'lumen-demo',
  name: 'Lumen Demo',
  plan_id: 'internal',
  is_internal: true,
  enabled_plugins: [
    'core_ads', 'drama', 'optimizer', 'designer_performance',
    'attribution_metis', 'returned_conversion', 'ops_panel_polardb', 'ai_studio',
  ],
}

interface AdUnit {
  id: string
  name: string
  status: string
}

interface AdGroup {
  id: string
  name: string
  status: string
  budget: number
  ads: AdUnit[]
}

interface Campaign {
  platform: 'tiktok' | 'meta'
  accountId: string
  accountName: string
  id: string
  name: string
  objective: string
  status: string
  budget: number
  baseSpend: number
  roas: number
  adgroups: AdGroup[]
}

const CAMPAIGNS: Campaign[] = [
  camp('tiktok', '7482910033445566', 'Lumen US · TikTok', '18021001', 'US · 女频复仇 · 素材包 A', 'APP_PROMOTION', 'ENABLE', 800, 620, 2.24, [
    group('ag-18021001-1', 'US 18-34 女 · 兴趣', 'ENABLE', 450, [
      ad('ad-18021001-1', '复仇预告 15s · 竖版', 'ENABLE'),
      ad('ad-18021001-2', '名场面切片 9s', 'ENABLE'),
    ]),
    group('ag-18021001-2', 'US 再营销 · 7日观看', 'ENABLE', 350, [
      ad('ad-18021001-3', '评论截图 + 剧名', 'ENABLE'),
    ]),
  ]),
  camp('tiktok', '7482910033445566', 'Lumen US · TikTok', '18021002', 'UK · 甜宠 · 放量测试', 'APP_PROMOTION', 'ENABLE', 400, 310, 0.74, [
    group('ag-18021002-1', 'UK 宽定向', 'ENABLE', 400, [
      ad('ad-18021002-1', '甜宠对白 12s', 'ENABLE'),
      ad('ad-18021002-2', '封面静态轮播', 'DISABLE'),
    ]),
  ]),
  camp('tiktok', '7482910088776655', 'Lumen LATAM · TikTok', '18021003', 'BR · 悬疑 · Spark', 'APP_PROMOTION', 'ENABLE', 280, 210, 1.86, [
    group('ag-18021003-1', 'BR 葡语 · 安卓', 'ENABLE', 280, [
      ad('ad-18021003-1', '悬疑开场 20s', 'ENABLE'),
    ]),
  ]),
  camp('meta', '902184331122', 'Lumen Global · Meta', '23881001', 'Global · ASC · 剧集包', 'OUTCOME_APP_PROMOTION', 'ACTIVE', 1200, 740, 1.81, [
    group('as-23881001-1', 'ASC 自动版位', 'ACTIVE', 1200, [
      ad('mad-23881001-1', '多语言片花 15s', 'ACTIVE'),
      ad('mad-23881001-2', '字幕版 30s', 'ACTIVE'),
    ]),
  ]),
  camp('meta', '902184331122', 'Lumen Global · Meta', '23881002', 'US · 兴趣 · 付费墙', 'OUTCOME_SALES', 'ACTIVE', 500, 190, 0.68, [
    group('as-23881002-1', 'US 女频兴趣', 'ACTIVE', 320, [
      ad('mad-23881002-1', '付费墙截图', 'ACTIVE'),
    ]),
    group('as-23881002-2', 'US Lookalike 1%', 'PAUSED', 180, [
      ad('mad-23881002-2', '口播推荐', 'PAUSED'),
    ]),
  ]),
  camp('meta', '902184339900', 'Lumen SEA · Meta', '23881003', 'ID/PH · 短剧合集', 'OUTCOME_APP_PROMOTION', 'ACTIVE', 360, 260, 1.42, [
    group('as-23881003-1', '东南亚安卓', 'ACTIVE', 360, [
      ad('mad-23881003-1', '合集封面轮播', 'ACTIVE'),
    ]),
  ]),
]

function camp(
  platform: Campaign['platform'],
  accountId: string,
  accountName: string,
  id: string,
  name: string,
  objective: string,
  status: string,
  budget: number,
  baseSpend: number,
  roas: number,
  adgroups: AdGroup[],
): Campaign {
  return { platform, accountId, accountName, id, name, objective, status, budget, baseSpend, roas, adgroups }
}

function group(id: string, name: string, status: string, budget: number, ads: AdUnit[]): AdGroup {
  return { id, name, status, budget, ads }
}

function ad(id: string, name: string, status: string): AdUnit {
  return { id, name, status }
}

function utcDay(offset: number): string {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() + offset)
  return d.toISOString().slice(0, 10)
}

function hash01(seed: string): number {
  let h = 2166136261
  for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619)
  return (h >>> 0) / 4294967296
}

function round2(n: number): number {
  return Math.round(n * 100) / 100
}

const DAY_OFFSETS = Array.from({ length: 30 }, (_, i) => i - 29)

interface DailyPoint {
  platform: 'tiktok' | 'meta'
  account_id: string
  campaign_id: string
  campaign_name: string
  adgroup_id: string
  adgroup_name: string
  ad_id: string
  ad_name: string
  stat_date: string
  spend: number
  revenue: number
  impressions: number
  clicks: number
  installs: number
  conversions: number
  registrations: number
}

function buildDaily(): DailyPoint[] {
  const rows: DailyPoint[] = []
  for (const c of CAMPAIGNS) {
    const groups = c.adgroups.length || 1
    for (const offset of DAY_OFFSETS) {
      const date = utcDay(offset)
      const wave = 0.72 + hash01(`${c.id}|${date}`) * 0.56
      const spend = round2(c.baseSpend * wave)
      const revenue = round2(spend * c.roas * (0.9 + hash01(`${c.id}|rev|${date}`) * 0.2))
      const impressions = Math.round(spend * (90 + hash01(`${c.id}|imp|${date}`) * 40))
      const clicks = Math.round(impressions * (0.012 + hash01(`${c.id}|clk|${date}`) * 0.01))
      const installs = Math.round(clicks * (0.18 + hash01(`${c.id}|ins|${date}`) * 0.08))
      const registrations = Math.round(installs * 0.62)
      const conversions = Math.round(registrations * 0.22)
      c.adgroups.forEach(g => {
        const share = 1 / groups
        const gSpend = round2(spend * share)
        g.ads.forEach(a => {
          const aShare = 1 / g.ads.length
          rows.push({
            platform: c.platform,
            account_id: c.accountId,
            campaign_id: c.id,
            campaign_name: c.name,
            adgroup_id: g.id,
            adgroup_name: g.name,
            ad_id: a.id,
            ad_name: a.name,
            stat_date: date,
            spend: round2(gSpend * aShare),
            revenue: round2(revenue * share * aShare),
            impressions: Math.round(impressions * share * aShare),
            clicks: Math.round(clicks * share * aShare),
            installs: Math.round(installs * share * aShare),
            conversions: Math.round(conversions * share * aShare),
            registrations: Math.round(registrations * share * aShare),
          })
        })
      })
    }
  }
  return rows
}

const DAILY = buildDaily()

function inRange(date: string, start?: string | null, end?: string | null) {
  if (start && date < start) return false
  if (end && date > end) return false
  return true
}

function filteredDaily(q: URLSearchParams) {
  const start = q.get('start_date')
  const end = q.get('end_date')
  const platform = q.get('platform')
  return DAILY.filter(r => {
    if (platform && r.platform !== platform) return false
    return inRange(r.stat_date, start, end)
  })
}

function sum(rows: DailyPoint[], key: keyof DailyPoint): number {
  return rows.reduce((s, r) => s + Number(r[key] || 0), 0)
}

function overviewOf(rows: DailyPoint[]) {
  const spend = round2(sum(rows, 'spend'))
  const revenue = round2(sum(rows, 'revenue'))
  const impressions = sum(rows, 'impressions')
  const clicks = sum(rows, 'clicks')
  const installs = sum(rows, 'installs')
  const conversions = sum(rows, 'conversions')
  const registrations = sum(rows, 'registrations')
  return {
    total_spend: spend,
    total_revenue: revenue,
    total_impressions: impressions,
    total_clicks: clicks,
    total_installs: installs,
    total_conversions: conversions,
    total_registrations: registrations,
    attribution_spend: round2(spend * 0.97),
    avg_ctr: impressions ? clicks / impressions : null,
    avg_cpc: clicks ? round2(spend / clicks) : null,
    avg_cpm: impressions ? round2((spend / impressions) * 1000) : null,
    avg_cpi: installs ? round2(spend / installs) : null,
    avg_cpa: conversions ? round2(spend / conversions) : null,
    avg_roas: spend ? round2(revenue / spend) : null,
  }
}

interface AggRow {
  platform: string
  account_id: string
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
  total_registrations: number
  attribution_spend: number
  ctr: number | null
  cpc: number | null
  cpm: number | null
  cpi: number | null
  cpa: number | null
  roas: number | null
}

function aggFrom(rows: DailyPoint[], level: 'campaign' | 'adgroup' | 'ad'): AggRow[] {
  const map = new Map<string, AggRow>()
  for (const r of rows) {
    const key = level === 'campaign' ? r.campaign_id : level === 'adgroup' ? r.adgroup_id : r.ad_id
    const cur = map.get(key) ?? {
      platform: r.platform,
      account_id: r.account_id,
      campaign_id: r.campaign_id,
      campaign_name: r.campaign_name,
      adgroup_id: level === 'campaign' ? undefined : r.adgroup_id,
      adgroup_name: level === 'campaign' ? undefined : r.adgroup_name,
      ad_id: level === 'ad' ? r.ad_id : undefined,
      ad_name: level === 'ad' ? r.ad_name : undefined,
      total_spend: 0,
      total_revenue: 0,
      total_impressions: 0,
      total_clicks: 0,
      total_installs: 0,
      total_conversions: 0,
      total_registrations: 0,
      attribution_spend: 0,
      ctr: null,
      cpc: null,
      cpm: null,
      cpi: null,
      cpa: null,
      roas: null,
    }
    cur.total_spend = round2(cur.total_spend + r.spend)
    cur.total_revenue = round2(cur.total_revenue + r.revenue)
    cur.total_impressions += r.impressions
    cur.total_clicks += r.clicks
    cur.total_installs += r.installs
    cur.total_conversions += r.conversions
    cur.total_registrations += r.registrations
    map.set(key, cur)
  }
  return Array.from(map.values()).map(row => {
    const spend = row.total_spend
    const revenue = row.total_revenue
    const impressions = row.total_impressions
    const clicks = row.total_clicks
    const installs = row.total_installs
    const conversions = row.total_conversions
    return {
      ...row,
      attribution_spend: round2(spend * 0.97),
      ctr: impressions ? clicks / impressions : null,
      cpc: clicks ? round2(spend / clicks) : null,
      cpm: impressions ? round2((spend / impressions) * 1000) : null,
      cpi: installs ? round2(spend / installs) : null,
      cpa: conversions ? round2(spend / conversions) : null,
      roas: spend ? round2(revenue / spend) : null,
    }
  })
}

function ok<T>(data: T, extra?: Json) {
  return { code: 0, message: 'ok', data, ...extra }
}

const APPLICATIONS = [
  {
    id: 1,
    tenant_id: 1,
    slug: 'lumen-shorts',
    name: 'Lumen Shorts',
    description: '演示用短剧应用，未绑定真实商店。',
    platform_type: 'multi',
    bundle_id: 'com.lumen.shorts.demo',
    industry: '短剧',
    status: 'active',
    is_default: true,
    settings: {},
    created_at: '2026-03-02T08:00:00Z',
    updated_at: '2026-10-18T08:00:00Z',
  },
  {
    id: 2,
    tenant_id: 1,
    slug: 'lumen-web',
    name: 'Lumen Web',
    description: '演示用落地页应用。',
    platform_type: 'web',
    industry: '短剧',
    status: 'active',
    is_default: false,
    settings: {},
    created_at: '2026-06-11T08:00:00Z',
    updated_at: '2026-10-12T08:00:00Z',
  },
]

const ACCOUNTS = [
  {
    id: 11,
    platform: 'tiktok',
    account_id: '7482910033445566',
    account_name: 'Lumen US · TikTok',
    currency: 'USD',
    timezone: 'America/Los_Angeles',
    status: 'ACTIVE',
    access_token_masked: '演示数据',
    app_id: 'demo-app',
    app_secret_masked: '演示数据',
    is_default: 1,
    last_synced_at: new Date().toISOString(),
    created_at: '2026-02-01T00:00:00Z',
    updated_at: new Date().toISOString(),
    application_id: 1,
  },
  {
    id: 12,
    platform: 'tiktok',
    account_id: '7482910088776655',
    account_name: 'Lumen LATAM · TikTok',
    currency: 'USD',
    timezone: 'America/Sao_Paulo',
    status: 'ACTIVE',
    access_token_masked: '演示数据',
    app_id: 'demo-app',
    app_secret_masked: '演示数据',
    is_default: 0,
    last_synced_at: new Date().toISOString(),
    created_at: '2026-04-01T00:00:00Z',
    updated_at: new Date().toISOString(),
    application_id: 1,
  },
  {
    id: 21,
    platform: 'meta',
    account_id: '902184331122',
    account_name: 'Lumen Global · Meta',
    currency: 'USD',
    timezone: 'America/Los_Angeles',
    status: 'ACTIVE',
    access_token_masked: '演示数据',
    app_id: 'demo-app',
    app_secret_masked: '演示数据',
    is_default: 1,
    last_synced_at: new Date().toISOString(),
    created_at: '2026-02-01T00:00:00Z',
    updated_at: new Date().toISOString(),
    application_id: 1,
  },
  {
    id: 22,
    platform: 'meta',
    account_id: '902184339900',
    account_name: 'Lumen SEA · Meta',
    currency: 'USD',
    timezone: 'Asia/Jakarta',
    status: 'ACTIVE',
    access_token_masked: '演示数据',
    app_id: 'demo-app',
    app_secret_masked: '演示数据',
    is_default: 0,
    last_synced_at: new Date().toISOString(),
    created_at: '2026-05-01T00:00:00Z',
    updated_at: new Date().toISOString(),
    application_id: 1,
  },
]

const TEMPLATES = [
  {
    id: 'tpl-tt-w2a',
    name: 'TikTok Web to App · 英语女频',
    platform: 'tiktok',
    template_type: 'tiktok_web_to_app',
    template_subtype: 'web_to_app',
    is_builtin: true,
    is_system: true,
    is_editable: false,
    delivery_languages: ['en', 'es', 'pt'],
    default_delivery_language: 'en',
    created_at: '2026-01-15T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
  },
  {
    id: 'tpl-tt-minis',
    name: 'TikTok Minis · 剧集推广',
    platform: 'tiktok',
    template_type: 'tiktok_minis',
    is_builtin: true,
    is_system: false,
    is_editable: true,
    delivery_languages: ['en'],
    default_delivery_language: 'en',
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-08-20T00:00:00Z',
  },
  {
    id: 'tpl-meta-asc',
    name: 'Meta ASC · 应用安装',
    platform: 'meta',
    template_type: 'meta_asc',
    is_builtin: false,
    is_system: false,
    is_editable: true,
    delivery_languages: ['en', 'id'],
    default_delivery_language: 'en',
    created_at: '2026-04-12T00:00:00Z',
    updated_at: '2026-10-02T00:00:00Z',
  },
]

const USERS = [
  { id: 1, username: 'demo.owner', role: 'super_admin', display_name: '演示负责人', assigned_accounts: [], email: 'owner@demo.invalid' },
  { id: 2, username: 'demo.optimizer', role: 'optimizer', display_name: '林可', assigned_accounts: ['7482910033445566'], email: 'optimizer@demo.invalid' },
  { id: 3, username: 'demo.designer', role: 'designer', display_name: '周宁', assigned_accounts: [], email: 'designer@demo.invalid' },
  { id: 4, username: 'demo.analyst', role: 'analyst', display_name: '陈予', assigned_accounts: [], email: 'analyst@demo.invalid' },
]

const MEMBERS = [
  { tenant_id: 1, user_id: 1, role: 'owner', joined_at: '2026-01-08T00:00:00Z', username: 'demo.owner', display_name: '演示负责人' },
  { tenant_id: 1, user_id: 2, role: 'admin', joined_at: '2026-02-14T00:00:00Z', username: 'demo.optimizer', display_name: '林可' },
  { tenant_id: 1, user_id: 3, role: 'member', joined_at: '2026-05-03T00:00:00Z', username: 'demo.designer', display_name: '周宁' },
]

const MATERIALS = [
  {
    id: 501,
    advertiser_id: '7482910033445566',
    local_file_name: 'revenge-trailer-15s.mp4',
    file_size_bytes: 18_400_000,
    duration_sec: 15,
    upload_channel: 'demo',
    tiktok_video_id: 'v-demo-501',
    tiktok_file_name: 'revenge-trailer-15s.mp4',
    tiktok_url: '',
    tiktok_width: 1080,
    tiktok_height: 1920,
    tiktok_format: 'mp4',
    upload_status: 'success',
    error_code: null,
    error_message: null,
    can_use_for_ad: true,
    ad_usage_note: '演示素材，无真实视频文件',
    created_by: 'demo.designer',
    created_at: '2026-10-12T04:00:00Z',
    updated_at: '2026-10-12T04:02:00Z',
  },
  {
    id: 502,
    advertiser_id: '7482910033445566',
    local_file_name: 'sweet-dialogue-12s.mp4',
    file_size_bytes: 12_200_000,
    duration_sec: 12,
    upload_channel: 'demo',
    tiktok_video_id: 'v-demo-502',
    tiktok_file_name: 'sweet-dialogue-12s.mp4',
    tiktok_url: '',
    tiktok_width: 1080,
    tiktok_height: 1920,
    tiktok_format: 'mp4',
    upload_status: 'success',
    error_code: null,
    error_message: null,
    can_use_for_ad: true,
    ad_usage_note: '演示素材，无真实视频文件',
    created_by: 'demo.designer',
    created_at: '2026-10-16T09:00:00Z',
    updated_at: '2026-10-16T09:01:00Z',
  },
]

let insight = { roi: { min: 0.1, low: 0.8, target: 1.2, high: 2.0 } }

function panelsPayload() {
  return DEMO_PANELS.map((key, i) => ({
    id: i + 1,
    panel_key: key,
    panel_name: key,
    panel_group: 'demo',
    route_path: '/',
    sort_order: i,
    is_enabled: 1,
  }))
}

function bizCampaigns(platform?: string | null) {
  return CAMPAIGNS.filter(c => !platform || c.platform === platform).map((c, i) => ({
    id: i + 1,
    platform: c.platform,
    account_id: c.accountId,
    campaign_id: c.id,
    campaign_name: c.name,
    objective: c.objective,
    buying_type: 'AUCTION',
    status: c.status,
    is_active: c.status === 'ENABLE' || c.status === 'ACTIVE' ? 1 : 0,
    raw_json: { budget: c.budget, daily_budget: c.budget },
  }))
}

function bizAdgroups(platform?: string | null) {
  const rows = []
  let i = 1
  for (const c of CAMPAIGNS) {
    if (platform && c.platform !== platform) continue
    for (const g of c.adgroups) {
      rows.push({
        id: i++,
        platform: c.platform,
        account_id: c.accountId,
        campaign_id: c.id,
        adgroup_id: g.id,
        adgroup_name: g.name,
        status: g.status,
        is_active: g.status === 'ENABLE' || g.status === 'ACTIVE' ? 1 : 0,
        raw_json: { budget: g.budget, daily_budget: g.budget },
      })
    }
  }
  return rows
}

function bizAds(platform?: string | null) {
  const rows = []
  let i = 1
  for (const c of CAMPAIGNS) {
    if (platform && c.platform !== platform) continue
    for (const g of c.adgroups) {
      for (const a of g.ads) {
        rows.push({
          id: i++,
          platform: c.platform,
          account_id: c.accountId,
          campaign_id: c.id,
          adgroup_id: g.id,
          ad_id: a.id,
          ad_name: a.name,
          status: a.status,
          is_active: a.status === 'ENABLE' || a.status === 'ACTIVE' ? 1 : 0,
          raw_json: null,
        })
      }
    }
  }
  return rows
}

function findEntity(kind: string, id: string) {
  for (const c of CAMPAIGNS) {
    if (kind === 'campaign' && c.id === id) return c
    for (const g of c.adgroups) {
      if (kind === 'adgroup' && g.id === id) return g
      for (const a of g.ads) {
        if (kind === 'ad' && a.id === id) return a
      }
    }
  }
  return null
}

function dailyList(q: URLSearchParams, level: 'campaign' | 'adgroup' | 'ad') {
  let rows = filteredDaily(q)
  const campaignId = q.get('campaign_id')
  const adgroupId = q.get('adgroup_id')
  if (campaignId) rows = rows.filter(r => r.campaign_id === campaignId)
  if (adgroupId) rows = rows.filter(r => r.adgroup_id === adgroupId)
  const page = Number(q.get('page') || 1)
  const pageSize = Number(q.get('page_size') || 50)
  const mapped = rows.map(r => ({
    platform: r.platform,
    account_id: r.account_id,
    campaign_id: r.campaign_id,
    campaign_name: r.campaign_name,
    adgroup_id: level === 'campaign' ? undefined : r.adgroup_id,
    adgroup_name: level === 'campaign' ? undefined : r.adgroup_name,
    ad_id: level === 'ad' ? r.ad_id : undefined,
    ad_name: level === 'ad' ? r.ad_name : undefined,
    stat_date: r.stat_date,
    spend: r.spend,
    impressions: r.impressions,
    clicks: r.clicks,
    installs: r.installs,
    conversions: r.conversions,
    registrations: r.registrations,
    revenue: r.revenue,
    ctr: r.impressions ? r.clicks / r.impressions : null,
    cpc: r.clicks ? round2(r.spend / r.clicks) : null,
    cpm: r.impressions ? round2((r.spend / r.impressions) * 1000) : null,
    cpi: r.installs ? round2(r.spend / r.installs) : null,
    cpa: r.conversions ? round2(r.spend / r.conversions) : null,
    roas: r.spend ? round2(r.revenue / r.spend) : null,
  }))
  const start = (page - 1) * pageSize
  return {
    total: mapped.length,
    list: mapped.slice(start, start + pageSize),
    page,
    page_size: pageSize,
  }
}

function topCampaigns(q: URLSearchParams) {
  const limit = Number(q.get('limit') || 10)
  return aggFrom(filteredDaily(q), 'campaign')
    .map(r => ({
      platform: r.platform,
      account_id: r.account_id,
      campaign_id: r.campaign_id,
      campaign_name: r.campaign_name,
      total_spend: r.total_spend,
      total_impressions: r.total_impressions,
      total_clicks: r.total_clicks,
      total_installs: r.total_installs,
      total_conversions: r.total_conversions,
      total_registrations: r.total_registrations,
      total_revenue: r.total_revenue,
      avg_roas: r.roas,
    }))
    .sort((a, b) => Number(b.total_spend) - Number(a.total_spend))
    .slice(0, limit)
}

function creativeAnalysis(q: URLSearchParams) {
  const rows = aggFrom(filteredDaily(q), 'ad').map(r => ({
    ad_id: String(r.ad_id),
    ad_name: String(r.ad_name),
    platform: String(r.platform),
    impressions: Number(r.total_impressions),
    clicks: Number(r.total_clicks),
    spend: Number(r.total_spend),
    revenue: Number(r.total_revenue),
    installs: Number(r.total_installs),
    conversions: Number(r.total_conversions),
    ctr: r.ctr as number | null,
    roas: r.roas as number | null,
  }))
  const ranked = [...rows].sort((a, b) => (b.roas ?? 0) - (a.roas ?? 0))
  const spend = rows.reduce((s, r) => s + (r.spend ?? 0), 0)
  const revenue = rows.reduce((s, r) => s + (r.revenue ?? 0), 0)
  return {
    overview: {
      total_creatives: rows.length,
      avg_ctr: rows.length ? rows.reduce((s, r) => s + (r.ctr ?? 0), 0) / rows.length : null,
      avg_completion_rate: 0.41,
      avg_roas: spend ? round2(revenue / spend) : null,
      total_spend: round2(spend),
      total_revenue: round2(revenue),
    },
    top: ranked.slice(0, 5),
    low: [...ranked].reverse().slice(0, 5),
    list: ranked,
  }
}

function availability(supported = true) {
  const field = { supported, has_nonzero_data: supported }
  return {
    registrations_returned: field,
    purchase_value_returned: field,
    purchase_count_returned: field,
    subscribe_value_returned: field,
    subscribe_count_returned: field,
    d1_value_returned: field,
    d0_registrations_returned: field,
    d0_purchase_value_returned: field,
    d0_subscribe_value_returned: field,
  }
}

function returnedSummary(rows: DailyPoint[]) {
  const spend = round2(sum(rows, 'spend'))
  const value = round2(sum(rows, 'revenue') * 0.92)
  const regs = sum(rows, 'registrations')
  return {
    spend,
    impressions: sum(rows, 'impressions'),
    clicks: sum(rows, 'clicks'),
    installs: sum(rows, 'installs'),
    registrations_returned: regs,
    purchase_value_returned: round2(value * 0.7),
    purchase_count_returned: Math.round(regs * 0.08),
    subscribe_value_returned: round2(value * 0.3),
    subscribe_count_returned: Math.round(regs * 0.03),
    total_value_returned: value,
    cumulative_roi_returned: spend ? round2(value / spend) : 0,
    d0_roi_returned: spend ? round2((value * 0.46) / spend) : 0,
    d0_roi_is_fallback: false,
    d1_value_returned: round2(value * 0.18),
    d1_roi_returned: spend ? round2((value * 0.18) / spend) : 0,
    d0_registrations_returned: Math.round(regs * 0.7),
    d0_purchase_value_returned: round2(value * 0.32),
    d0_subscribe_value_returned: round2(value * 0.14),
  }
}

function opsRows(q: URLSearchParams) {
  const start = q.get('start_date') || utcDay(-7)
  const end = q.get('end_date') || utcDay(0)
  const days: string[] = []
  const cursor = new Date(`${start}T00:00:00Z`)
  const last = new Date(`${end}T00:00:00Z`)
  while (cursor <= last && days.length < 40) {
    days.push(cursor.toISOString().slice(0, 10))
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return days.map(date => {
    const n = 0.85 + hash01(date) * 0.3
    const spend = round2(4200 * n)
    const iosSub = round2(980 * n)
    const iosIap = round2(240 * n)
    const andSub = round2(760 * n)
    const andIap = round2(310 * n)
    return {
      date,
      revenue_source: 'intraday',
      new_register_uv: Math.round(1800 * n),
      new_active_uv: Math.round(2400 * n),
      active_uv: Math.round(18600 * n),
      d1_retained_uv: Math.round(920 * n),
      d7_retained_uv: Math.round(410 * n),
      d30_retained_uv: Math.round(160 * n),
      total_payer_uv: Math.round(640 * n),
      ad_spend: spend,
      ios_subscribe_revenue: iosSub,
      ios_onetime_revenue: iosIap,
      ios_first_sub_orders: Math.round(90 * n),
      ios_repeat_sub_orders: Math.round(40 * n),
      ios_first_iap_orders: Math.round(30 * n),
      ios_repeat_iap_orders: Math.round(18 * n),
      ios_payer_uv: Math.round(260 * n),
      android_subscribe_revenue: andSub,
      android_onetime_revenue: andIap,
      android_first_sub_orders: Math.round(110 * n),
      android_repeat_sub_orders: Math.round(48 * n),
      android_first_iap_orders: Math.round(55 * n),
      android_repeat_iap_orders: Math.round(22 * n),
      android_payer_uv: Math.round(380 * n),
    }
  })
}

function hourly(q: URLSearchParams) {
  const start = q.get('start_date') || utcDay(-1)
  const end = q.get('end_date') || utcDay(0)
  const days: string[] = []
  const cursor = new Date(`${start}T00:00:00Z`)
  const last = new Date(`${end}T00:00:00Z`)
  while (cursor <= last && days.length < 31) {
    days.push(cursor.toISOString().slice(0, 10))
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return {
    days,
    series: days.map(ds => ({
      ds,
      hours: Array.from({ length: 24 }, (_, h) => {
        const wave = h >= 8 && h <= 23 ? 1 : 0.35
        const n = wave * (0.7 + hash01(`${ds}|${h}`) * 0.6)
        const total = round2(180 * n)
        return {
          h,
          orders: Math.round(26 * n),
          payer_uv: Math.round(18 * n),
          total_usd: total,
          android_usd: round2(total * 0.58),
          ios_usd: round2(total * 0.42),
          sub_usd: round2(total * 0.71),
          iap_usd: round2(total * 0.29),
        }
      }),
    })),
  }
}

function prdSummary() {
  const rows = DAILY
  const spend = round2(sum(rows, 'spend'))
  const revenue = round2(sum(rows, 'revenue'))
  return {
    register_count: sum(rows, 'registrations'),
    first_subscribe_count: 860,
    first_subscribe_amount: round2(revenue * 0.22),
    repeat_subscribe_count: 410,
    repeat_subscribe_amount: round2(revenue * 0.18),
    first_inapp_count: 540,
    first_inapp_amount: round2(revenue * 0.12),
    repeat_inapp_count: 220,
    repeat_inapp_amount: round2(revenue * 0.08),
    inapp_total_amount: round2(revenue * 0.2),
    subscribe_total_amount: round2(revenue * 0.4),
    recharge_total_amount: round2(revenue * 0.6),
    ad_cost_amount: spend,
    day1_roi: 0.46,
    day3_roi: 0.72,
    day7_roi: 0.98,
    day14_roi: 1.21,
    day30_roi: 1.48,
  }
}

function syncStatus() {
  const now = new Date().toISOString()
  const mod = { is_running: false, last_synced_at: now, last_error: null, last_range: '近 30 天 · 演示' }
  return { structure: mod, reports: mod, returned: mod }
}

const LANDING = [
  {
    id: 1, org_id: 'demo', name: '女频复仇 · 英语落地页', landing_page_url: 'https://demo.invalid/lp/revenge-en',
    product_name: 'Lumen Shorts', channel: 'tiktok', language: 'en', region_tags: ['US', 'UK'],
    remark: '演示落地页，链接不可访问', status: 'active', usage_count: 12, last_used_at: '2026-10-18T00:00:00Z',
    created_by: 'demo.owner', created_at: '2026-07-01T00:00:00Z', updated_at: '2026-10-18T00:00:00Z',
  },
  {
    id: 2, org_id: 'demo', name: '甜宠 · 葡语落地页', landing_page_url: 'https://demo.invalid/lp/sweet-pt',
    product_name: 'Lumen Shorts', channel: 'meta', language: 'pt', region_tags: ['BR'],
    remark: '演示落地页，链接不可访问', status: 'active', usage_count: 4, last_used_at: '2026-10-11T00:00:00Z',
    created_by: 'demo.optimizer', created_at: '2026-08-12T00:00:00Z', updated_at: '2026-10-11T00:00:00Z',
  },
]

const COPIES = [
  {
    id: 1, org_id: 'demo', name: '复仇钩子 · EN', primary_text: 'She came back for the ending they stole.',
    headline: 'Watch the full series', description: 'New episodes daily', language: 'en',
    product_name: 'Lumen Shorts', channel: 'tiktok', country_tags: ['US'], theme_tags: ['revenge'],
    remark: '', status: 'active', usage_count: 9, last_used_at: '2026-10-17T00:00:00Z',
    created_by: 'demo.designer', created_at: '2026-07-02T00:00:00Z', updated_at: '2026-10-17T00:00:00Z',
  },
]

const REGIONS = [
  {
    id: 1, org_id: 'demo', name: '英语核心市场', country_codes: ['US', 'UK', 'CA', 'AU'],
    country_count: 4, language_hint: 'en', remark: '', status: 'active', usage_count: 7,
    last_used_at: '2026-10-15T00:00:00Z', created_by: 'demo.optimizer',
    created_at: '2026-06-01T00:00:00Z', updated_at: '2026-10-15T00:00:00Z',
  },
  {
    id: 2, org_id: 'demo', name: '拉美葡西语', country_codes: ['BR', 'MX'],
    country_count: 2, language_hint: 'pt', remark: '', status: 'active', usage_count: 3,
    last_used_at: null, created_by: 'demo.optimizer',
    created_at: '2026-06-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
  },
]

function match(pathname: string, method: string, q: URLSearchParams): unknown {
  const p = pathname.replace(/\/+$/, '') || '/'

  if (p === '/api/users/login' && method === 'POST') {
    return {
      ok: true,
      token: 'demo-preview',
      role: 'super_admin',
      allowed_panels: DEMO_PANELS,
      user: { role: 'super_admin', username: 'demo.owner', display_name: '演示负责人' },
      tenant: TENANT,
    }
  }
  if (p === '/api/users/me') {
    return { email_verified: true, username: 'demo.owner', display_name: '演示负责人' }
  }
  if (p === '/api/users') return USERS
  if (p.startsWith('/api/users/')) return USERS[0]

  if (p === '/api/panels/my') {
    return { allowed_panels: DEMO_PANELS, role: 'super_admin', tenant: TENANT }
  }
  if (p === '/api/panels') return { panels: panelsPayload() }
  if (p.startsWith('/api/panels/roles/')) return { panel_keys: DEMO_PANELS }
  if (p.startsWith('/api/panels/users/')) {
    return { username: p.split('/').pop(), role: 'optimizer', has_override: false, allowed_panels: DEMO_PANELS }
  }

  if (p === '/api/applications') return APPLICATIONS
  if (p === '/api/applications/ad-accounts/available') return ACCOUNTS.filter(a => !a.application_id)
  const appAccount = p.match(/^\/api\/applications\/(\d+)\/ad-accounts$/)
  if (appAccount) return ACCOUNTS.filter(a => String(a.application_id) === appAccount[1])
  const appMembers = p.match(/^\/api\/applications\/(\d+)\/members$/)
  if (appMembers) {
    return [
      { application_id: Number(appMembers[1]), user_id: 1, role: 'owner', username: 'demo.owner', email: 'owner@demo.invalid', joined_at: '2026-01-08T00:00:00Z' },
      { application_id: Number(appMembers[1]), user_id: 2, role: 'editor', username: 'demo.optimizer', email: 'optimizer@demo.invalid', joined_at: '2026-02-14T00:00:00Z' },
    ]
  }
  const appOne = p.match(/^\/api\/applications\/(\d+)$/)
  if (appOne) return APPLICATIONS.find(a => String(a.id) === appOne[1]) ?? APPLICATIONS[0]

  if (p === '/api/quota/me') {
    return {
      tenant_id: 1,
      is_internal: true,
      plan_id: 'internal',
      plan_name: '内部演示',
      limits: { applications: 20, accounts: 50, members: 30, api_calls_monthly: 100000, ai_calls_monthly: 1000 },
      usage: { applications: APPLICATIONS.length, accounts: ACCOUNTS.length, members: MEMBERS.length },
      exhausted: { applications: false, accounts: false, members: false },
    }
  }
  if (p === '/api/insight/config') return insight

  if (p === '/api/biz/overview') return ok(overviewOf(filteredDaily(q)))
  if (p === '/api/biz/top-campaigns') return ok(topCampaigns(q))
  if (p === '/api/biz/campaign-daily') return ok(dailyList(q, 'campaign'))
  if (p === '/api/biz/adgroup-daily') return ok(dailyList(q, 'adgroup'))
  if (p === '/api/biz/ad-daily') return ok(dailyList(q, 'ad'))
  if (p === '/api/biz/campaigns') return ok(bizCampaigns(q.get('platform')))
  if (p === '/api/biz/adgroups') return ok(bizAdgroups(q.get('platform')))
  if (p === '/api/biz/ads') return ok(bizAds(q.get('platform')))
  if (p === '/api/biz/campaign-agg') return ok(aggFrom(filteredDaily(q), 'campaign'))
  if (p === '/api/biz/adgroup-agg') {
    let rows = filteredDaily(q)
    const id = q.get('campaign_id')
    if (id) rows = rows.filter(r => r.campaign_id === id)
    return ok(aggFrom(rows, 'adgroup'))
  }
  if (p === '/api/biz/ad-agg') {
    let rows = filteredDaily(q)
    const cid = q.get('campaign_id')
    const gid = q.get('adgroup_id')
    if (cid) rows = rows.filter(r => r.campaign_id === cid)
    if (gid) rows = rows.filter(r => r.adgroup_id === gid)
    return ok(aggFrom(rows, 'ad'))
  }
  if (p === '/api/biz/creative-analysis') return ok(creativeAnalysis(q))
  if (p === '/api/biz/update-status' && method === 'POST') {
    const entity = findEntity(q.get('entity_type') || '', q.get('entity_id') || '')
    if (entity && q.get('status')) entity.status = q.get('status') || entity.status
    return ok({ updated: true })
  }

  if (p === '/api/advertisers') {
    return {
      data: [
        { advertiser_id: '7482910033445566', advertiser_name: 'Lumen US · TikTok' },
        { advertiser_id: '7482910088776655', advertiser_name: 'Lumen LATAM · TikTok' },
      ],
    }
  }
  if (p === '/api/meta/accounts/info') {
    const id = q.get('ad_account_id') || '902184331122'
    const acc = ACCOUNTS.find(a => a.account_id === id)
    return { data: { id, name: acc?.account_name ?? 'Lumen Meta', currency: 'USD', timezone_name: 'America/Los_Angeles' } }
  }
  if (p === '/api/meta/accounts') {
    return { data: ACCOUNTS.filter(a => a.platform === 'meta').map(a => ({ id: a.account_id, name: a.account_name, account_status: 1 })) }
  }
  if (p === '/api/meta/campaigns') {
    return { data: CAMPAIGNS.filter(c => c.platform === 'meta').map(c => ({ id: c.id, name: c.name, status: c.status, daily_budget: c.budget })) }
  }
  if (p === '/api/meta/adsets') {
    return {
      data: CAMPAIGNS.filter(c => c.platform === 'meta').flatMap(c => c.adgroups.map(g => ({
        id: g.id, name: g.name, campaign_id: c.id, status: g.status, daily_budget: g.budget,
      }))),
    }
  }
  if (p === '/api/meta/reports/insights' || p.startsWith('/api/reports/')) {
    return { data: aggFrom(filteredDaily(q), 'campaign') }
  }
  if (p === '/api/meta/assets/pages') {
    return { data: [{ id: 'pg-demo-1', name: 'Lumen Shorts' }] }
  }
  if (p === '/api/meta/assets/pixels') {
    return { data: [{ id: 'px-demo-1', name: 'Lumen Web Pixel' }] }
  }
  if (p === '/api/meta/assets/list') return { data: [] }

  if (p === '/api/campaigns') {
    const list = CAMPAIGNS.filter(c => c.platform === 'tiktok').map(c => ({
      campaign_id: c.id, campaign_name: c.name, objective_type: c.objective, budget: c.budget, status: c.status,
    }))
    return {
      data: { list },
      normalized: list.map(c => ({ id: c.campaign_id, name: c.campaign_name, platform: 'tiktok', status: c.status, objective: c.objective_type, budget: c.budget })),
    }
  }
  if (p === '/api/adgroups') {
    return {
      data: {
        list: CAMPAIGNS.filter(c => c.platform === 'tiktok').flatMap(c => c.adgroups.map(g => ({
          adgroup_id: g.id, adgroup_name: g.name, campaign_id: c.id, status: g.status, budget: g.budget,
        }))),
      },
    }
  }

  if (p === '/api/sync/status' || p.startsWith('/api/sync/status/')) return ok(p === '/api/sync/status' ? syncStatus() : syncStatus().reports)
  if (p.startsWith('/api/sync/trigger')) return { code: 0, message: '演示模式未触发外部同步' }

  if (p === '/api/templates') return { data: TEMPLATES }
  const tplOne = p.match(/^\/api\/templates\/([^/]+)$/)
  if (tplOne && method === 'GET') return { data: TEMPLATES.find(t => t.id === decodeURIComponent(tplOne[1])) ?? TEMPLATES[0] }
  if (p === '/api/templates/launch') {
    return {
      data: {
        platform: 'demo',
        campaign: { success: false, error: '演示模式不会向 TikTok 或 Meta 提交广告' },
        adsets: [],
        adgroup: { success: false, skipped: true, reason: '演示模式不会向广告平台提交' },
        ads: [],
        summary: { total: 0, success: 0, fail: 0 },
      },
    }
  }

  if (p === '/api/creatives/videos' || p === '/api/creatives/images') {
    return {
      data: {
        list: p.endsWith('videos')
          ? MATERIALS.map(m => ({ video_id: m.tiktok_video_id, file_name: m.local_file_name, duration: m.duration_sec, width: m.tiktok_width, height: m.tiktok_height, format: 'mp4' }))
          : [{ image_id: 'img-demo-1', file_name: 'cover-revenge.png', width: 1080, height: 1920, format: 'png' }],
        page_info: { page: 1, page_size: 20, total_number: 2, total_page: 1 },
      },
    }
  }
  if (p === '/api/creatives/identities') {
    return { data: { identity_list: [{ identity_id: 'id-demo-1', identity_type: 'BC_AUTH_TT', display_name: 'Lumen Official' }] } }
  }
  if (p === '/api/creatives/pixels') {
    return {
      data: {
        pixel_list: [{
          pixel_id: 'px-tt-demo',
          pixel_name: 'Lumen TikTok Pixel',
          events: [
            { event_code: 'ON_WEB_REGISTER', event_name: '注册', event_type: 'standard' },
            { event_code: 'SHOPPING', event_name: '付费', event_type: 'standard' },
          ],
        }],
      },
    }
  }

  if (p === '/api/materials/tiktok/account-library') {
    return {
      data: {
        items: MATERIALS.map(m => ({
          video_id: m.tiktok_video_id,
          file_name: m.local_file_name,
          video_cover_url: '',
          duration: m.duration_sec,
          width: 1080,
          height: 1920,
          format: 'mp4',
          size: m.file_size_bytes,
          create_time: m.created_at,
          material_id: String(m.id),
        })),
        page: 1, page_size: 20, total: MATERIALS.length, total_page: 1, has_more: false,
      },
    }
  }
  if (p === '/api/materials/tiktok') {
    return { data: { items: MATERIALS, total: MATERIALS.length, page: 1, page_size: 20 } }
  }

  if (p === '/api/ad-accounts' || p === '/api/ad-accounts/') return { data: ACCOUNTS }
  const adAcc = p.match(/^\/api\/ad-accounts\/(\d+)$/)
  if (adAcc) return { data: ACCOUNTS.find(a => String(a.id) === adAcc[1]) ?? ACCOUNTS[0] }
  if (p === '/api/ad-accounts/verify') {
    return { valid: false, error: '演示模式不会校验真实广告平台令牌', accounts: [] }
  }

  if (p === '/api/ad-assets/landing-pages') return { data: LANDING }
  if (p === '/api/ad-assets/copy-packs') return { data: COPIES }
  if (p === '/api/ad-assets/region-groups') return { data: REGIONS }

  if (p === '/api/oplog') {
    const data = [
      { id: 1, time: '2026-10-19T16:20:00Z', user: 'demo.optimizer', action: '暂停广告组', target: 'UK 宽定向', detail: '演示日志', platform: 'tiktok', status: 'success' },
      { id: 2, time: '2026-10-18T11:02:00Z', user: 'demo.owner', action: '调整日预算', target: 'Global · ASC · 剧集包', detail: '1200 → 1500（未真正提交）', platform: 'meta', status: 'success' },
      { id: 3, time: '2026-10-17T09:40:00Z', user: 'demo.designer', action: '上传素材', target: 'revenge-trailer-15s.mp4', detail: '演示记录', platform: 'tiktok', status: 'success' },
    ]
    return { data, total: data.length }
  }

  if (p === '/api/ops/daily-stats') return { rows: opsRows(q), source: q.get('source') || 'auto' }
  if (p === '/api/ops/hourly-revenue') return hourly(q)

  if (p === '/api/bizdata/channel_report_summary') return { data: prdSummary() }

  if (p === '/api/drama/summary') {
    const rows = [
      { content_key: 'revenge-queen', drama_id: 'd-1001', drama_type: '女频', localized_drama_name: '归来的女王', spend: 18420, impressions: 2100000, clicks: 42000, installs: 6100, registrations: 3800, purchase_value: 41280, ctr: 0.02, cpc: 0.44, roas: 2.24, language_count: 3 },
      { content_key: 'sweet-office', drama_id: 'd-1002', drama_type: '甜宠', localized_drama_name: '合约恋人', spend: 9630, impressions: 980000, clicks: 15000, installs: 1900, registrations: 1100, purchase_value: 7120, ctr: 0.015, cpc: 0.64, roas: 0.74, language_count: 2 },
      { content_key: 'mystery-bay', drama_id: 'd-1008', drama_type: '悬疑', localized_drama_name: '海湾来信', spend: 6400, impressions: 720000, clicks: 12800, installs: 1700, registrations: 980, purchase_value: 11900, ctr: 0.018, cpc: 0.5, roas: 1.86, language_count: 2 },
    ]
    return { total: rows.length, page: 1, page_size: 50, rows }
  }
  if (p === '/api/drama/locale-breakdown') {
    return { rows: [
      { language_code: 'en', localized_drama_name: 'The Queen Returns', spend: 12000, clicks: 28000, installs: 4000, registrations: 2500, purchase_value: 28000, roas: 2.33 },
      { language_code: 'es', localized_drama_name: 'El regreso', spend: 4200, clicks: 9000, installs: 1400, registrations: 800, purchase_value: 8600, roas: 2.05 },
    ] }
  }
  if (p === '/api/drama/trend') {
    return { rows: DAY_OFFSETS.slice(-14).map(offset => ({ stat_date: utcDay(offset), spend: 600, purchase_value: 1100, roas: 1.8 })) }
  }

  if (p === '/api/optimizer-performance/summary') {
    const rows = [
      { optimizer_name: '林可', total_spend: 28400, spend_share: 0.62, avg_daily_spend: 946, active_days: 30, campaign_count: 3, impressions: 3200000, clicks: 54000, installs: 7600, registrations: 4700, purchase_value: 51200, roas: 1.8 },
      { optimizer_name: '未识别', total_spend: 8600, spend_share: 0.19, avg_daily_spend: 286, active_days: 21, campaign_count: 2, impressions: 900000, clicks: 14000, installs: 1600, registrations: 900, purchase_value: 6200, roas: 0.72 },
    ]
    return ok(rows, { meta: { grand_total_spend: 37000, unidentified_spend: 8600, unidentified_ratio: 0.23 } })
  }
  if (p === '/api/optimizer-performance/detail') {
    return ok(aggFrom(DAILY, 'campaign').slice(0, 4).map(r => ({
      campaign_id: r.campaign_id,
      campaign_name: r.campaign_name,
      platform: r.platform,
      account_id: r.account_id,
      match_source: 'name',
      match_confidence: 0.9,
      match_position: 'prefix',
      spend: r.total_spend,
      impressions: r.total_impressions,
      clicks: r.total_clicks,
      installs: r.total_installs,
      purchase_value: r.total_revenue,
      active_days: 30,
      roas: r.roas,
    })))
  }
  if (p === '/api/optimizer-performance/match-distribution') {
    return ok([
      { match_source: 'name', match_source_label: '命名匹配', campaign_count: 4, total_spend: 28400 },
      { match_source: 'unmatched', match_source_label: '未匹配', campaign_count: 2, total_spend: 8600 },
    ])
  }
  if (p === '/api/optimizer-directory/list') {
    return ok([
      { id: 1, optimizer_name: '林可', optimizer_code: 'LK', aliases: 'linke,林可', is_active: 1, remark: '', created_at: '2026-02-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z' },
      { id: 2, optimizer_name: '周宁', optimizer_code: 'ZN', aliases: 'zhouning', is_active: 1, remark: '兼设计师', created_at: '2026-03-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z' },
    ])
  }
  if (p === '/api/optimizer-directory/unassigned-samples') {
    return ok([{ optimizer_name_raw: 'test_ops', occurrence_count: 2, total_spend: 860, last_seen_at: '2026-10-18T00:00:00Z' }])
  }

  if (p === '/api/designer-performance/summary') {
    return ok([
      { designer_name: '周宁', material_count: 8, total_spend: 22100, impressions: 2400000, clicks: 48000, installs: 6200, conversions: 900, purchase_value: 39800, ctr: 0.02, roas: 1.8 },
      { designer_name: '外部代理', material_count: 3, total_spend: 6400, impressions: 500000, clicks: 7000, installs: 800, conversions: 90, purchase_value: 4100, ctr: 0.014, roas: 0.64 },
    ])
  }
  if (p === '/api/designer-performance/materials') {
    return ok(aggFrom(DAILY, 'ad').slice(0, 6).map(r => ({
      ad_id: r.ad_id, ad_name: r.ad_name, platform: r.platform, campaign_name: r.campaign_name,
      spend: r.total_spend, impressions: r.total_impressions, clicks: r.total_clicks,
      installs: r.total_installs, registrations: r.total_registrations, purchase_value: r.total_revenue,
      ctr: r.ctr, roas: r.roas,
    })))
  }

  if (p === '/api/analysis/returned-conversion/hierarchy' || p === '/api/analysis/returned-conversion') {
    const rows = filteredDaily(q)
    const summary = returnedSummary(rows.length ? rows : DAILY)
    const grouped = aggFrom(rows.length ? rows : DAILY, 'campaign')
    return {
      code: 0,
      message: 'ok',
      meta: { data_label: 'returned', disclaimer: '演示回传口径，非真实订单', group_by: q.get('group_by') || 'campaign', db: 'demo' },
      summary,
      availability: availability(true),
      rows: grouped.map(r => ({
        ...summary,
        spend: r.total_spend,
        impressions: r.total_impressions,
        clicks: r.total_clicks,
        installs: r.total_installs,
        registrations_returned: r.total_registrations,
        purchase_value_returned: round2(Number(r.total_revenue) * 0.7),
        total_value_returned: r.total_revenue,
        cumulative_roi_returned: r.roas,
        dimension_key: String(r.campaign_id),
        dimension_label: String(r.campaign_name),
        campaign_id: r.campaign_id,
        campaign_name: r.campaign_name,
        adset_id: r.adgroup_id,
        ad_id: r.ad_id,
      })),
    }
  }

  if (p === '/api/integrations/overview') {
    return {
      tenant_id: 1,
      redirect_base: null,
      items: [
        { platform: 'tiktok', configured: true, mock_available: true, credentials: { total: 1, valid: 1, expiring: 0, expired: 0 } },
        { platform: 'meta', configured: true, mock_available: true, credentials: { total: 1, valid: 1, expiring: 0, expired: 0 } },
      ],
    }
  }
  if (p === '/api/integrations/credentials') {
    return {
      items: [
        { id: 1, platform: 'tiktok', external_id: 'bc-demo-lumen', expires_at: null, scopes: ['demo'] },
        { id: 2, platform: 'meta', external_id: 'biz-demo-lumen', expires_at: null, scopes: ['demo'] },
      ],
    }
  }
  if (p.includes('/oauth/start')) {
    return {
      platform: p.includes('meta') ? 'meta' : 'tiktok',
      mock_mode: true,
      authorize_url: 'about:blank',
      state: 'demo',
      hint: '演示模式不会打开真实授权页',
    }
  }

  if (p === '/api/tenant/members') return MEMBERS
  if (p === '/api/tenant/invitations') {
    return [{
      id: 1, tenant_id: 1, email: 'new.member@demo.invalid', role: 'member', token: 'demo-invite',
      status: 'active', expires_at: '2026-11-01T00:00:00Z', invited_by_username: 'demo.owner',
      created_at: '2026-10-18T00:00:00Z',
    }]
  }

  if (p === '/api/billing/upgrade-requests' || p === '/api/billing/admin/upgrade-requests') {
    return [{
      id: 9, tenant_id: 1, tenant_name: 'Lumen Demo', tenant_slug: 'lumen-demo',
      from_plan_id: 'free', to_plan_id: 'pro', contact_email: 'owner@demo.invalid',
      message: '演示申请', status: 'pending', requested_by_username: 'demo.owner',
      created_at: '2026-10-10T00:00:00Z',
    }]
  }

  if (p === '/health') return { ok: true, mode: 'demo' }

  if (method !== 'GET' && method !== 'HEAD') {
    return { ok: true, code: 0, message: '演示模式仅在本地模拟，未连接外部服务', data: { success: false } }
  }
  return { code: 0, message: 'demo', data: [], items: [], rows: [], list: [], ok: true, total: 0 }
}

function demoResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export function installDemoFetch() {
  const original = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    let url: URL
    try {
      url = new URL(raw, window.location.origin)
    } catch {
      return original(input, init)
    }
    if (!url.pathname.startsWith('/api/') && url.pathname !== '/health') {
      return original(input, init)
    }
    const method = (init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase()
    if (method === 'PUT' && url.pathname.replace(/\/+$/, '') === '/api/insight/config') {
      try {
        insight = JSON.parse(String(init?.body ?? '{}'))
      } catch { /* keep previous */ }
    }
    const body = match(url.pathname, method, url.searchParams)
    return demoResponse(body)
  }
}
