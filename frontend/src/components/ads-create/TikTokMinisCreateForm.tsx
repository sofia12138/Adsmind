import { useLaunchDraft } from './useLaunchDraft'
/**
 * TikTok Minis 新建广告子表单（嵌入到统一新建广告页中使用）
 *
 * 不再单独占据一个路由/页面，由 AdsCreatePage 在选中 minis 模板时挂载。
 * 模板的选择 (selectedTpl) 由父组件维护并通过 props 注入，避免双 Source of Truth。
 */
import { useState, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, AlertCircle, CheckCircle, Send, Shield } from 'lucide-react'
import { SectionCard } from '@/components/common/SectionCard'
import type { Template } from '@/services/templates'
import { fetchTikTokAdvertisers, type Advertiser } from '@/services/advertisers'
import { fetchMaterialList, type TikTokMaterialRecord } from '@/services/tiktok-materials'
import { TikTokLocationPicker, resolveCountryCodesFromTemplate } from '@/components/common/TikTokLocationPicker'
import { TikTokIdentityPicker } from '@/components/common/TikTokIdentityPicker'
import { codesToLocationIds, type LocationSelection } from '@/constants/tiktok-locations'
import { DEFAULT_DELIVERY_LANGUAGE } from '@/constants/deliveryLanguages'
import DeliveryLanguageSelect from '@/components/ads-create/DeliveryLanguageSelect'

const inputCls = 'w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-pink-500/20 focus:border-pink-400 transition'

export function isTikTokMinisBasicTpl(t: Template | null | undefined): boolean {
  if (!t) return false
  return t.platform === 'tiktok' && t.template_type === 'tiktok_minis_basic'
}

interface LaunchResult {
  draft_saved?: boolean
  data?: {
    platform?: string
    template_type?: string
    campaign?: { success: boolean; campaign_id?: string; error?: string; skipped?: boolean; reason?: string; hint?: string }
    adgroup?: { success: boolean; adgroup_id?: string; error?: string; skipped?: boolean; reason?: string; hint?: string }
    ad?: { success: boolean; ad_id?: string; ad_name?: string; error?: string; skipped?: boolean; reason?: string; hint?: string }
    summary?: { total: number; success: number; fail: number }
  }
  error?: string
}

interface Props {
  /** 当前选中的 minis 模板（必须是 tiktok_minis_basic） */
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
  // 后端识别出业务能力问题时会附带 hint，优先展示给用户
  if (step.hint) return `失败 → ${step.hint}（原始: ${step.error ?? ''}）`
  return `失败 → ${step.error ?? '未知错误'}`
}

export default function TikTokMinisCreateForm({ tpl }: Props) {
  const { launch, dialog } = useLaunchDraft()
  const { data: advResp } = useQuery({ queryKey: ['tiktok-advertisers'], queryFn: fetchTikTokAdvertisers })
  const advertisers: Advertiser[] = advResp?.data ?? []

  // ── 表单字段 ──
  const [advertiserId, setAdvertiserId] = useState('')
  const budgetCurrency = advertisers.find(a => a.advertiser_id === advertiserId)?.currency || ''
  const [campaignName, setCampaignName] = useState('')
  const [adgroupName, setAdgroupName] = useState('')
  const [adName, setAdName] = useState('')
  const [budget, setBudget] = useState('50')
  const [roasBid, setRoasBid] = useState('')
  const [scheduleStartTime, setScheduleStartTime] = useState('')
  const [scheduleEndTime, setScheduleEndTime] = useState('')
  const [identityId, setIdentityId] = useState('')
  const [identityType, setIdentityType] = useState('CUSTOMIZED_USER')
  const [appId, setAppId] = useState('')
  const [minisId, setMinisId] = useState('')
  const [countryCodes, setCountryCodes] = useState<string[]>([])
  const [adText, setAdText] = useState('')
  const [landingUrl, setLandingUrl] = useState('')
  const [videoMaterialId, setVideoMaterialId] = useState<number | null>(null)
  const [selectedDeliveryLanguage, setSelectedDeliveryLanguage] = useState<string>(DEFAULT_DELIVERY_LANGUAGE)

  // 切换模板时回填默认值（强制覆盖，避免上一个模板残留）
  useEffect(() => {
    if (!tpl) return
    const defaults = (tpl.defaults as Record<string, unknown>) ?? {}
    const adgroup = (tpl.adgroup as Record<string, unknown>) ?? {}
    if (defaults.app_id) setAppId(String(defaults.app_id))
    if (defaults.minis_id) setMinisId(String(defaults.minis_id))

    const selection = (defaults.location_selection as LocationSelection | undefined) ?? null
    const fallbackIds = Array.isArray(defaults.location_ids)
      ? (defaults.location_ids as unknown[]).map(String)
      : []
    setCountryCodes(resolveCountryCodesFromTemplate(selection, fallbackIds))

    const tplIdentityId = (defaults.identity_id as string | undefined) || ''
    const tplIdentityType = (defaults.identity_type as string | undefined) || ''
    setIdentityId(tplIdentityId)
    if (tplIdentityType) setIdentityType(tplIdentityType)

    if (adgroup.default_budget) setBudget(String(adgroup.default_budget))
    if (adgroup.default_roas_bid) setRoasBid(String(adgroup.default_roas_bid))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tpl?.id])

  // ── 拉取所选广告主下的 TikTok 素材库（success 状态） ──
  const { data: matsResp } = useQuery({
    queryKey: ['tiktok-materials', advertiserId, 'success'],
    queryFn: () => fetchMaterialList({ advertiser_id: advertiserId, status: 'success', page_size: 50 }),
    enabled: !!advertiserId,
  })
  const materials: TikTokMaterialRecord[] = matsResp?.data?.items ?? []

  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<LaunchResult | null>(null)
  const [errorMsg, setErrorMsg] = useState('')

  function validate(): string | null {
    if (!advertiserId) return '请选择广告主'
    if (!campaignName.trim()) return 'Campaign Name 不能为空'
    if (!appId.trim()) return 'App ID 不能为空'
    if (!minisId.trim()) return 'Minis ID 不能为空'
    if (!identityId.trim()) return '请选择 Identity（TikTok 广告必填）'
    if (countryCodes.length === 0) return '请至少选择 1 个投放国家'
    if (!videoMaterialId) return '请选择视频素材'
    const mat = materials.find(m => m.id === videoMaterialId)
    if (!mat?.tiktok_video_id) return '所选素材没有 tiktok_video_id（请确认素材已上传成功）'
    const b = Number(budget)
    if (!Number.isFinite(b) || b <= 0) return '日预算必须为正数'
    return null
  }

  async function handleSubmit() {
    setErrorMsg(''); setResult(null)
    const err = validate()
    if (err) { setErrorMsg(err); return }
    const mat = materials.find(m => m.id === videoMaterialId)!

    const payload: Record<string, unknown> = {
      template_id: tpl.id,
      advertiser_id: advertiserId,
      campaign_name: campaignName.trim(),
      adgroup_name: adgroupName.trim() || campaignName.trim(),
      ad_name: adName.trim() || adgroupName.trim() || campaignName.trim(),
      budget: Number(budget),
      budget_currency: budgetCurrency,
      app_id: appId.trim(),
      minis_id: minisId.trim(),
      identity_id: identityId.trim(),
      identity_type: identityType,
      video_id: mat.tiktok_video_id,
      ad_text: adText,
      landing_url: landingUrl.trim(),
      location_ids: codesToLocationIds(countryCodes),
      selected_delivery_language: selectedDeliveryLanguage,
    }
    if (roasBid) payload.roas_bid = Number(roasBid)
    if (scheduleStartTime) payload.schedule_start_time = scheduleStartTime
    if (scheduleEndTime) payload.schedule_end_time = scheduleEndTime

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
  const overallSuccess = !!created && created.campaign?.success && created.adgroup?.success && created.ad?.success

  return (
    <>
      {dialog}
      {isSystemTpl && (
        <div className="flex items-start gap-2 p-3 mb-5 bg-amber-50 border border-amber-200 rounded-xl">
          <Shield className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-700">
            当前选择的是系统母版（只读）。如需保存自定义配置，请先在「模板管理」页另存为业务模板再使用。
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
            <input value={campaignName} onChange={e => setCampaignName(e.target.value)} className={inputCls} placeholder="例：102-AIGC-US-小程序-TROAS-0.8-20260422-XX-1" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">AdGroup Name</label>
              <input value={adgroupName} onChange={e => setAdgroupName(e.target.value)} className={inputCls} placeholder="留空则使用 Campaign Name" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Ad Name</label>
              <input value={adName} onChange={e => setAdName(e.target.value)} className={inputCls} placeholder="留空则使用 AdGroup Name" />
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
            <label className="block text-xs font-medium text-gray-600 mb-1">ROAS 出价（VO_MIN_ROAS）</label>
            <input type="number" value={roasBid} onChange={e => setRoasBid(e.target.value)} className={inputCls} min="0.1" step="0.1" placeholder="如 0.8" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">投放开始时间</label>
            <input type="datetime-local" value={scheduleStartTime} onChange={e => setScheduleStartTime(e.target.value.replace('T', ' '))} className={inputCls} />
            <p className="text-xs text-gray-400 mt-1">留空则使用 SCHEDULE_FROM_NOW（立即开始）</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">投放结束时间</label>
            <input type="datetime-local" value={scheduleEndTime} onChange={e => setScheduleEndTime(e.target.value.replace('T', ' '))} className={inputCls} />
          </div>
        </div>
      </SectionCard>

      {/* 定向与小程序 */}
      <SectionCard title="定向与小程序" className="mb-5">
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">投放地区 <span className="text-red-400">*</span></label>
            <TikTokLocationPicker
              value={countryCodes}
              onChange={({ country_codes }) => setCountryCodes(country_codes)}
            />
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
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">App ID（minis 宿主 app）<span className="text-red-400">*</span></label>
              <input value={appId} onChange={e => setAppId(e.target.value)} className={inputCls} placeholder="如 7613116626166104080" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Minis ID <span className="text-red-400">*</span></label>
              <input value={minisId} onChange={e => setMinisId(e.target.value)} className={inputCls} placeholder="如 mnu8f8spjpxjy7oa" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Minis 跳转路径 / 落地参数（可选）</label>
            <input value={landingUrl} onChange={e => setLandingUrl(e.target.value)} className={inputCls} placeholder="如 minis://path?utm_source=tiktok" />
          </div>
        </div>
      </SectionCard>

      {/* 创意（Identity + 视频 + 文案） */}
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
            <label className="block text-xs font-medium text-gray-600 mb-1">视频素材 <span className="text-red-400">*</span></label>
            {!advertiserId ? (
              <p className="text-xs text-gray-400">请先选择广告主</p>
            ) : materials.length === 0 ? (
              <p className="text-xs text-gray-400">该广告主下暂无成功上传的视频素材，请先在「TikTok 素材上传」页上传</p>
            ) : (
              <select value={videoMaterialId ?? ''} onChange={e => setVideoMaterialId(e.target.value ? Number(e.target.value) : null)} className={`${inputCls} bg-white`}>
                <option value="">请选择视频</option>
                {materials.filter(m => m.tiktok_video_id).map(m => (
                  <option key={m.id} value={m.id}>{m.local_file_name} · {m.tiktok_video_id}</option>
                ))}
              </select>
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">广告文案 (Ad Text)</label>
            <textarea value={adText} onChange={e => setAdText(e.target.value)} className={inputCls} rows={3} placeholder="广告主标题/描述" />
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
              <span>已成功创建 1 个 Campaign / 1 个 AdGroup / 1 个 Ad</span>
            </div>
          )}
          <div className="text-xs space-y-1 font-mono text-gray-600">
            <div>Campaign: {renderStepResult(created?.campaign, 'campaign_id')}</div>
            <div>AdGroup:  {renderStepResult(created?.adgroup, 'adgroup_id')}</div>
            <div>Ad:       {renderStepResult(created?.ad, 'ad_id')}</div>
            {summary && <div className="text-gray-400">summary: total={summary.total} success={summary.success} fail={summary.fail}</div>}
          </div>
        </SectionCard>
      )}
    </>
  )
}

/** 派生：把全量模板列表里的 minis 模板筛出来（按业务/系统排序） */
export function useMinisTemplates(allTemplates: Template[] | undefined): Template[] {
  return useMemo(() => {
    if (!allTemplates) return []
    return allTemplates.filter(isTikTokMinisBasicTpl)
  }, [allTemplates])
}
