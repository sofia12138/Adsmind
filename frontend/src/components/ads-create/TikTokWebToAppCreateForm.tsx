import { useLaunchDraft } from './useLaunchDraft'
/**
 * TikTok Web to App 新建广告子表单（嵌入到统一新建广告页中使用）
 *
 * 与 TikTokMinisCreateForm 保持相同的结构和交互风格；区别在于：
 *  - 不需要 App ID / Minis ID
 *  - 必填 Landing Page URL
 *  - 支持 Ad Title / Call to Action / Tracking URL
 *  - 使用普通 budget（非 ROAS）
 *
 * 模板的选择 (selectedTpl) 由父组件维护并通过 props 注入。
 */
import { useState, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, AlertCircle, CheckCircle, Send, Shield, Library, Globe, X, FileVideo, Plus } from 'lucide-react'
import { SectionCard } from '@/components/common/SectionCard'
import type { Template } from '@/services/templates'
import { fetchTikTokAdvertisers, type Advertiser } from '@/services/advertisers'
import { TikTokLocationPicker, resolveCountryCodesFromTemplate } from '@/components/common/TikTokLocationPicker'
import { TikTokIdentityPicker } from '@/components/common/TikTokIdentityPicker'
import { TikTokPixelEventPicker } from '@/components/common/TikTokPixelEventPicker'
import {
  LandingPagePickerDialog,
  CopyPackPickerDialog,
  RegionGroupPickerDialog,
} from '@/components/common/AssetPickerDialog'
import { TikTokVideoMaterialPicker, type PickedVideo } from '@/components/common/TikTokVideoMaterialPicker'
import { codesToLocationIds, type LocationSelection } from '@/constants/tiktok-locations'
import { DEFAULT_DELIVERY_LANGUAGE } from '@/constants/deliveryLanguages'
import DeliveryLanguageSelect from '@/components/ads-create/DeliveryLanguageSelect'

const inputCls = 'w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-pink-500/20 focus:border-pink-400 transition'

export function isTikTokWebToAppTpl(t: Template | null | undefined): boolean {
  if (!t) return false
  return t.platform === 'tiktok' && t.template_type === 'tiktok_web_to_app'
}

const CTA_OPTIONS = [
  'LEARN_MORE', 'DOWNLOAD_NOW', 'SHOP_NOW', 'SIGN_UP', 'INSTALL_NOW',
  'GET_QUOTE', 'APPLY_NOW', 'BOOK_NOW', 'VIEW_NOW', 'ORDER_NOW',
]

// W2A 业务白名单：仅允许两个优化事件，前端按业务名展示
const W2A_ALLOWED_EVENTS = [
  { code: 'SHOPPING',         label: 'Purchase'  },
  { code: 'ON_WEB_SUBSCRIBE', label: 'Subscribe' },
] as const

/** 去掉文件名后缀，用作默认 Ad Name */
function stripExt(name: string): string {
  if (!name) return ''
  const i = name.lastIndexOf('.')
  return i > 0 ? name.slice(0, i) : name
}

interface AdResultItem {
  success: boolean
  ad_id?: string
  ad_name?: string
  video_id?: string
  error?: string
  skipped?: boolean
  reason?: string
  hint?: string
}

interface LaunchResult {
  draft_saved?: boolean
  data?: {
    platform?: string
    template_type?: string
    campaign?: { success: boolean; campaign_id?: string; error?: string; skipped?: boolean; reason?: string; hint?: string }
    adgroup?: { success: boolean; adgroup_id?: string; error?: string; skipped?: boolean; reason?: string; hint?: string }
    /** 单条兼容（始终等于 ads[0]） */
    ad?: AdResultItem | null
    /** 批量结果（一对一对应 materials） */
    ads?: AdResultItem[]
    summary?: { total: number; success: number; fail: number }
  }
  error?: string
}

interface Props {
  /** 当前选中的 W2A 模板（必须是 tiktok_web_to_app） */
  tpl: Template
}

type StepResult = {
  success: boolean
  error?: string
  skipped?: boolean
  reason?: string
  hint?: string
} & Record<string, unknown>

function renderStepResult(step: StepResult | undefined, idKey: string): string {
  if (!step) return '未执行'
  if (step.success) return `成功 → ${(step[idKey] as string) ?? ''}`
  if (step.skipped) return step.reason || '未执行（上一步失败）'
  if (step.hint) return `失败 → ${step.hint}（原始: ${step.error ?? ''}）`
  return `失败 → ${step.error ?? '未知错误'}`
}

export default function TikTokWebToAppCreateForm({ tpl }: Props) {
  const { launch, dialog } = useLaunchDraft()
  const { data: advResp } = useQuery({ queryKey: ['tiktok-advertisers'], queryFn: fetchTikTokAdvertisers })
  const advertisers: Advertiser[] = advResp?.data ?? []

  const [advertiserId, setAdvertiserId] = useState('')
  const budgetCurrency = advertisers.find(a => a.advertiser_id === advertiserId)?.currency || ''
  const [campaignName, setCampaignName] = useState('')
  const [adgroupName, setAdgroupName] = useState('')
  const [adName, setAdName] = useState('')
  const [budget, setBudget] = useState('50')
  const [bidPrice, setBidPrice] = useState('')
  const [scheduleStartTime, setScheduleStartTime] = useState('')
  const [scheduleEndTime, setScheduleEndTime] = useState('')
  const [identityId, setIdentityId] = useState('')
  const [identityType, setIdentityType] = useState('CUSTOMIZED_USER')
  const [countryCodes, setCountryCodes] = useState<string[]>([])
  // 投放地区模式：'countries' = 用户手选国家；'group' = 引用资产库地区组
  const [regionMode, setRegionMode] = useState<'countries' | 'group'>('countries')
  const [regionGroupId, setRegionGroupId] = useState<number | null>(null)
  const [regionGroupName, setRegionGroupName] = useState('')
  const [showRegionPicker, setShowRegionPicker] = useState(false)

  const [landingPageUrl, setLandingPageUrl] = useState('')
  const [landingPageId, setLandingPageId] = useState<number | null>(null)
  const [landingPageName, setLandingPageName] = useState('')
  const [showLandingPicker, setShowLandingPicker] = useState(false)

  const [trackingUrl, setTrackingUrl] = useState('')
  const [pixelId, setPixelId] = useState('')
  const [optimizationEvent, setOptimizationEvent] = useState('SHOPPING')
  const [adText, setAdText] = useState('')
  const [adTitle, setAdTitle] = useState('')
  const [callToAction, setCallToAction] = useState('LEARN_MORE')
  const [copyPackId, setCopyPackId] = useState<number | null>(null)
  const [copyPackName, setCopyPackName] = useState('')
  const [showCopyPicker, setShowCopyPicker] = useState(false)

  // 视频素材：批量多选；每条素材对应一个 Ad
  const [pickedVideos, setPickedVideos] = useState<PickedVideo[]>([])
  // 已选素材的 ad_name 编辑（key: `${source}-${video_id}`）
  const [adNameOverrides, setAdNameOverrides] = useState<Record<string, string>>({})
  const [showVideoPicker, setShowVideoPicker] = useState(false)

  const [selectedDeliveryLanguage, setSelectedDeliveryLanguage] = useState<string>(DEFAULT_DELIVERY_LANGUAGE)

  // 切换模板时回填默认值
  useEffect(() => {
    if (!tpl) return
    const defaults = (tpl.defaults as Record<string, unknown>) ?? {}
    const adgroup = (tpl.adgroup as Record<string, unknown>) ?? {}
    const ad = (tpl.ad as Record<string, unknown>) ?? {}

    const targeting = (defaults.targeting as Record<string, unknown>) ?? {}
    const selection = (targeting.location_selection as LocationSelection | undefined) ?? null
    const fallbackIds = Array.isArray(targeting.location_ids)
      ? (targeting.location_ids as unknown[]).map(String)
      : []
    setCountryCodes(resolveCountryCodesFromTemplate(selection, fallbackIds))

    // 模板地区组快照（资产库引用）
    const tplRegionMode = targeting.region_mode === 'group' ? 'group' : 'countries'
    setRegionMode(tplRegionMode)
    const tplRegionId = typeof targeting.region_group_id === 'number' ? targeting.region_group_id : null
    setRegionGroupId(tplRegionId)
    setRegionGroupName(String(targeting.region_group_name_snapshot || ''))

    // 模板落地页快照（资产库引用）
    const landing = (defaults.landing as Record<string, unknown>) ?? {}
    const tplLandingId = typeof landing.landing_page_id === 'number' ? landing.landing_page_id : null
    setLandingPageId(tplLandingId)
    setLandingPageName(String(landing.landing_page_name_snapshot || ''))

    // 模板文案快照（资产库引用）
    const copy = (defaults.copy as Record<string, unknown>) ?? {}
    const tplCopyId = typeof copy.copy_pack_id === 'number' ? copy.copy_pack_id : null
    setCopyPackId(tplCopyId)
    setCopyPackName(String(copy.copy_pack_name_snapshot || ''))

    const identity = (defaults.identity as Record<string, unknown>) ?? {}
    const tplIdentityId = (identity.identity_id as string | undefined) || ''
    const tplIdentityType = (identity.identity_type as string | undefined) || ''
    setIdentityId(tplIdentityId)
    if (tplIdentityType) setIdentityType(tplIdentityType)

    const tracking = (defaults.tracking as Record<string, unknown>) ?? {}
    if (tracking.pixel_id) setPixelId(String(tracking.pixel_id))
    if (tracking.optimization_event) setOptimizationEvent(String(tracking.optimization_event))

    const tplCta = (defaults.call_to_action as string | undefined) || (ad.call_to_action as string | undefined) || ''
    if (tplCta) setCallToAction(tplCta)

    if (defaults.landing_page_template) setLandingPageUrl(String(defaults.landing_page_template))
    if (adgroup.default_budget) setBudget(String(adgroup.default_budget))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tpl?.id])

  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<LaunchResult | null>(null)
  const [errorMsg, setErrorMsg] = useState('')

  // 切换广告主时清空已选素材（避免跨账户串号）
  useEffect(() => {
    setPickedVideos([])
    setAdNameOverrides({})
  }, [advertiserId])

  /** 计算每条素材最终的 ad_name（含重名加序号） */
  const computedMaterials = useMemo(() => {
    const seen: Record<string, number> = {}
    return pickedVideos.map((v) => {
      const key = `${v.source}-${v.video_id}`
      const userOverride = (adNameOverrides[key] || '').trim()
      const auto = stripExt(v.file_name) || `${campaignName.trim() || 'Ad'}`
      const base = userOverride || auto
      const n = (seen[base] = (seen[base] || 0) + 1)
      const final = n === 1 ? base : `${base}_${String(n).padStart(2, '0')}`
      return { ...v, key, final_ad_name: final, source_base_name: auto }
    })
  }, [pickedVideos, adNameOverrides, campaignName])

  function validate(): string | null {
    if (!advertiserId) return '请选择广告主'
    if (!campaignName.trim()) return 'Campaign Name 不能为空'
    if (!identityId.trim()) return '请选择 Identity（TikTok 广告必填）'
    if (countryCodes.length === 0) return '请至少选择 1 个投放国家'
    if (!landingPageUrl.trim()) return 'Landing Page URL 不能为空（Web to App 必填）'
    if (pickedVideos.length === 0) return '请至少选择 1 个视频素材'
    const b = Number(budget)
    if (!Number.isFinite(b) || b <= 0) return '日预算必须为正数'
    return null
  }

  async function handleSubmit() {
    setErrorMsg(''); setResult(null)
    const err = validate()
    if (err) { setErrorMsg(err); return }

    // 构造批量 materials（一对一对应每个 Ad）
    const materialsPayload = computedMaterials.map(m => ({
      video_id: m.video_id,
      ad_name: m.final_ad_name,
      file_name: m.file_name,
    }))
    const firstMaterial = computedMaterials[0]!

    const payload: Record<string, unknown> = {
      template_id: tpl.id,
      advertiser_id: advertiserId,
      campaign_name: campaignName.trim(),
      adgroup_name: adgroupName.trim() || campaignName.trim(),
      // 顶层 ad_name/video_id 仅供单素材兼容路径使用；后端有 materials 时优先用 materials
      ad_name: adName.trim() || firstMaterial.final_ad_name,
      material_name: firstMaterial.source_base_name,
      video_id: firstMaterial.video_id,
      materials: materialsPayload,
      budget: Number(budget),
      budget_currency: budgetCurrency,
      identity_id: identityId.trim(),
      identity_type: identityType,
      ad_text: adText,
      ad_title: adTitle.trim(),
      call_to_action: callToAction,
      landing_page_url: landingPageUrl.trim(),
      location_ids: codesToLocationIds(countryCodes),
    }
    if (bidPrice) payload.bid = Number(bidPrice)
    if (trackingUrl.trim()) payload.tracking_url = trackingUrl.trim()
    if (pixelId.trim()) payload.pixel_id = pixelId.trim()
    if (optimizationEvent) payload.optimization_event = optimizationEvent
    if (scheduleStartTime) payload.schedule_start_time = scheduleStartTime
    if (scheduleEndTime) payload.schedule_end_time = scheduleEndTime
    payload.selected_delivery_language = selectedDeliveryLanguage

    // 资产库引用 + 快照（后端只用于日志/operation_log 与模板回填，不影响 TikTok 主调用）
    payload.region_mode = regionMode
    if (regionGroupId) {
      payload.region_group_id = regionGroupId
      payload.region_group_name_snapshot = regionGroupName
    }
    if (landingPageId) {
      payload.landing_page_id = landingPageId
      payload.landing_page_name_snapshot = landingPageName
      payload.landing_page_url_snapshot = landingPageUrl.trim()
    }
    if (copyPackId) {
      payload.copy_pack_id = copyPackId
      payload.copy_pack_name_snapshot = copyPackName
    }

    setSubmitting(true)
    try {
      const res = await launch(payload) as LaunchResult
      setResult(res)
      if (res.error && !res.draft_saved) setErrorMsg(res.error)
    } catch (e) {
      setErrorMsg(`投放失败: ${(e as Error).message}`)
    } finally {
      setSubmitting(false)
    }
  }

  const isSystemTpl = Boolean(tpl.is_system)
  const summary = result?.data?.summary
  const created = result?.data
  const adsList: AdResultItem[] = created?.ads ?? (created?.ad ? [created.ad] : [])
  const allAdsOk = adsList.length > 0 && adsList.every(a => a.success)
  const overallSuccess = !!created && created.campaign?.success && created.adgroup?.success && allAdsOk

  return (
    <>
      {dialog}
      {isSystemTpl && (
        <div className="flex items-start gap-2 p-3 mb-5 bg-amber-50 border border-amber-200 rounded-xl">
          <Shield className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-700">
            当前选择的是 TikTok Web to App 系统母版（只读）。母版提供策略默认值，只会根据下方白名单字段生成最终投放参数；如需保存自定义配置，请先在「模板管理」页另存为业务模板再使用。
          </p>
        </div>
      )}

      {/* 账户与命名 */}
      <SectionCard title="账户与命名" className="mb-5">
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">广告主 <span className="text-red-400">*</span></label>
            <select value={advertiserId} onChange={e => setAdvertiserId(e.target.value)} className={`${inputCls} bg-white`}>
              <option value="">请选择广告主</option>
              {advertisers.map(a => (
                <option key={a.advertiser_id} value={a.advertiser_id}>{a.advertiser_name} ({a.advertiser_id})</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Campaign Name <span className="text-red-400">*</span></label>
            <input
              value={campaignName}
              onChange={e => setCampaignName(e.target.value)}
              onBlur={() => {
                // 失焦时若 AdGroup Name 为空，自动继承 Campaign Name
                const c = campaignName.trim()
                if (c && !adgroupName.trim()) setAdgroupName(c)
              }}
              className={inputCls}
              placeholder="例：102-W2A-US-LandingXX-20260422-01"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">AdGroup Name</label>
              <input value={adgroupName} onChange={e => setAdgroupName(e.target.value)} className={inputCls} placeholder="留空将自动继承 Campaign Name" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Ad Name</label>
              <input value={adName} onChange={e => setAdName(e.target.value)} className={inputCls} placeholder="留空将自动取所选素材文件名" />
            </div>
          </div>
        </div>
      </SectionCard>

      {/* 预算与排期 */}
      <SectionCard title="预算与排期" className="mb-5">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">日预算 ({budgetCurrency || '请选择账户'}) <span className="text-red-400">*</span></label>
            <input type="number" value={budget} onChange={e => setBudget(e.target.value)} className={inputCls} min="1" step="1" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">出价 (Bid, 可选)</label>
            <input type="number" value={bidPrice} onChange={e => setBidPrice(e.target.value)} className={inputCls} min="0.01" step="0.01" placeholder="留空则使用 NO_BID" />
            <p className="text-xs text-gray-400 mt-1">填入数值会自动切换到 BID_TYPE_CUSTOM</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">投放开始时间</label>
            <input type="datetime-local" value={scheduleStartTime} onChange={e => setScheduleStartTime(e.target.value.replace('T', ' '))} className={inputCls} />
            <p className="text-xs text-gray-400 mt-1">留空则使用 SCHEDULE_FROM_NOW</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">投放结束时间</label>
            <input type="datetime-local" value={scheduleEndTime} onChange={e => setScheduleEndTime(e.target.value.replace('T', ' '))} className={inputCls} />
          </div>
        </div>
      </SectionCard>

      {/* 定向与落地 */}
      <SectionCard title="定向与落地" className="mb-5">
        <div className="space-y-4">
          {/* 投放地区：Tabs（按国家 / 地区组） */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-xs font-medium text-gray-600">投放地区 <span className="text-red-400">*</span></label>
              <div className="inline-flex border border-gray-200 rounded-lg overflow-hidden text-[11px]">
                <button
                  type="button"
                  onClick={() => setRegionMode('countries')}
                  className={`px-2.5 py-1 ${regionMode === 'countries' ? 'bg-pink-50 text-pink-600 font-medium' : 'text-gray-500 hover:bg-gray-50'}`}
                >按国家</button>
                <button
                  type="button"
                  onClick={() => setRegionMode('group')}
                  className={`px-2.5 py-1 border-l border-gray-200 ${regionMode === 'group' ? 'bg-pink-50 text-pink-600 font-medium' : 'text-gray-500 hover:bg-gray-50'}`}
                >地区组</button>
              </div>
            </div>

            {regionMode === 'countries' ? (
              <TikTokLocationPicker
                value={countryCodes}
                onChange={({ country_codes }) => {
                  setCountryCodes(country_codes)
                  // 切换到手选 → 清掉资产库引用
                  setRegionGroupId(null)
                  setRegionGroupName('')
                }}
              />
            ) : (
              <div className="space-y-2">
                {regionGroupId ? (
                  <div className="flex items-center gap-2 p-3 bg-blue-50/40 border border-blue-100 rounded-xl">
                    <Globe className="w-4 h-4 text-blue-400" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-800 truncate">{regionGroupName || `地区组 #${regionGroupId}`}</div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        共 {countryCodes.length} 个国家 · 展开为 {codesToLocationIds(countryCodes).length} 个 TikTok location_id
                        {countryCodes.length > codesToLocationIds(countryCodes).length && (
                          <span className="text-amber-600 ml-1">（{countryCodes.length - codesToLocationIds(countryCodes).length} 个未匹配本地映射，将被忽略）</span>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setShowRegionPicker(true)}
                      className="px-2.5 py-1 text-xs text-blue-500 border border-blue-200 rounded-lg hover:bg-blue-50"
                    >更换</button>
                    <button
                      type="button"
                      onClick={() => { setRegionGroupId(null); setRegionGroupName(''); setCountryCodes([]) }}
                      className="p-1 text-gray-400 hover:bg-gray-100 rounded-md"
                      title="清除"
                    ><X className="w-3.5 h-3.5" /></button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setShowRegionPicker(true)}
                    className="w-full flex items-center justify-center gap-2 py-2.5 border border-dashed border-gray-300 rounded-xl text-sm text-gray-500 hover:border-blue-300 hover:text-blue-500 hover:bg-blue-50/30"
                  >
                    <Library className="w-4 h-4" />
                    从地区组库选择
                  </button>
                )}
              </div>
            )}
          </div>

          <DeliveryLanguageSelect
            value={selectedDeliveryLanguage}
            onChange={setSelectedDeliveryLanguage}
            deliveryLanguages={tpl.delivery_languages}
            defaultDeliveryLanguage={tpl.default_delivery_language}
            templateId={tpl.id}
            inputClassName={inputCls}
            accent="pink"
          />

          {/* Landing Page URL（支持手填或从落地页库选择） */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-xs font-medium text-gray-600">Landing Page URL <span className="text-red-400">*</span></label>
              <button
                type="button"
                onClick={() => setShowLandingPicker(true)}
                className="text-[11px] text-blue-500 hover:text-blue-600 flex items-center gap-1"
              >
                <Library className="w-3 h-3" />
                从落地页库选择
              </button>
            </div>
            <input
              value={landingPageUrl}
              onChange={e => {
                setLandingPageUrl(e.target.value)
                // 手动改 URL → 清掉资产库引用
                if (landingPageId) { setLandingPageId(null); setLandingPageName('') }
              }}
              className={inputCls}
              placeholder="https://your.landing.page/xxx"
            />
            {landingPageId && (
              <p className="text-[11px] text-blue-500 mt-1 flex items-center gap-1">
                <Library className="w-3 h-3" />
                来自落地页库：{landingPageName || `#${landingPageId}`}
              </p>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Tracking URL（可选）</label>
            <input value={trackingUrl} onChange={e => setTrackingUrl(e.target.value)} className={inputCls} placeholder="第三方监测链接" />
          </div>
          <TikTokPixelEventPicker
            advertiserId={advertiserId}
            pixelId={pixelId}
            optimizationEvent={optimizationEvent}
            allowedEvents={[...W2A_ALLOWED_EVENTS]}
            onChange={({ pixel_id, optimization_event }) => {
              setPixelId(pixel_id)
              setOptimizationEvent(optimization_event)
            }}
          />
        </div>
      </SectionCard>

      {/* 创意（Identity + 视频 + 文案 + CTA） */}
      <SectionCard title="创意" className="mb-5">
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Identity（身份） <span className="text-red-400">*</span></label>
            <TikTokIdentityPicker
              advertiserId={advertiserId}
              value={identityId}
              onChange={({ identity_id, identity_type }) => {
                setIdentityId(identity_id)
                if (identity_type) setIdentityType(identity_type)
              }}
            />
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-xs font-medium text-gray-600">视频素材 <span className="text-red-400">*</span></label>
              <span className="text-[11px] text-gray-400">
                共 {pickedVideos.length} 个 · 将创建 {pickedVideos.length} 个 Ad
              </span>
            </div>
            {!advertiserId ? (
              <p className="text-xs text-gray-400">请先选择广告主</p>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => setShowVideoPicker(true)}
                  className="w-full flex items-center justify-center gap-2 py-2.5 border border-dashed border-gray-300 rounded-xl text-sm text-gray-600 hover:border-pink-300 hover:text-pink-600 hover:bg-pink-50/30"
                >
                  <Plus className="w-4 h-4" />
                  {pickedVideos.length === 0 ? '选择视频素材（系统素材 / 本地上传 / 账户素材）' : '继续添加 / 调整素材'}
                </button>

                {/* 已选素材列表（每条可编辑 ad_name） */}
                {computedMaterials.length > 0 && (
                  <div className="mt-3 border border-gray-100 rounded-xl divide-y divide-gray-50 overflow-hidden">
                    {computedMaterials.map((m, idx) => (
                      <div key={m.key} className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50">
                        <span className="text-[11px] text-gray-400 w-5 text-right">#{idx + 1}</span>
                        <FileVideo className="w-4 h-4 text-blue-400 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <div className="text-xs text-gray-700 truncate" title={m.file_name}>{m.file_name || m.video_id}</div>
                          <div className="text-[10px] text-gray-400 mt-0.5">
                            {m.source === 'system' && '系统素材'}
                            {m.source === 'local' && '本地上传'}
                            {m.source === 'account' && '账户素材'}
                            <span className="mx-1">·</span>
                            {m.video_id}
                          </div>
                        </div>
                        <input
                          value={adNameOverrides[m.key] ?? ''}
                          onChange={e => setAdNameOverrides(prev => ({ ...prev, [m.key]: e.target.value }))}
                          placeholder={m.final_ad_name}
                          className="px-2 py-1 w-44 border border-gray-200 rounded-md text-[11px] focus:outline-none focus:ring-1 focus:ring-pink-200"
                          title="留空将自动取素材名（重名自动加序号）"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            setPickedVideos(prev => prev.filter(v => !(v.video_id === m.video_id && v.source === m.source)))
                            setAdNameOverrides(prev => { const p = { ...prev }; delete p[m.key]; return p })
                          }}
                          className="text-gray-300 hover:text-red-500 p-0.5"
                          title="移除"
                        ><X className="w-3.5 h-3.5" /></button>
                      </div>
                    ))}
                  </div>
                )}
                {pickedVideos.length === 0 && (
                  <p className="text-[11px] text-gray-400 mt-2">未选择素材时无法创建广告。多选素材时，将共用同一套 Campaign / AdGroup / 文案配置，每个素材生成一个 Ad。</p>
                )}
              </>
            )}
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Ad Title (Display Name)</label>
              <input
                value={adTitle}
                onChange={e => {
                  setAdTitle(e.target.value)
                  if (copyPackId) { setCopyPackId(null); setCopyPackName('') }
                }}
                className={inputCls}
                placeholder="广告标题"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Call to Action</label>
              <select value={callToAction} onChange={e => setCallToAction(e.target.value)} className={`${inputCls} bg-white`}>
                {CTA_OPTIONS.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-xs font-medium text-gray-600">广告文案 (Ad Text)</label>
              <button
                type="button"
                onClick={() => setShowCopyPicker(true)}
                className="text-[11px] text-blue-500 hover:text-blue-600 flex items-center gap-1"
              >
                <Library className="w-3 h-3" />
                从文案库选择
              </button>
            </div>
            <textarea
              value={adText}
              onChange={e => {
                setAdText(e.target.value)
                if (copyPackId) { setCopyPackId(null); setCopyPackName('') }
              }}
              className={inputCls}
              rows={3}
              placeholder="广告描述文案"
            />
            {copyPackId && (
              <p className="text-[11px] text-blue-500 mt-1 flex items-center gap-1">
                <Library className="w-3 h-3" />
                来自文案库：{copyPackName || `#${copyPackId}`}
              </p>
            )}
          </div>
        </div>
      </SectionCard>

      {/* 提交 */}
      <div className="flex items-center gap-3 mb-6">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={submitting}
          className="px-5 py-2.5 bg-pink-500 text-white text-sm rounded-xl hover:bg-pink-600 disabled:opacity-50 transition font-medium flex items-center gap-1.5"
        >
          {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          {submitting ? '创建中...' : '创建广告'}
        </button>
      </div>

      {result?.draft_saved && <p role="status" className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-xl text-sm text-blue-700">草稿已保存，可在「广告草稿」中继续。</p>}
      {errorMsg && (
        <div className="flex items-start gap-2 p-3 mb-4 bg-red-50 border border-red-200 rounded-xl text-sm text-red-600">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{errorMsg}</span>
        </div>
      )}

      {result?.data && (
        <SectionCard title={overallSuccess ? '创建成功' : '创建结果（含失败）'} className="mb-5">
          {overallSuccess && (
            <div className="flex items-center gap-2 p-3 mb-3 bg-green-50 border border-green-200 rounded-xl text-sm text-green-700">
              <CheckCircle className="w-4 h-4" />
              <span>已成功创建 1 个 Campaign / 1 个 AdGroup / {adsList.length} 个 Ad</span>
            </div>
          )}
          <div className="text-xs space-y-1 font-mono text-gray-600">
            <div>Campaign: {renderStepResult(created?.campaign, 'campaign_id')}</div>
            <div>AdGroup:  {renderStepResult(created?.adgroup, 'adgroup_id')}</div>
          </div>

          {/* Ad 批量结果表 */}
          {adsList.length > 0 && (
            <div className="mt-3">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-gray-700">Ad 创建结果（{adsList.length} 个）</span>
                {summary && (
                  <span className="text-[11px] text-gray-400">
                    total={summary.total} · <span className="text-green-600">success={summary.success}</span> · <span className="text-red-500">fail={summary.fail}</span>
                  </span>
                )}
              </div>
              <div className="border border-gray-100 rounded-lg overflow-hidden">
                <table className="w-full text-[11px]">
                  <thead className="bg-gray-50 text-gray-500">
                    <tr>
                      <th className="px-2 py-1.5 text-left font-medium w-8">#</th>
                      <th className="px-2 py-1.5 text-left font-medium">Ad Name</th>
                      <th className="px-2 py-1.5 text-left font-medium">video_id</th>
                      <th className="px-2 py-1.5 text-left font-medium">状态</th>
                      <th className="px-2 py-1.5 text-left font-medium">ad_id / 失败原因</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {adsList.map((a, i) => (
                      <tr key={i} className={a.success ? '' : 'bg-red-50/30'}>
                        <td className="px-2 py-1.5 text-gray-400">{i + 1}</td>
                        <td className="px-2 py-1.5 text-gray-700 font-mono">{a.ad_name || '-'}</td>
                        <td className="px-2 py-1.5 text-gray-500 font-mono truncate max-w-[140px]" title={a.video_id || ''}>{a.video_id || '-'}</td>
                        <td className="px-2 py-1.5">
                          {a.success ? (
                            <span className="inline-flex items-center gap-1 text-green-600"><CheckCircle className="w-3 h-3" /> 成功</span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-red-500"><AlertCircle className="w-3 h-3" /> {a.skipped ? '已拦截' : '失败'}</span>
                          )}
                        </td>
                        <td className="px-2 py-1.5 text-gray-600 font-mono break-all">
                          {a.success ? (a.ad_id || '-') : (a.error || a.reason || '-')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </SectionCard>
      )}

      {/* ───── 资产库 PickerDialog（懒挂载） ───── */}
      <RegionGroupPickerDialog
        open={showRegionPicker}
        onClose={() => setShowRegionPicker(false)}
        onSelect={(item) => {
          // 把地区组的 country_codes 直接同步到 countryCodes，
          // codesToLocationIds 只会保留本地映射里有的国家（其余忽略，UI 会提示）
          setCountryCodes(item.country_codes)
          setRegionGroupId(item.id)
          setRegionGroupName(item.name)
          setRegionMode('group')
        }}
      />

      <LandingPagePickerDialog
        open={showLandingPicker}
        onClose={() => setShowLandingPicker(false)}
        onSelect={(item) => {
          setLandingPageUrl(item.landing_page_url)
          setLandingPageId(item.id)
          setLandingPageName(item.name)
        }}
      />

      <CopyPackPickerDialog
        open={showCopyPicker}
        onClose={() => setShowCopyPicker(false)}
        onSelect={(item, mode) => {
          // mode = 'all' 全部覆盖；'empty' 仅填充空白
          const fillAll = mode === 'all'
          if (item.primary_text && (fillAll || !adText.trim())) setAdText(item.primary_text)
          if (item.headline && (fillAll || !adTitle.trim())) setAdTitle(item.headline)
          setCopyPackId(item.id)
          setCopyPackName(item.name)
        }}
      />

      {/* 视频素材统一选择器（系统素材 / 本地批量上传 / 账户素材） */}
      <TikTokVideoMaterialPicker
        open={showVideoPicker}
        advertiserId={advertiserId}
        value={pickedVideos}
        onChange={setPickedVideos}
        onClose={() => setShowVideoPicker(false)}
      />
    </>
  )
}

/** 派生：把全量模板列表里的 W2A 模板筛出来 */
export function useW2aTemplates(allTemplates: Template[] | undefined): Template[] {
  return useMemo(() => {
    if (!allTemplates) return []
    return allTemplates.filter(isTikTokWebToAppTpl)
  }, [allTemplates])
}
