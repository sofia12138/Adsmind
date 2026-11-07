import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { CountryMultiSelect } from '@/components/common/CountryMultiSelect'
import {
  Loader2, AlertCircle, Trash2, Pencil, Copy, X, Eye,
  ToggleLeft, ToggleRight, ChevronLeft, Shield, Save, Package,
  Send,
} from 'lucide-react'
import {
  LandingPagePickerDialog,
  CopyPackPickerDialog,
  RegionGroupPickerDialog,
} from '@/components/common/AssetPickerDialog'
import type { LandingPageAsset, CopyPackAsset, RegionGroupAsset } from '@/services/ad-assets'
import {
  useTemplates, useUpdateTemplate, useDeleteTemplate, useCloneTemplate,
} from '@/hooks/use-templates'
import type { Template } from '@/services/templates'
import { locationIdsToCodes as locationIdsToCodesPreview } from '@/constants/tiktok-locations'
import { fetchMetaAccounts, type MetaAccount } from '@/services/advertisers'
import {
  fetchMetaPages, fetchMetaPixels,
  type MetaPageOption, type MetaPixelOption,
} from '@/services/meta-assets'
import {
  DELIVERY_LANGUAGE_OPTIONS,
  DEFAULT_DELIVERY_LANGUAGES,
  DEFAULT_DELIVERY_LANGUAGE,
  deliveryLanguageLabel,
  normalizeTemplateDeliveryLanguages,
} from '@/constants/deliveryLanguages'

/* ═══════════════════════════════════════════════════
   内置模板 ID 集合 — 前端判断是否为母版
   ═══════════════════════════════════════════════════ */
const BUILTIN_IDS = new Set([
  'tpl_tiktok_android_purchase',
  'tpl_web_to_app',
  'tpl_miniapp_troas',
  'tpl_meta_us_aeo',
  'tpl_meta_web_to_app_basic_abo',
  'tpl_meta_web_to_app_conv_abo',
  'tpl_meta_web_to_app_conv_cbo',
])

function isBuiltin(t: Template): boolean {
  return BUILTIN_IDS.has(t.id) || Boolean(t.is_builtin)
}

function isMetaW2aConv(t: Template): boolean {
  if (t.platform !== 'meta') return false
  // ABO（含基础 W2A）
  if (t.template_type === 'web_to_app' && t.template_subtype === 'conversion') return true
  // CBO（W2A Conversion CBO）
  if (t.template_type === 'web_to_app_conversion_cbo') return true
  return false
}

function isSystemMaster(t: Template): boolean {
  return Boolean(t.is_system)
}

function isTikTokMinisBasic(t: Template): boolean {
  return t.platform === 'tiktok' && t.template_type === 'tiktok_minis_basic'
}

function isTikTokWebToApp(t: Template): boolean {
  return t.platform === 'tiktok' && t.template_type === 'tiktok_web_to_app'
}

/** 是否支持从模板管理页跳转到新建广告页直接使用 */
function canLaunchFromTemplatesPage(t: Template): boolean {
  return isTikTokMinisBasic(t) || isTikTokWebToApp(t)
}

/* ═══════════════════════════════════════════════════
   固定枚举
   ═══════════════════════════════════════════════════ */
const OBJECTIVES = [
  { value: 'OUTCOME_SALES', label: 'OUTCOME_SALES (转化/销售)' },
  { value: 'OUTCOME_TRAFFIC', label: 'OUTCOME_TRAFFIC (流量)' },
  { value: 'OUTCOME_LEADS', label: 'OUTCOME_LEADS (线索)' },
  { value: 'OUTCOME_APP_PROMOTION', label: 'OUTCOME_APP_PROMOTION (应用推广)' },
  { value: 'OUTCOME_ENGAGEMENT', label: 'OUTCOME_ENGAGEMENT (互动)' },
  { value: 'OUTCOME_AWARENESS', label: 'OUTCOME_AWARENESS (品牌知名度)' },
] as const

const OPT_GOALS = [
  { value: 'OFFSITE_CONVERSIONS', label: 'OFFSITE_CONVERSIONS (站外转化)' },
  { value: 'LANDING_PAGE_VIEWS', label: 'LANDING_PAGE_VIEWS (落地页浏览)' },
  { value: 'LINK_CLICKS', label: 'LINK_CLICKS (链接点击)' },
  { value: 'IMPRESSIONS', label: 'IMPRESSIONS (展示)' },
  { value: 'REACH', label: 'REACH (触达)' },
  { value: 'APP_INSTALLS', label: 'APP_INSTALLS (应用安装)' },
  { value: 'APP_EVENTS', label: 'APP_EVENTS (应用事件)' },
  { value: 'VALUE', label: 'VALUE (价值优化)' },
] as const

const BILLING_EVENTS = [
  { value: 'IMPRESSIONS', label: 'IMPRESSIONS (按展示计费)' },
  { value: 'LINK_CLICKS', label: 'LINK_CLICKS (按点击计费)' },
] as const

const CTA_OPTIONS = [
  'LEARN_MORE', 'SHOP_NOW', 'INSTALL_NOW', 'SIGN_UP',
  'WATCH_MORE', 'DOWNLOAD', 'GET_OFFER', 'ORDER_NOW',
  'SUBSCRIBE', 'CONTACT_US', 'BOOK_NOW', 'APPLY_NOW',
] as const

const EVENT_TYPES = [
  { value: 'PURCHASE', label: 'PURCHASE (购买)' },
  { value: 'COMPLETE_REGISTRATION', label: 'COMPLETE_REGISTRATION (完成注册)' },
  { value: 'LEAD', label: 'LEAD (线索)' },
  { value: 'INITIATE_CHECKOUT', label: 'INITIATE_CHECKOUT (发起结账)' },
  { value: 'ADD_TO_CART', label: 'ADD_TO_CART (加入购物车)' },
  { value: 'VIEW_CONTENT', label: 'VIEW_CONTENT (查看内容)' },
  { value: 'SEARCH', label: 'SEARCH (搜索)' },
  { value: 'CONTACT', label: 'CONTACT (联系)' },
  { value: 'SUBSCRIBE', label: 'SUBSCRIBE (订阅)' },
  { value: 'START_TRIAL', label: 'START_TRIAL (开始试用)' },
] as const

const BID_STRATEGIES = [
  { value: 'LOWEST_COST_WITHOUT_CAP', label: '最低成本 (自动出价)' },
  { value: 'COST_CAP', label: '成本上限 (Cost Cap)' },
  { value: 'BID_CAP', label: '出价上限 (Bid Cap)' },
] as const

const inputCls = 'w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition'

/* ═══════════════════════════════════════════════════
   编辑 state 类型 + 转换
   ═══════════════════════════════════════════════════ */
interface W2aEditState {
  name: string
  adAccountId: string
  pageId: string
  pixelId: string
  customEventType: string
  countries: string[]
  objective: string
  optimizationGoal: string
  billingEvent: string
  callToAction: string
  bidStrategy: string
  landingPageUrl: string
  primaryText: string
  headline: string
  description: string
  dailyBudget: string
  ageMin: string
  ageMax: string
  notes: string
  // asset refs + snapshots
  landing_page_asset_id?: number
  landing_page_asset_name?: string
  landing_page_url_snapshot?: string
  copy_asset_id?: number
  copy_asset_name?: string
  primary_text_snapshot?: string
  headline_snapshot?: string
  description_snapshot?: string
  region_group_id?: number
  region_group_name?: string
  country_codes_snapshot?: string[]
  // 投放语种（强制开启平台语言定向）
  deliveryLanguages: string[]
  defaultDeliveryLanguage: string
}

function templateToEditState(t: Template): W2aEditState {
  const campaign = (t.campaign ?? {}) as Record<string, unknown>
  const adset = (t.adset ?? {}) as Record<string, unknown>
  const creative = (t.creative ?? {}) as Record<string, unknown>
  const targeting = (adset.targeting ?? {}) as Record<string, unknown>
  const geoLocations = (targeting.geo_locations ?? {}) as Record<string, unknown>
  const po = (adset.promoted_object ?? {}) as Record<string, unknown>
  const dl = normalizeTemplateDeliveryLanguages({
    delivery_languages: t.delivery_languages,
    default_delivery_language: t.default_delivery_language,
  })

  return {
    name: t.name || '',
    adAccountId: String(t.default_ad_account_id ?? ''),
    pageId: String(creative.page_id ?? ''),
    pixelId: String(po.pixel_id ?? ''),
    customEventType: String(po.custom_event_type ?? ''),
    countries: Array.isArray(geoLocations.countries) ? geoLocations.countries : ['US'],
    objective: String(campaign.objective ?? 'OUTCOME_SALES'),
    optimizationGoal: String(adset.optimization_goal ?? 'OFFSITE_CONVERSIONS'),
    billingEvent: String(adset.billing_event ?? 'IMPRESSIONS'),
    callToAction: String(creative.call_to_action ?? 'LEARN_MORE'),
    bidStrategy: String(adset.bid_strategy ?? 'LOWEST_COST_WITHOUT_CAP'),
    landingPageUrl: String(creative.link ?? ''),
    primaryText: String(creative.primary_text ?? ''),
    headline: String(creative.headline ?? ''),
    description: String(creative.description ?? ''),
    dailyBudget: adset.daily_budget ? String(Number(adset.daily_budget) / 100) : '50',
    ageMin: String((targeting.age_min as number) ?? 18),
    ageMax: String((targeting.age_max as number) ?? 65),
    notes: String(t.notes ?? ''),
    landing_page_asset_id: t.landing_page_asset_id as number | undefined,
    landing_page_asset_name: t.landing_page_asset_name as string | undefined,
    landing_page_url_snapshot: t.landing_page_url_snapshot as string | undefined,
    copy_asset_id: t.copy_asset_id as number | undefined,
    copy_asset_name: t.copy_asset_name as string | undefined,
    primary_text_snapshot: t.primary_text_snapshot as string | undefined,
    headline_snapshot: t.headline_snapshot as string | undefined,
    description_snapshot: t.description_snapshot as string | undefined,
    region_group_id: t.region_group_id as number | undefined,
    region_group_name: t.region_group_name as string | undefined,
    country_codes_snapshot: t.country_codes_snapshot as string[] | undefined,
    deliveryLanguages: dl.delivery_languages,
    defaultDeliveryLanguage: dl.default_delivery_language,
  }
}

function editStateToBody(s: W2aEditState, source?: Template | null): Record<string, unknown> {
  const dl = normalizeTemplateDeliveryLanguages({
    delivery_languages: s.deliveryLanguages,
    default_delivery_language: s.defaultDeliveryLanguage,
  })
  // 保留源模板的 template_type / subtype，避免 CBO 副本被静默降级为 ABO
  const tplType = (source?.template_type as string) || 'web_to_app'
  const tplSubtype = (source?.template_subtype as string)
    || (tplType === 'web_to_app_conversion_cbo' ? 'conversion_cbo' : 'conversion')
  return {
    name: s.name,
    platform: 'meta',
    template_type: tplType,
    template_subtype: tplSubtype,
    default_ad_account_id: s.adAccountId || undefined,
    notes: s.notes || undefined,
    delivery_languages: dl.delivery_languages,
    default_delivery_language: dl.default_delivery_language,
    landing_page_asset_id: s.landing_page_asset_id || undefined,
    landing_page_asset_name: s.landing_page_asset_name || undefined,
    landing_page_url_snapshot: s.landing_page_url_snapshot || undefined,
    copy_asset_id: s.copy_asset_id || undefined,
    copy_asset_name: s.copy_asset_name || undefined,
    primary_text_snapshot: s.primary_text_snapshot || undefined,
    headline_snapshot: s.headline_snapshot || undefined,
    description_snapshot: s.description_snapshot || undefined,
    region_group_id: s.region_group_id || undefined,
    region_group_name: s.region_group_name || undefined,
    country_codes_snapshot: s.country_codes_snapshot || undefined,
    campaign: {
      objective: s.objective,
      status: 'PAUSED',
      special_ad_categories: [],
      is_adset_budget_sharing_enabled: false,
    },
    adset: {
      billing_event: s.billingEvent,
      optimization_goal: s.optimizationGoal,
      daily_budget: Math.round(Number(s.dailyBudget || '50') * 100),
      bid_strategy: s.bidStrategy,
      status: 'PAUSED',
      targeting: {
        geo_locations: { countries: s.countries.length ? s.countries : ['US'] },
        age_min: Number(s.ageMin) || 18,
        age_max: Number(s.ageMax) || 65,
      },
      promoted_object: {
        pixel_id: s.pixelId,
        custom_event_type: s.customEventType,
      },
    },
    creative: {
      page_id: s.pageId,
      primary_text: s.primaryText,
      headline: s.headline,
      description: s.description,
      call_to_action: s.callToAction,
      link: s.landingPageUrl,
      image_hash: '',
      video_id: '',
    },
    ad: { status: 'PAUSED' },
  }
}

/* ═══════════════════════════════════════════════════
   主组件
   ═══════════════════════════════════════════════════ */
export default function TemplatesPage() {
  const navigate = useNavigate()
  const { data: templates, isLoading, isError } = useTemplates()
  const updateMutation = useUpdateTemplate()
  const deleteMutation = useDeleteTemplate()
  const cloneMutation = useCloneTemplate()

  // 系统母版只读预览弹窗
  const [systemPreview, setSystemPreview] = useState<Template | null>(null)

  // 视图状态
  type View = 'list' | 'view' | 'edit'
  const [view, setView] = useState<View>('list')
  const [currentTpl, setCurrentTpl] = useState<Template | null>(null)
  const [w2aEdit, setW2aEdit] = useState<W2aEditState | null>(null)

  // 另存为弹窗
  const [cloneOpen, setCloneOpen] = useState(false)
  const [cloneSourceId, setCloneSourceId] = useState('')
  const [cloneName, setCloneName] = useState('')
  const [cloneNotes, setCloneNotes] = useState('')
  const [cloneSuccess, setCloneSuccess] = useState('')

  // Meta API 联动
  const [metaAccounts, setMetaAccounts] = useState<MetaAccount[]>([])
  const [pages, setPages] = useState<MetaPageOption[]>([])
  const [pixels, setPixels] = useState<MetaPixelOption[]>([])
  const [pagesLoading, setPagesLoading] = useState(false)
  const [pixelsLoading, setPixelsLoading] = useState(false)
  const [pagesError, setPagesError] = useState('')
  const [pixelsError, setPixelsError] = useState('')

  useEffect(() => {
    fetchMetaAccounts()
      .then(r => setMetaAccounts(r.data ?? []))
      .catch(() => {})
  }, [])

  const currentAdAccount = w2aEdit?.adAccountId ?? ''
  useEffect(() => {
    if (!currentAdAccount) {
      setPages([]); setPixels([])
      setPagesError(''); setPixelsError('')
      return
    }
    setPagesLoading(true); setPagesError('')
    fetchMetaPages(currentAdAccount)
      .then(r => setPages(r.data ?? []))
      .catch(e => setPagesError(String(e)))
      .finally(() => setPagesLoading(false))
    setPixelsLoading(true); setPixelsError('')
    fetchMetaPixels(currentAdAccount)
      .then(r => setPixels(r.data ?? []))
      .catch(e => setPixelsError(String(e)))
      .finally(() => setPixelsLoading(false))
  }, [currentAdAccount])

  /* ── 列表筛选 ── */
  // 系统母版区：所有 is_system === true 的模板（含 TikTok Minis、Meta W2A Conv ABO）
  const systemTemplates = useMemo(
    () => (templates ?? []).filter(isSystemMaster),
    [templates],
  )
  // Meta W2A 业务模板：用户基于 Meta W2A 母版另存的副本，在下方「我的业务模板」展示
  const w2aTemplates = useMemo(() =>
    (templates ?? []).filter(isMetaW2aConv),
    [templates],
  )
  const businessTpls = useMemo(() => w2aTemplates.filter(t => !isBuiltin(t)), [w2aTemplates])

  /* ── 操作 ── */
  function openView(t: Template) {
    setCurrentTpl(t); setW2aEdit(templateToEditState(t)); setView('view')
  }
  function openEdit(t: Template) {
    setCurrentTpl(t); setW2aEdit(templateToEditState(t)); setView('edit')
  }
  function goBack() {
    setView('list'); setCurrentTpl(null); setW2aEdit(null)
  }

  function openCloneDialog(sourceId: string, sourceName: string) {
    setCloneSourceId(sourceId)
    setCloneName(`${sourceName} - 副本`)
    setCloneNotes('')
    setCloneSuccess('')
    setCloneOpen(true)
  }

  function handleClone() {
    if (!cloneName.trim()) return
    cloneMutation.mutate(
      { tplId: cloneSourceId, body: { name: cloneName.trim(), notes: cloneNotes.trim() || undefined } },
      {
        onSuccess: (newTpl) => {
          setCloneSuccess(`模板「${newTpl.name}」创建成功`)
          setTimeout(() => {
            setCloneOpen(false)
            openEdit(newTpl)
          }, 800)
        },
      },
    )
  }

  function handleSave() {
    if (!w2aEdit || !currentTpl || !w2aEdit.name.trim()) return
    const body = editStateToBody(w2aEdit, currentTpl)
    updateMutation.mutate({ tplId: currentTpl.id, body }, { onSuccess: goBack })
  }

  function handleDelete(tplId: string) {
    if (!confirm('确定删除此业务模板？')) return
    deleteMutation.mutate(tplId)
  }

  function handleToggleStatus(t: Template) {
    const newStatus = String(t.status ?? 'active') === 'active' ? 'disabled' : 'active'
    updateMutation.mutate({ tplId: t.id, body: { status: newStatus } })
  }

  function setField<K extends keyof W2aEditState>(key: K, val: W2aEditState[K]) {
    setW2aEdit(prev => prev ? { ...prev, [key]: val } : prev)
  }

  function handleAdAccountChange(val: string) {
    setW2aEdit(prev => {
      if (!prev) return prev
      const next = { ...prev, adAccountId: val }
      if (prev.adAccountId && prev.adAccountId !== val) {
        next.pageId = ''; next.pixelId = ''
      }
      return next
    })
  }

  const isPending = updateMutation.isPending || cloneMutation.isPending

  // ── 资产库弹窗 ──
  const [showLPPicker, setShowLPPicker] = useState(false)
  const [showCopyPicker, setShowCopyPicker] = useState(false)
  const [showRegionPicker, setShowRegionPicker] = useState(false)

  /* ═══════════════════════════════════════════════
     渲染：查看/编辑详情页
     ═══════════════════════════════════════════════ */
  if ((view === 'view' || view === 'edit') && currentTpl && w2aEdit) {
    const readonly = view === 'view'
    const tplIsBuiltin = isBuiltin(currentTpl)
    return (
      <div className="max-w-5xl mx-auto">
        {/* 顶栏 */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <button onClick={goBack} className="p-2 rounded-lg hover:bg-gray-100 transition text-gray-500">
              <ChevronLeft className="w-5 h-5" />
            </button>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-semibold text-gray-800">
                  {readonly ? '查看模板' : '编辑模板'}
                </h1>
                {tplIsBuiltin && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-600 border border-amber-200">
                    <Shield className="w-3 h-3" /> 系统默认
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-400 mt-0.5">Meta Web to App Conversion (ABO)</p>
            </div>
          </div>
          {tplIsBuiltin && readonly && (
            <button
              onClick={() => openCloneDialog(currentTpl.id, currentTpl.name)}
              className="px-4 py-2 bg-blue-500 text-white text-sm rounded-xl hover:bg-blue-600 transition font-medium flex items-center gap-1.5"
            >
              <Copy className="w-4 h-4" /> 另存为业务模板
            </button>
          )}
        </div>

        {/* 只读提示 */}
        {readonly && tplIsBuiltin && (
          <div className="flex items-start gap-3 p-4 mb-5 bg-amber-50 border border-amber-200 rounded-xl">
            <Shield className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-amber-700">这是系统默认模板（母版）</p>
              <p className="text-xs text-amber-600 mt-1">
                不支持直接编辑。请点击右上角「另存为业务模板」创建副本后再修改。
              </p>
            </div>
          </div>
        )}

        {/* A. 下拉选择配置区 */}
        <SectionCard title="投放策略配置" className="mb-5">
          <div className="space-y-5">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">模板名称 <span className="text-red-400">*</span></label>
              <input value={w2aEdit.name} onChange={e => setField('name', e.target.value)} disabled={readonly} placeholder="例：US-Pixel-Conv-ABO" className={`${inputCls} ${readonly ? 'bg-gray-50 text-gray-500' : ''}`} />
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">默认广告账户</label>
              <select value={w2aEdit.adAccountId} onChange={e => handleAdAccountChange(e.target.value)} disabled={readonly} className={`${inputCls} bg-white ${readonly ? '!bg-gray-50 text-gray-500' : ''}`}>
                <option value="">请选择 Meta 广告账户</option>
                {metaAccounts.map(a => <option key={a.id} value={a.id}>{a.name} ({a.id})</option>)}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">默认 Page</label>
                <select value={w2aEdit.pageId} onChange={e => setField('pageId', e.target.value)}
                  disabled={readonly || !w2aEdit.adAccountId || pagesLoading}
                  className={`${inputCls} bg-white ${readonly ? '!bg-gray-50 text-gray-500' : ''}`}>
                  <option value="">{!w2aEdit.adAccountId ? '请先选择广告账户' : pagesLoading ? '加载中...' : '请选择主页'}</option>
                  {pages.map(p => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}
                </select>
                {pagesError && <p className="text-xs text-red-400 mt-1">拉取失败: {pagesError}</p>}
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">默认 Pixel</label>
                <select value={w2aEdit.pixelId} onChange={e => setField('pixelId', e.target.value)}
                  disabled={readonly || !w2aEdit.adAccountId || pixelsLoading}
                  className={`${inputCls} bg-white ${readonly ? '!bg-gray-50 text-gray-500' : ''}`}>
                  <option value="">{!w2aEdit.adAccountId ? '请先选择广告账户' : pixelsLoading ? '加载中...' : '请选择 Pixel'}</option>
                  {pixels.map(p => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}
                </select>
                {pixelsError && <p className="text-xs text-red-400 mt-1">拉取失败: {pixelsError}</p>}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Custom Event Type</label>
                <select value={w2aEdit.customEventType} onChange={e => setField('customEventType', e.target.value)} disabled={readonly} className={`${inputCls} bg-white ${readonly ? '!bg-gray-50 text-gray-500' : ''}`}>
                  <option value="">请选择事件类型</option>
                  {EVENT_TYPES.map(e => <option key={e.value} value={e.value}>{e.label}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Call To Action</label>
                <select value={w2aEdit.callToAction} onChange={e => setField('callToAction', e.target.value)} disabled={readonly} className={`${inputCls} bg-white ${readonly ? '!bg-gray-50 text-gray-500' : ''}`}>
                  {CTA_OPTIONS.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-medium text-gray-600">投放国家/地区</label>
                {!readonly && (
                  <button type="button" onClick={() => setShowRegionPicker(true)} className="text-xs text-blue-500 hover:text-blue-600 flex items-center gap-1">
                    <Package className="w-3 h-3" />选择地区组
                  </button>
                )}
              </div>
              {readonly ? (
                <div className="flex flex-wrap gap-1.5 px-3 py-2 border border-gray-200 rounded-xl bg-gray-50 min-h-[42px]">
                  {w2aEdit.countries.map(c => (
                    <span key={c} className="inline-block px-2 py-0.5 rounded-md bg-blue-50 text-blue-600 text-xs font-medium">{c}</span>
                  ))}
                  {w2aEdit.countries.length === 0 && <span className="text-gray-400 text-sm">未设置</span>}
                </div>
              ) : (
                <CountryMultiSelect value={w2aEdit.countries} onChange={codes => setField('countries', codes)} />
              )}
              {w2aEdit.region_group_name && (
                <p className="text-xs text-blue-400 mt-1">
                  来源地区组: {w2aEdit.region_group_name}
                  {!readonly && <button type="button" className="text-gray-400 hover:text-red-400 ml-2" onClick={() => setW2aEdit(prev => prev ? { ...prev, region_group_id: undefined, region_group_name: undefined, country_codes_snapshot: undefined } : prev)}>清除引用</button>}
                </p>
              )}
            </div>

            <DeliveryLanguageEditor
              readonly={readonly}
              languages={w2aEdit.deliveryLanguages}
              defaultLanguage={w2aEdit.defaultDeliveryLanguage}
              onChange={(langs, defLang) => setW2aEdit(prev => prev ? {
                ...prev, deliveryLanguages: langs, defaultDeliveryLanguage: defLang,
              } : prev)}
            />

            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Campaign Objective</label>
                <select value={w2aEdit.objective} onChange={e => setField('objective', e.target.value)} disabled={readonly} className={`${inputCls} bg-white ${readonly ? '!bg-gray-50 text-gray-500' : ''}`}>
                  {OBJECTIVES.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Optimization Goal</label>
                <select value={w2aEdit.optimizationGoal} onChange={e => setField('optimizationGoal', e.target.value)} disabled={readonly} className={`${inputCls} bg-white ${readonly ? '!bg-gray-50 text-gray-500' : ''}`}>
                  {OPT_GOALS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Billing Event</label>
                <select value={w2aEdit.billingEvent} onChange={e => setField('billingEvent', e.target.value)} disabled={readonly} className={`${inputCls} bg-white ${readonly ? '!bg-gray-50 text-gray-500' : ''}`}>
                  {BILLING_EVENTS.map(b => <option key={b.value} value={b.value}>{b.label}</option>)}
                </select>
              </div>
            </div>

            <div className="max-w-xs">
              <label className="block text-xs font-medium text-gray-600 mb-1">出价策略</label>
              <select value={w2aEdit.bidStrategy} onChange={e => setField('bidStrategy', e.target.value)} disabled={readonly} className={`${inputCls} bg-white ${readonly ? '!bg-gray-50 text-gray-500' : ''}`}>
                {BID_STRATEGIES.map(b => <option key={b.value} value={b.value}>{b.label}</option>)}
              </select>
            </div>
          </div>
        </SectionCard>

        {/* B. 默认值配置区 */}
        <SectionCard title="创意与预算默认值" className="mb-5">
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-medium text-gray-600">Landing Page URL</label>
                {!readonly && (
                  <button type="button" onClick={() => setShowLPPicker(true)} className="text-xs text-blue-500 hover:text-blue-600 flex items-center gap-1">
                    <Package className="w-3 h-3" />从推广链接选择
                  </button>
                )}
              </div>
              <input value={w2aEdit.landingPageUrl} onChange={e => setField('landingPageUrl', e.target.value)} disabled={readonly} placeholder="https://example.com/landing" className={`${inputCls} ${readonly ? 'bg-gray-50 text-gray-500' : ''}`} />
              {w2aEdit.landing_page_asset_name && (
                <p className="text-xs text-blue-400 mt-1">
                  来源资产: {w2aEdit.landing_page_asset_name}
                  {!readonly && <button type="button" className="text-gray-400 hover:text-red-400 ml-2" onClick={() => setW2aEdit(prev => prev ? { ...prev, landing_page_asset_id: undefined, landing_page_asset_name: undefined, landing_page_url_snapshot: undefined } : prev)}>清除引用</button>}
                </p>
              )}
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-medium text-gray-600">Primary Text</label>
                {!readonly && (
                  <button type="button" onClick={() => setShowCopyPicker(true)} className="text-xs text-blue-500 hover:text-blue-600 flex items-center gap-1">
                    <Package className="w-3 h-3" />从文案库选择
                  </button>
                )}
              </div>
              <textarea value={w2aEdit.primaryText} onChange={e => setField('primaryText', e.target.value)} disabled={readonly} rows={2} placeholder="广告主文案" className={`${inputCls} ${readonly ? 'bg-gray-50 text-gray-500' : ''}`} />
              {w2aEdit.copy_asset_name && (
                <p className="text-xs text-blue-400 mt-1">
                  来源文案: {w2aEdit.copy_asset_name}
                  {!readonly && <button type="button" className="text-gray-400 hover:text-red-400 ml-2" onClick={() => setW2aEdit(prev => prev ? { ...prev, copy_asset_id: undefined, copy_asset_name: undefined, primary_text_snapshot: undefined, headline_snapshot: undefined, description_snapshot: undefined } : prev)}>清除引用</button>}
                </p>
              )}
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Headline</label>
                <input value={w2aEdit.headline} onChange={e => setField('headline', e.target.value)} disabled={readonly} placeholder="标题" className={`${inputCls} ${readonly ? 'bg-gray-50 text-gray-500' : ''}`} />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
                <input value={w2aEdit.description} onChange={e => setField('description', e.target.value)} disabled={readonly} placeholder="可选描述" className={`${inputCls} ${readonly ? 'bg-gray-50 text-gray-500' : ''}`} />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">日预算 (USD)</label>
                <input type="number" value={w2aEdit.dailyBudget} onChange={e => setField('dailyBudget', e.target.value)} disabled={readonly} placeholder="50" min="1" className={`${inputCls} ${readonly ? 'bg-gray-50 text-gray-500' : ''}`} />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">最小年龄</label>
                <input type="number" value={w2aEdit.ageMin} onChange={e => setField('ageMin', e.target.value)} disabled={readonly} min="13" max="65" className={`${inputCls} ${readonly ? 'bg-gray-50 text-gray-500' : ''}`} />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">最大年龄</label>
                <input type="number" value={w2aEdit.ageMax} onChange={e => setField('ageMax', e.target.value)} disabled={readonly} min="13" max="65" className={`${inputCls} ${readonly ? 'bg-gray-50 text-gray-500' : ''}`} />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">备注</label>
              <textarea value={w2aEdit.notes} onChange={e => setField('notes', e.target.value)} disabled={readonly} rows={2} placeholder="内部备注，不影响投放" className={`${inputCls} ${readonly ? 'bg-gray-50 text-gray-500' : ''}`} />
            </div>
          </div>
        </SectionCard>

        {/* 底部操作栏 */}
        <div className="flex items-center gap-3">
          {readonly ? (
            <button
              onClick={() => openCloneDialog(currentTpl.id, currentTpl.name)}
              className="px-5 py-2.5 bg-blue-500 text-white text-sm rounded-xl hover:bg-blue-600 transition font-medium flex items-center gap-1.5"
            >
              <Copy className="w-4 h-4" /> 另存为业务模板
            </button>
          ) : (
            <button
              onClick={handleSave}
              disabled={isPending || !w2aEdit.name.trim()}
              className="px-5 py-2.5 bg-blue-500 text-white text-sm rounded-xl hover:bg-blue-600 disabled:opacity-50 transition font-medium flex items-center gap-1.5"
            >
              <Save className="w-4 h-4" /> {isPending ? '保存中...' : '保存修改'}
            </button>
          )}
          <button onClick={goBack} className="px-5 py-2.5 bg-gray-100 text-gray-600 text-sm rounded-xl hover:bg-gray-200 transition">返回列表</button>
        </div>

        {/* 另存为弹窗 */}
        {cloneOpen && <CloneDialog
          name={cloneName} setName={setCloneName}
          notes={cloneNotes} setNotes={setCloneNotes}
          onSubmit={handleClone} onClose={() => setCloneOpen(false)}
          isPending={cloneMutation.isPending} success={cloneSuccess}
        />}

        {/* ── 资产库弹窗 ── */}
        <LandingPagePickerDialog
          open={showLPPicker}
          onClose={() => setShowLPPicker(false)}
          onSelect={(item: LandingPageAsset) => {
            setField('landingPageUrl', item.landing_page_url)
            setW2aEdit(prev => prev ? {
              ...prev,
              landingPageUrl: item.landing_page_url,
              landing_page_asset_id: item.id,
              landing_page_asset_name: item.name,
              landing_page_url_snapshot: item.landing_page_url,
            } : prev)
          }}
        />
        <CopyPackPickerDialog
          open={showCopyPicker}
          onClose={() => setShowCopyPicker(false)}
          onSelect={(item: CopyPackAsset, mode: 'all' | 'empty') => {
            setW2aEdit(prev => {
              if (!prev) return prev
              const next = { ...prev,
                copy_asset_id: item.id,
                copy_asset_name: item.name,
                primary_text_snapshot: item.primary_text || '',
                headline_snapshot: item.headline || '',
                description_snapshot: item.description || '',
              }
              if (mode === 'all') {
                next.primaryText = item.primary_text || ''
                next.headline = item.headline || ''
                next.description = item.description || ''
              } else {
                if (!prev.primaryText) next.primaryText = item.primary_text || ''
                if (!prev.headline) next.headline = item.headline || ''
                if (!prev.description) next.description = item.description || ''
              }
              return next
            })
          }}
        />
        <RegionGroupPickerDialog
          open={showRegionPicker}
          onClose={() => setShowRegionPicker(false)}
          onSelect={(item: RegionGroupAsset) => {
            setW2aEdit(prev => prev ? {
              ...prev,
              countries: item.country_codes,
              region_group_id: item.id,
              region_group_name: item.name,
              country_codes_snapshot: [...item.country_codes],
            } : prev)
          }}
        />
      </div>
    )
  }

  /* ═══════════════════════════════════════════════
     渲染：模板列表主页
     ═══════════════════════════════════════════════ */
  return (
    <div className="max-w-6xl mx-auto">
      <PageHeader title="模板管理" description="系统母版（只读） + 我的业务模板" />

      {/* ─── 系统母版区（含 TikTok Minis、Meta W2A 等所有 is_system 模板） ─── */}
      {!isLoading && !isError && systemTemplates.length > 0 && (
        <SectionCard
          title={`系统母版（${systemTemplates.length}）`}
          className="mb-5"
          extra={<span className="inline-flex items-center gap-1 text-amber-500 font-medium"><Shield className="w-3.5 h-3.5" /> 只读 · 可另存为</span>}
        >
          <div className="divide-y divide-gray-100">
            {systemTemplates.map(t => {
              const canLaunch = canLaunchFromTemplatesPage(t)
              const platformLabel = t.platform === 'tiktok' ? 'TikTok' : t.platform === 'meta' ? 'Meta' : String(t.platform)
              const platformBg = t.platform === 'tiktok' ? 'bg-pink-50 text-pink-600' : 'bg-indigo-50 text-indigo-600'
              return (
                <div key={t.id} className="flex items-center justify-between py-3 first:pt-0 last:pb-0">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-semibold text-gray-800 truncate">{t.name}</p>
                      <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${platformBg}`}>{platformLabel}</span>
                      <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-600 border border-amber-200">系统母版</span>
                      {t.template_type ? (
                        <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-500">{String(t.template_type)}</span>
                      ) : null}
                    </div>
                    <p className="text-xs text-gray-400 mt-1">
                      {t.template_key ? `key: ${String(t.template_key)}` : `id: ${t.id}`}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 ml-4">
                    {canLaunch && (
                      <button
                        onClick={() => navigate(`/ads/create?template_id=${encodeURIComponent(t.id)}`)}
                        className="flex items-center gap-1.5 px-3 py-2 text-xs text-white bg-pink-500 rounded-lg hover:bg-pink-600 transition font-medium"
                        title="使用此模板创建 TikTok 广告"
                      >
                        <Send className="w-3.5 h-3.5" /> 用此模板新建广告
                      </button>
                    )}
                    <button
                      onClick={() => isMetaW2aConv(t) ? openView(t) : setSystemPreview(t)}
                      className="flex items-center gap-1.5 px-3 py-2 text-xs text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition"
                    >
                      <Eye className="w-3.5 h-3.5" /> 查看
                    </button>
                    <button
                      onClick={() => openCloneDialog(t.id, t.name)}
                      className="flex items-center gap-1.5 px-3 py-2 text-xs text-white bg-blue-500 rounded-lg hover:bg-blue-600 transition font-medium"
                    >
                      <Copy className="w-3.5 h-3.5" /> 另存为
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </SectionCard>
      )}

      {isLoading && (
        <div className="flex items-center justify-center py-32 text-gray-400">
          <Loader2 className="w-6 h-6 animate-spin mr-2" /><span className="text-sm">加载中...</span>
        </div>
      )}
      {isError && (
        <div className="flex flex-col items-center justify-center py-24 text-red-400">
          <AlertCircle className="w-8 h-8 mb-2" /><p className="text-sm font-medium">数据加载失败</p>
        </div>
      )}

      {!isLoading && !isError && (
        <>
          {/* 业务模板列表 */}
          <SectionCard title={`我的业务模板（${businessTpls.length}）`} className="mb-5">
            {businessTpls.length === 0 ? (
              <div className="flex flex-col items-center py-12 text-gray-400">
                <Copy className="w-8 h-8 mb-3 opacity-50" />
                <p className="text-sm">暂无业务模板</p>
                <p className="text-xs mt-1">点击上方系统母版的「另存为」创建第一个业务模板</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100">
                {businessTpls.map(t => {
                  const adset = (t.adset ?? {}) as Record<string, unknown>
                  const targeting = (adset.targeting ?? {}) as Record<string, unknown>
                  const geo = (targeting.geo_locations ?? {}) as Record<string, unknown>
                  const countries = Array.isArray(geo.countries) ? geo.countries as string[] : []
                  const st = String(t.status ?? 'active')
                  return (
                    <div key={t.id} className="flex items-center justify-between py-3 first:pt-0 last:pb-0">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-gray-800 truncate">{t.name}</p>
                          <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${st === 'active' ? 'bg-green-50 text-green-600' : 'bg-gray-100 text-gray-400'}`}>
                            {st === 'active' ? '启用' : '停用'}
                          </span>
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {countries.length > 0 ? `${countries.slice(0, 5).join(', ')}${countries.length > 5 ? ` +${countries.length - 5}` : ''}` : '-'}
                          {' · '}
                          ${Number(adset.daily_budget ?? 5000) / 100}/天
                          {t.updated_at ? ` · 更新于 ${String(t.updated_at).slice(0, 10)}` : ''}
                        </p>
                      </div>
                      <div className="flex items-center gap-1.5 ml-4">
                        <button onClick={() => openEdit(t)} className="p-1.5 text-gray-400 hover:text-blue-500 transition" title="编辑">
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button onClick={() => openCloneDialog(t.id, t.name)} className="p-1.5 text-gray-400 hover:text-blue-500 transition" title="复制">
                          <Copy className="w-3.5 h-3.5" />
                        </button>
                        <button onClick={() => handleToggleStatus(t)} className="p-1.5 text-gray-400 hover:text-amber-500 transition" title={st === 'active' ? '停用' : '启用'}>
                          {st === 'active' ? <ToggleRight className="w-3.5 h-3.5" /> : <ToggleLeft className="w-3.5 h-3.5" />}
                        </button>
                        <button onClick={() => handleDelete(t.id)} className="p-1.5 text-gray-400 hover:text-red-500 transition" title="删除">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </SectionCard>
        </>
      )}

      {/* 另存为弹窗 */}
      {cloneOpen && <CloneDialog
        name={cloneName} setName={setCloneName}
        notes={cloneNotes} setNotes={setCloneNotes}
        onSubmit={handleClone} onClose={() => setCloneOpen(false)}
        isPending={cloneMutation.isPending} success={cloneSuccess}
      />}

      {/* 系统母版只读预览弹窗（非 Meta-W2A 母版用此） */}
      {systemPreview && <SystemTemplatePreviewDialog
        tpl={systemPreview}
        onClose={() => setSystemPreview(null)}
        onClone={() => {
          openCloneDialog(systemPreview.id, systemPreview.name)
          setSystemPreview(null)
        }}
        onLaunch={isTikTokMinisBasic(systemPreview) ? () => {
          navigate(`/ads/create?template_id=${encodeURIComponent(systemPreview.id)}`)
        } : undefined}
      />}
    </div>
  )
}

/* ═══════════════════════════════════════════════════
   系统母版只读预览弹窗
   ═══════════════════════════════════════════════════ */
interface SystemTemplatePreviewDialogProps {
  tpl: Template
  onClose: () => void
  onClone: () => void
  onLaunch?: () => void
}

function SystemTemplatePreviewDialog({ tpl, onClose, onClone, onLaunch }: SystemTemplatePreviewDialogProps) {
  // 排除行级字段，只展示模板内容
  const reserved = new Set([
    'id', 'name', 'platform', 'is_builtin', 'is_system', 'is_editable',
    'template_key', 'parent_template_id', 'created_at', 'updated_at',
  ])
  const content: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(tpl)) {
    if (!reserved.has(k)) content[k] = v
  }
  const previewDl = normalizeTemplateDeliveryLanguages({
    delivery_languages: tpl.delivery_languages,
    default_delivery_language: tpl.default_delivery_language,
  })
  // 友好预览：投放地区与默认 identity（仅 TikTok Minis 模板有意义）
  const defaults = (tpl.defaults as Record<string, unknown> | undefined) ?? {}
  const selection = defaults.location_selection as { country_codes?: string[]; group_key?: string | null } | undefined
  const locationIds = Array.isArray(defaults.location_ids) ? (defaults.location_ids as unknown[]).map(String) : []
  const locationCountryCodes = selection?.country_codes && selection.country_codes.length > 0
    ? selection.country_codes
    : locationIdsToCodesPreview(locationIds)
  const locationGroupKey = selection?.group_key
  const defaultIdentityId = (defaults.identity_id as string | undefined) || ''
  const showLocationPreview = locationIds.length > 0 || locationCountryCodes.length > 0
  const showIdentityPreview = !!defaultIdentityId
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-gray-800">{tpl.name}</h3>
              <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-600 border border-amber-200">系统母版</span>
            </div>
            <p className="text-xs text-gray-400 mt-1">
              platform: {tpl.platform}
              {tpl.template_type ? ` · type: ${String(tpl.template_type)}` : ''}
              {tpl.template_key ? ` · key: ${String(tpl.template_key)}` : ''}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
        </div>
        <div className="flex items-start gap-3 mx-6 mt-4 p-3 bg-amber-50 border border-amber-200 rounded-xl">
          <Shield className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-700">
            系统母版为只读模板，不支持直接编辑或删除。如需修改，请「另存为」生成业务模板副本。
          </p>
        </div>
        <div className="flex-1 overflow-auto px-6 py-4 space-y-4">
          {(showLocationPreview || showIdentityPreview) && (
            <div className="grid grid-cols-2 gap-3">
              {showLocationPreview && (
                <div className="p-3 border border-gray-200 rounded-xl bg-white">
                  <div className="text-[11px] text-gray-400 mb-1.5">默认投放地区</div>
                  <div className="flex flex-wrap gap-1">
                    {locationCountryCodes.length > 0
                      ? locationCountryCodes.map(c => (
                        <span key={c} className="inline-block px-2 py-0.5 rounded-md bg-blue-50 text-blue-600 text-xs font-medium">{c}</span>
                      ))
                      : <span className="text-xs text-gray-400">无可识别国家代码</span>}
                    {locationGroupKey && (
                      <span className="inline-block px-2 py-0.5 rounded-md bg-pink-50 text-pink-500 text-[11px]">group: {locationGroupKey}</span>
                    )}
                  </div>
                  <div className="mt-1.5 text-[11px] font-mono text-gray-400 break-all">
                    location_ids = [{locationIds.map(id => `"${id}"`).join(', ')}]
                  </div>
                </div>
              )}
              {showIdentityPreview && (
                <div className="p-3 border border-gray-200 rounded-xl bg-white">
                  <div className="text-[11px] text-gray-400 mb-1.5">默认 Identity</div>
                  <div className="text-xs font-mono text-gray-700 break-all">{defaultIdentityId}</div>
                </div>
              )}
            </div>
          )}
          <div className="p-3 border border-gray-200 rounded-xl bg-white">
            <div className="text-[11px] text-gray-400 mb-1.5">投放语种（强制启用平台语言定向）</div>
            <div className="flex flex-wrap gap-1.5">
              {previewDl.delivery_languages.map(code => (
                <span
                  key={code}
                  className={`inline-block px-2 py-0.5 rounded-md text-xs font-medium ${
                    code === previewDl.default_delivery_language
                      ? 'bg-blue-100 text-blue-700 border border-blue-200'
                      : 'bg-blue-50 text-blue-600'
                  }`}
                  title={code === previewDl.default_delivery_language ? '默认语种' : undefined}
                >
                  {deliveryLanguageLabel(code)}
                  {code === previewDl.default_delivery_language ? ' · 默认' : ''}
                </span>
              ))}
            </div>
          </div>
          <pre className="text-xs bg-gray-50 border border-gray-200 rounded-xl p-4 overflow-auto whitespace-pre-wrap break-all text-gray-700">
            {JSON.stringify(content, null, 2)}
          </pre>
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-gray-100 bg-gray-50/50 rounded-b-2xl">
          {onLaunch && (
            <button onClick={onLaunch} className="px-4 py-2 text-sm text-white bg-pink-500 rounded-xl hover:bg-pink-600 transition font-medium flex items-center gap-1.5">
              <Send className="w-4 h-4" /> 用此模板新建广告
            </button>
          )}
          <button onClick={onClone} className="px-4 py-2 text-sm text-white bg-blue-500 rounded-xl hover:bg-blue-600 transition font-medium flex items-center gap-1.5">
            <Copy className="w-4 h-4" /> 另存为业务模板
          </button>
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-xl hover:bg-gray-200 transition">关闭</button>
        </div>
      </div>
    </div>
  )
}

/* ═══════════════════════════════════════════════════
   另存为弹窗组件
   ═══════════════════════════════════════════════════ */
interface CloneDialogProps {
  name: string; setName: (v: string) => void
  notes: string; setNotes: (v: string) => void
  onSubmit: () => void; onClose: () => void
  isPending: boolean; success: string
}

function CloneDialog({ name, setName, notes, setNotes, onSubmit, onClose, isPending, success }: CloneDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-800">另存为业务模板</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
        </div>

        {success ? (
          <div className="flex items-center gap-2 py-8 justify-center text-green-600">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
            <span className="text-sm font-medium">{success}</span>
          </div>
        ) : (
          <>
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">新模板名称 <span className="text-red-400">*</span></label>
                <input value={name} onChange={e => setName(e.target.value)} placeholder="例：US-Conv-新剧推广" className={inputCls} autoFocus />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">备注（可选）</label>
                <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={2} placeholder="记录此模板的用途" className={inputCls} />
              </div>
            </div>
            <div className="flex items-center gap-2 mt-5">
              <button onClick={onSubmit} disabled={isPending || !name.trim()}
                className="flex-1 px-4 py-2.5 bg-blue-500 text-white text-sm rounded-xl hover:bg-blue-600 disabled:opacity-50 transition font-medium">
                {isPending ? '创建中...' : '创建副本'}
              </button>
              <button onClick={onClose} className="px-4 py-2.5 bg-gray-100 text-gray-600 text-sm rounded-xl hover:bg-gray-200 transition">取消</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/* ═══════════════════════════════════════════════════
   投放语种编辑器（在模板编辑/查看视图复用）
   ═══════════════════════════════════════════════════ */
interface DeliveryLanguageEditorProps {
  readonly: boolean
  languages: string[]
  defaultLanguage: string
  onChange: (languages: string[], defaultLanguage: string) => void
}

function DeliveryLanguageEditor({ readonly, languages, defaultLanguage, onChange }: DeliveryLanguageEditorProps) {
  const safeLangs = languages.length > 0 ? languages : [...DEFAULT_DELIVERY_LANGUAGES]
  const safeDefault = safeLangs.includes(defaultLanguage) ? defaultLanguage : (safeLangs[0] || DEFAULT_DELIVERY_LANGUAGE)

  function toggle(code: string) {
    const has = safeLangs.includes(code)
    let next: string[]
    if (has) {
      // 至少保留 1 项
      if (safeLangs.length <= 1) return
      next = safeLangs.filter(c => c !== code)
    } else {
      next = [...safeLangs, code]
    }
    const nextDefault = next.includes(safeDefault) ? safeDefault : next[0]
    onChange(next, nextDefault)
  }
  function changeDefault(code: string) {
    if (!safeLangs.includes(code)) return
    onChange(safeLangs, code)
  }

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <label className="block text-xs font-medium text-gray-600">
          投放语种 <span className="text-red-400">*</span>
        </label>
        <span className="text-[11px] text-gray-400">至少 1 项 · 默认语种必须在勾选范围内</span>
      </div>
      <p className="text-[11px] text-gray-400 mb-2">
        创建广告时可在允许范围内选择本次投放语种，平台将强制按所选语种定向人群。
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 p-2 border border-gray-200 rounded-xl bg-gray-50/40">
        {DELIVERY_LANGUAGE_OPTIONS.map(opt => {
          const checked = safeLangs.includes(opt.code)
          const isDefault = checked && opt.code === safeDefault
          return (
            <label
              key={opt.code}
              className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-xs cursor-pointer select-none transition ${
                checked ? 'bg-white border border-blue-200' : 'bg-transparent border border-transparent hover:border-gray-200'
              } ${readonly ? 'cursor-default' : ''}`}
            >
              <input
                type="checkbox"
                checked={checked}
                disabled={readonly}
                onChange={() => toggle(opt.code)}
                className="accent-blue-500"
              />
              <span className={`${checked ? 'text-gray-700' : 'text-gray-500'} truncate`}>{opt.label}</span>
              {isDefault && (
                <span className="ml-auto inline-block px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 text-[10px]">默认</span>
              )}
            </label>
          )
        })}
      </div>
      <div className="mt-2 flex items-center gap-2">
        <label className="text-xs text-gray-600 shrink-0">默认语种</label>
        <select
          value={safeDefault}
          disabled={readonly}
          onChange={e => changeDefault(e.target.value)}
          className={`${inputCls} bg-white max-w-xs ${readonly ? '!bg-gray-50 text-gray-500' : ''}`}
        >
          {safeLangs.map(code => (
            <option key={code} value={code}>{deliveryLanguageLabel(code)}</option>
          ))}
        </select>
      </div>
    </div>
  )
}
