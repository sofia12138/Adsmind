import { apiFetch } from './api'
import type { LaunchResponse } from './launch-drafts'
import type { Template } from './templates'

const TIKTOK_LOCATION_IDS: Record<string, string> = {
  US: '6252001', JP: '1861060', KR: '1835841', TW: '1668284',
  TH: '1605651', ID: '1643084', VN: '1562822', BR: '3469034',
  MX: '3996063', DE: '2921044',
}

// ─── Types ───────────────────────────────────────────────

export interface W2aFields {
  pageId: string
  landingPageUrl: string
  primaryText: string
  headline: string
  description: string
  callToAction: string
  pixelId: string
  customEventType: string
}

export interface MaterialItem {
  id: string
  type: 'image' | 'video'
  image_hash?: string
  video_id?: string
  picture_url?: string
  original_name: string
  ad_name: string
  /** 素材来源：本地批量上传 / 账户已上传素材；用于操作日志统计 */
  source?: 'local_upload' | 'account_asset'
  /** 账户素材的 Meta 资产 ID（video_id 或 image_hash 一致即可） */
  meta_asset_id?: string
}

export interface AdSetConfig {
  name: string
  daily_budget: number
  countries: string[]
  pixel_id?: string
  custom_event_type?: string
  material_ids: string[]
  region_group_id?: number
  region_group_name?: string
  country_codes_snapshot?: string[]
}

export interface AssetRefs {
  landing_page_asset_id?: number
  landing_page_asset_name?: string
  landing_page_url_snapshot?: string
  copy_asset_id?: number
  copy_asset_name?: string
  primary_text_snapshot?: string
  headline_snapshot?: string
  description_snapshot?: string
}

export interface MetaScheduleFields {
  /** ISO 8601 with timezone offset, e.g. 2026-04-25T10:00:00-0700 */
  start_time: string
  /** ISO 8601, optional. 不填表示长期投放 */
  end_time?: string
  /** 友好展示用，eg "America/Los_Angeles"；后端只透传 + 日志 */
  timezone?: string
}

export interface CreateAdsParams {
  launch?: (payload: Record<string, unknown>) => Promise<LaunchResponse>
  mode: 'template'
  platform: 'tiktok' | 'meta'
  campaignName: string
  country: string
  countries?: string[]
  budget: number
  budgetCurrency?: string
  templateId?: string
  template?: Template | null
  adAccountId?: string
  w2a?: W2aFields
  materials?: MaterialItem[]
  adsets?: AdSetConfig[]
  assetRefs?: AssetRefs
  /** Meta 投放时间（写入 AdSet）；不传 → 不传给 Meta API */
  metaSchedule?: MetaScheduleFields
  /** Meta CBO 模板的 Campaign 层日预算（账户币种主单位，未乘 100）。仅 web_to_app_conversion_cbo 使用 */
  campaignDailyBudget?: number
  /** 本次投放选择的语种（必须 ∈ template.delivery_languages）；后端会强制启用平台语言定向 */
  selectedDeliveryLanguage?: string
}

export interface AdResult {
  success: boolean
  ad_id?: string
  ad_name: string
  material_name: string
  material_type?: string
  error?: string
}

export interface AdSetResult {
  success: boolean
  adset_id?: string
  adset_name: string
  error?: string
  payload_sent?: Record<string, unknown>
  meta_error_code?: number | null
  meta_error_subcode?: number | null
  meta_error_message?: string
  ads: AdResult[]
}

export interface CampaignResult {
  success: boolean
  campaign_id?: string
  error?: string
  meta_error_code?: number | null
  meta_error_subcode?: number | null
  meta_error_message?: string
  campaign_payload_debug?: Record<string, unknown>
}

export interface BatchLaunchResult {
  platform: string
  template_type?: string
  ad_account_id?: string
  campaign: CampaignResult
  adsets: AdSetResult[]
  /** Meta 预算模式（仅 Meta 链路返回）：CBO / ABO */
  budget_mode?: 'CBO' | 'ABO'
  requested_budget_mode?: 'CBO' | 'ABO'
  actual_budget_mode?: 'CBO' | 'CBO_FAILED' | 'ABO'
  failed_step?: 'campaign' | 'adset' | 'ad'
  campaign_daily_budget?: number | null
  adset_daily_budget?: number | null
}

export interface CreateResult {
  success: boolean
  message: string
  draftSaved?: boolean
  details?: BatchLaunchResult
}

// ─── 统一入口 ────────────────────────────────────────────

export async function createAds(params: CreateAdsParams): Promise<CreateResult> {
  if (!params.templateId) {
    return { success: false, message: '请先选择模板' }
  }
  return launchFromTemplate(params)
}

// ─── 模板投放：POST /api/templates/launch ────────────────

async function launchFromTemplate(p: CreateAdsParams): Promise<CreateResult> {
  try {
    const tplPlatform = p.template?.platform ?? p.platform
    const tplType = p.template?.template_type ?? ''

    const body: Record<string, unknown> = {
      template_id: p.templateId,
      campaign_name: p.campaignName,
      budget: p.budget || 50,
      budget_currency: p.budgetCurrency,
    }
    if (p.selectedDeliveryLanguage) {
      body.selected_delivery_language = p.selectedDeliveryLanguage
    }

    if (tplPlatform === 'meta') {
      if (!p.adAccountId) {
        return { success: false, message: 'Meta 模板投放必须选择广告账户 (ad_account_id)' }
      }
      body.ad_account_id = p.adAccountId

      // W2A 系列模板（含 ABO 与 CBO）走相同 overrides 构建逻辑；
      // 唯一差异：CBO 在 overrides.campaign 注入 daily_budget，AdSet 不带 daily_budget
      const isW2aFamily = (tplType === 'web_to_app' || tplType === 'web_to_app_conversion_cbo')
      const isCbo = tplType === 'web_to_app_conversion_cbo'

      if (isW2aFamily && p.w2a) {
        body.overrides = _buildW2aOverrides(p, isCbo)
      } else {
        const countryCodes = (p.countries && p.countries.length > 0) ? p.countries : [p.country]
        body.overrides = {
          adset: {
            targeting: { geo_locations: { countries: countryCodes } },
          },
        }
      }

      if (p.materials && p.materials.length > 0) {
        body.materials = p.materials
      }
      if (p.adsets && p.adsets.length > 0) {
        body.adsets = p.adsets.map(a => ({
          name: a.name,
          daily_budget: a.daily_budget,
          targeting: { geo_locations: { countries: a.countries } },
          promoted_object: {
            pixel_id: a.pixel_id || p.w2a?.pixelId || '',
            custom_event_type: a.custom_event_type || p.w2a?.customEventType || '',
          },
          material_ids: a.material_ids,
          region_group_id: a.region_group_id,
          region_group_name: a.region_group_name,
          country_codes_snapshot: a.country_codes_snapshot,
        }))
      }
      if (p.assetRefs) {
        body.asset_refs = p.assetRefs
      }
      // 投放时间（写入 AdSet 的 start_time / end_time）
      if (p.metaSchedule && p.metaSchedule.start_time) {
        body.meta_schedule = {
          start_time: p.metaSchedule.start_time,
          end_time: p.metaSchedule.end_time || undefined,
          timezone: p.metaSchedule.timezone || undefined,
        }
      }
    } else {
      body.advertiser_id = ''
      const locId = TIKTOK_LOCATION_IDS[p.country]
      body.location_ids = locId ? [locId] : []
    }

    const res = (p.launch ? await p.launch(body) : await apiFetch('/api/templates/launch', {
      method: 'POST', body: JSON.stringify(body),
    })) as { data?: BatchLaunchResult; error?: string; draft_saved?: boolean }
    if (res.draft_saved) return { success: false, draftSaved: true, message: res.error || '草稿已保存' }

    if (res.error) {
      return { success: false, message: `模板投放失败: ${res.error}`, details: res.data }
    }

    const d = res.data
    if (!d?.campaign?.success) {
      const err = d?.campaign?.error ?? '未知错误'
      return { success: false, message: `Campaign 创建失败: ${err}`, details: d }
    }

    const adsets = d.adsets ?? []
    const totalAdsets = adsets.length
    const okAdsets = adsets.filter(a => a.success).length
    const totalAds = adsets.reduce((s, a) => s + (a.ads?.length ?? 0), 0)
    const okAds = adsets.reduce((s, a) => s + (a.ads?.filter(ad => ad.success).length ?? 0), 0)

    if (okAdsets === 0 && totalAdsets > 0) {
      return { success: false, message: `所有 AdSet 创建失败 (${totalAdsets} 个)`, details: d }
    }
    if (okAdsets < totalAdsets || okAds < totalAds) {
      return {
        success: true,
        message: `部分创建成功: AdSet ${okAdsets}/${totalAdsets}, Ad ${okAds}/${totalAds}`,
        details: d,
      }
    }
    return {
      success: true,
      message: `创建成功: ${okAdsets} 个 AdSet, ${okAds} 个 Ad`,
      details: d,
    }
  } catch (e) {
    return { success: false, message: `模板投放失败: ${(e as Error).message}` }
  }
}

function _buildW2aOverrides(p: CreateAdsParams, isCbo = false): Record<string, unknown> {
  const w = p.w2a!
  const countryCodes = (p.countries && p.countries.length > 0) ? p.countries : [p.country]
  // ABO：daily_budget 在 AdSet；CBO：daily_budget 在 Campaign
  const adsetBlock: Record<string, unknown> = {
    targeting: {
      geo_locations: { countries: countryCodes },
    },
    promoted_object: {
      pixel_id: w.pixelId || '',
      custom_event_type: w.customEventType || '',
    },
  }
  if (!isCbo) {
    adsetBlock.daily_budget = Math.round((p.budget || 50) * 100)
  }
  const campaignBlock: Record<string, unknown> = {}
  if (isCbo) {
    // CBO（Meta ACB）：仅在 Campaign 层注入 daily_budget；
    // 不要带 is_adset_budget_sharing_enabled —— Meta 会拒绝 (subcode=4834002)
    const cboBudget = Number(p.campaignDailyBudget ?? p.budget ?? 50)
    campaignBlock.daily_budget = Math.round(cboBudget * 100)
  }
  const overrides: Record<string, unknown> = {
    adset: adsetBlock,
    creative: {
      page_id: w.pageId,
      primary_text: w.primaryText,
      headline: w.headline,
      description: w.description,
      call_to_action: w.callToAction || 'LEARN_MORE',
      link: w.landingPageUrl,
    },
  }
  if (isCbo) overrides.campaign = campaignBlock
  return overrides
}

// ─── 素材名 → Ad 名称工具 ────────────────────────────────

const _ILLEGAL_CHARS = /[<>:"/\\|?*\x00-\x1f]/g
const _MAX_AD_NAME_LEN = 200

export function fileNameToAdName(fileName: string): string {
  const dotIdx = fileName.lastIndexOf('.')
  const base = dotIdx > 0 ? fileName.slice(0, dotIdx) : fileName
  return base.replace(_ILLEGAL_CHARS, '_').trim().slice(0, _MAX_AD_NAME_LEN) || 'ad'
}
