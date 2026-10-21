import { useLaunchDraft } from '@/components/ads-create/useLaunchDraft'
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { CountryMultiSelect } from '@/components/common/CountryMultiSelect'
import {
  Send, Loader2, CheckCircle, AlertCircle,
  Image, Film, Trash2, Plus, Copy, ChevronDown, ChevronUp, Shield,
  Package,
} from 'lucide-react'
import {
  LandingPagePickerDialog,
  CopyPackPickerDialog,
  RegionGroupPickerDialog,
} from '@/components/common/AssetPickerDialog'
import type { LandingPageAsset, CopyPackAsset, RegionGroupAsset } from '@/services/ad-assets'
import { useTemplates } from '@/hooks/use-templates'
import {
  createAds,
  fileNameToAdName,
  type CreateResult,
  type W2aFields,
  type MaterialItem,
  type AdSetConfig,
  type BatchLaunchResult,
} from '@/services/ads-create'
import { fetchMetaAccounts, type MetaAccount } from '@/services/advertisers'
import {
  fetchMetaPages, fetchMetaPixels,
  uploadMetaImage, uploadMetaVideo,
  validateImageFile, validateVideoFile,
  type MetaPageOption, type MetaPixelOption,
  type MetaAccountAsset,
} from '@/services/meta-assets'
import { getVideoDuration } from '@/services/tiktok-materials'
import { MetaAccountAssetPicker } from '@/components/common/MetaAccountAssetPicker'
import TikTokMinisCreateForm, {
  isTikTokMinisBasicTpl,
  useMinisTemplates,
} from '@/components/ads-create/TikTokMinisCreateForm'
import TikTokWebToAppCreateForm, {
  isTikTokWebToAppTpl,
  useW2aTemplates,
} from '@/components/ads-create/TikTokWebToAppCreateForm'
import DeliveryLanguageSelect from '@/components/ads-create/DeliveryLanguageSelect'
import { DEFAULT_DELIVERY_LANGUAGE } from '@/constants/deliveryLanguages'

const MAX_MATERIALS = 20
const MAX_ADSETS = 20

const CTA_OPTIONS = [
  'LEARN_MORE', 'SHOP_NOW', 'INSTALL_NOW', 'SIGN_UP',
  'WATCH_MORE', 'DOWNLOAD', 'GET_OFFER', 'ORDER_NOW',
] as const

const EVENT_TYPE_OPTIONS = [
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

const inputCls = 'w-full px-4 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition'

function emptyW2a(): W2aFields {
  return {
    pageId: '', landingPageUrl: '', primaryText: '', headline: '',
    description: '', callToAction: 'LEARN_MORE',
    pixelId: '', customEventType: '',
  }
}

// ─── 素材上传状态 ──
interface UploadingMaterial {
  id: string
  /** 账户素材没有本地 File；用 ?: 兼容 */
  file?: File
  type: 'image' | 'video'
  original_name: string
  ad_name: string
  status: 'uploading' | 'success' | 'error'
  progress: number
  image_hash?: string
  video_id?: string
  picture_url?: string
  error?: string
  abort?: () => void
  thumbnail_uploading?: boolean
  thumbnail_error?: string
  duration_sec?: number
  /** 素材来源：本地批量上传 / 账户素材；未标记则视为本地（向后兼容） */
  source?: 'local_upload' | 'account_asset'
  /** 账户素材的 Meta 资产 ID（image_hash 或 video_id） */
  meta_asset_id?: string
}

const LONG_VIDEO_THRESHOLD = 600 // 10 min

// ─── AdSet 本地状态 ──
interface AdSetLocal {
  key: string
  name: string
  daily_budget: string
  countries: string[]
  pixel_id: string
  custom_event_type: string
  material_ids: string[]
  collapsed: boolean
}

let _matIdCounter = 0
function nextMatId() { return `mat_${Date.now()}_${++_matIdCounter}` }
let _adsetKeyCounter = 0
function nextAdSetKey() { return `as_${Date.now()}_${++_adsetKeyCounter}` }

export default function AdsCreatePage() {
  const { launch, dialog } = useLaunchDraft()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { data: allTemplates } = useTemplates()
  const { data: metaAccountsResp } = useQuery({ queryKey: ['meta-accounts'], queryFn: fetchMetaAccounts })
  const metaAccounts: MetaAccount[] = metaAccountsResp?.data ?? []

  const MASTER_TPL_ID = 'tpl_meta_web_to_app_conv_abo'
  const CBO_TPL_ID = 'tpl_meta_web_to_app_conv_cbo'
  // Meta W2A Conversion 系列模板（既有 ABO + 新增 CBO；其余 Meta 模板维持现状）
  const metaTemplates = useMemo(() => {
    if (!allTemplates) return []
    return allTemplates.filter(t => {
      if (t.platform !== 'meta') return false
      // ABO（既有）：template_type === 'web_to_app' 且 subtype === 'conversion' 或为 MASTER_TPL_ID
      if (t.template_type === 'web_to_app'
        && (t.template_subtype === 'conversion' || t.id === MASTER_TPL_ID)) return true
      // CBO（新增）：template_type === 'web_to_app_conversion_cbo'
      if (t.template_type === 'web_to_app_conversion_cbo' || t.id === CBO_TPL_ID) return true
      return false
    })
  }, [allTemplates])
  // TikTok Minis 系列模板（系统母版 + 业务模板）
  const minisTemplates = useMinisTemplates(allTemplates)
  // TikTok Web to App 系列模板（系统母版 + 业务模板）
  const tiktokW2aTemplates = useW2aTemplates(allTemplates)

  // 统一模板池：本页的"投放模板"下拉同时容纳 Meta W2A / TikTok Minis / TikTok W2A
  const templates = useMemo(
    () => [...metaTemplates, ...minisTemplates, ...tiktokW2aTemplates],
    [metaTemplates, minisTemplates, tiktokW2aTemplates],
  )

  // 与「模板管理」页一致：所有 is_system === true（或老数据兜底：is_builtin / 内置 Meta 母版 ID）归为「系统母版」
  // 其余统一进入「我的业务模板」（Meta W2A 副本 + TikTok Minis 自定义副本混合）
  const isSystemTplOption = useCallback(
    (t: { id: string; is_system?: boolean; is_builtin?: boolean }) =>
      Boolean(t.is_system) || t.id === MASTER_TPL_ID || Boolean(t.is_builtin),
    [],
  )
  const systemTpls = useMemo(
    () => templates.filter(isSystemTplOption),
    [templates, isSystemTplOption],
  )
  const businessTpls = useMemo(
    () => templates.filter(t => !isSystemTplOption(t)),
    [templates, isSystemTplOption],
  )
  const platformPrefix = (p?: string) =>
    p === 'tiktok' ? '[TikTok]' : p === 'meta' ? '[Meta]' : ''

  // ── 模板 & 全局配置 ──
  const [selectedTpl, setSelectedTpl] = useState('')
  const [campaignName, setCampaignName] = useState('')
  const [adAccountId, setAdAccountId] = useState('')
  const budgetCurrency = metaAccounts.find(a => a.id === adAccountId)?.currency || ''
  const [w2a, setW2a] = useState<W2aFields>(emptyW2a)

  // ── 素材池 ──
  const [materials, setMaterials] = useState<UploadingMaterial[]>([])

  // ── AdSet 列表 ──
  const [adSets, setAdSets] = useState<AdSetLocal[]>([])

  // ── 提交状态 ──
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<CreateResult | null>(null)

  // ── Page / Pixel 联动 ──
  const [pages, setPages] = useState<MetaPageOption[]>([])
  const [pagesLoading, setPagesLoading] = useState(false)
  const [pagesError, setPagesError] = useState('')
  const [pageManual, setPageManual] = useState(false)
  const [pixels, setPixels] = useState<MetaPixelOption[]>([])
  const [pixelsLoading, setPixelsLoading] = useState(false)
  const [pixelsError, setPixelsError] = useState('')
  const [pixelManual, setPixelManual] = useState(false)

  // ── Meta 账户素材选择器 ──
  const [showAccountAssetPicker, setShowAccountAssetPicker] = useState(false)

  // ── Meta 投放时间（仅 Conversion ABO/CBO 优化项；不影响 TikTok / Mini） ──
  // datetime-local 控件值（无时区，格式 yyyy-MM-ddTHH:mm）；提交时与浏览器时区合成 ISO 8601 with offset
  const [scheduleStartLocal, setScheduleStartLocal] = useState('')
  const [scheduleEndLocal, setScheduleEndLocal] = useState('')

  // ── Meta CBO：Campaign 层日预算（账户币种主单位，未乘 100）。仅 web_to_app_conversion_cbo 模板使用 ──
  const [campaignDailyBudget, setCampaignDailyBudget] = useState<string>('')

  // ── 投放语种（受 currentTpl.delivery_languages 限制；切换模板由 DeliveryLanguageSelect 内部回落） ──
  const [selectedDeliveryLanguage, setSelectedDeliveryLanguage] = useState<string>(DEFAULT_DELIVERY_LANGUAGE)

  // ── 资产库弹窗 & 引用追踪 ──
  const [showLPPicker, setShowLPPicker] = useState(false)
  const [showCopyPicker, setShowCopyPicker] = useState(false)
  const [showRegionPicker, setShowRegionPicker] = useState<string | null>(null)

  const [lpRef, setLpRef] = useState<{ id: number; name: string; snapshot: string } | null>(null)
  const [copyRef, setCopyRef] = useState<{ id: number; name: string; primaryTextSnapshot: string; headlineSnapshot: string; descriptionSnapshot: string } | null>(null)
  const [regionRefs, setRegionRefs] = useState<Record<string, { id: number; name: string; snapshot: string[] }>>({})

  const fileInputRef = useRef<HTMLInputElement>(null)

  const currentTpl = (templates ?? []).find(t => t.id === selectedTpl)
  const tplPlatform = currentTpl?.platform
  const isMeta = tplPlatform === 'meta'
  // CBO 与 ABO 共享 W2A 表单（创意/落地页/Pixel/Event/投放时间），仅预算层级不同
  const isW2aCbo = isMeta && (currentTpl?.template_type === 'web_to_app_conversion_cbo'
    || currentTpl?.id === CBO_TPL_ID)
  const isW2a = isMeta && (currentTpl?.template_type === 'web_to_app' || isW2aCbo)
  const isW2aConversion = isW2a && (currentTpl?.template_subtype === 'conversion'
    || currentTpl?.template_subtype === 'conversion_cbo'
    || currentTpl?.id === 'tpl_meta_web_to_app_conv_abo'
    || isW2aCbo)
  const isMinis = isTikTokMinisBasicTpl(currentTpl)
  const isTikTokW2a = isTikTokWebToAppTpl(currentTpl)
  // 只要是"TikTok 单表单"模板（minis 或 W2A），就走独立子表单分支，跳过 Meta 批量创建 UI
  const isTikTokSingleForm = isMinis || isTikTokW2a

  // ── URL ?template_id=xxx 同步 ──
  // 进入页面时（或外部跳转）若 URL 带 template_id，且模板池已加载，则自动选中
  useEffect(() => {
    const urlTplId = searchParams.get('template_id')
    if (!urlTplId) return
    if (selectedTpl === urlTplId) return
    if (templates.find(t => t.id === urlTplId)) {
      setSelectedTpl(urlTplId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templates.length, searchParams])
  // 切换到非 CBO 模板时清空 CBO 预算字段，避免下一次提交携带过期值
  useEffect(() => {
    if (!isW2aCbo && campaignDailyBudget) setCampaignDailyBudget('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isW2aCbo])
  // 用户在页面内手动改模板时，把 URL 同步上去（便于刷新/分享）
  useEffect(() => {
    if (!selectedTpl) return
    if (searchParams.get('template_id') === selectedTpl) return
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('template_id', selectedTpl)
      return next
    }, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTpl])

  const readyMaterials = useMemo(() =>
    materials.filter(m => m.status === 'success'),
    [materials],
  )

  // ── 初始化默认 adset ──
  function createDefaultAdSet(cName: string, countries: string[], budget: string, pixelId: string, eventType: string): AdSetLocal {
    return {
      key: nextAdSetKey(),
      name: cName || 'AdSet_01',
      daily_budget: budget || '50',
      countries: countries.length > 0 ? countries : ['US'],
      pixel_id: pixelId,
      custom_event_type: eventType,
      material_ids: [],
      collapsed: false,
    }
  }

  // ── Page/Pixel 联动 ──
  useEffect(() => {
    if (!adAccountId || !isW2a) { setPages([]); setPixels([]); return }
    setPagesLoading(true); setPagesError('')
    fetchMetaPages(adAccountId)
      .then(r => { setPages(r.data ?? []); if (r.error) setPagesError(r.error) })
      .catch(e => setPagesError(String(e)))
      .finally(() => setPagesLoading(false))
    setPixelsLoading(true); setPixelsError('')
    fetchMetaPixels(adAccountId)
      .then(r => { setPixels(r.data ?? []); if (r.error) setPixelsError(r.error) })
      .catch(e => setPixelsError(String(e)))
      .finally(() => setPixelsLoading(false))
  }, [adAccountId, isW2a])

  // ── 模板选择后预填（仅对 Meta 模板生效；minis 模板由 TikTokMinisCreateForm 自管）──
  useEffect(() => {
    if (!selectedTpl || !templates) return
    const tpl = templates.find(t => t.id === selectedTpl)
    if (!tpl) return
    if (isTikTokMinisBasicTpl(tpl) || isTikTokWebToAppTpl(tpl)) {
      // 选中 TikTok 单表单模板时，重置 Meta 批量创建的临时状态，避免上次残留
      setMaterials([])
      setAdSets([])
      setResult(null)
      return
    }

    setCampaignName(`${tpl.name}_${new Date().toISOString().slice(5, 10)}`)

    const tplAdset = (tpl as Record<string, unknown>).adset as Record<string, unknown> | undefined
    const tplCountries = (tplAdset?.targeting as Record<string, unknown>)?.geo_locations as Record<string, unknown> | undefined
    const countries = (tplCountries?.countries as string[]) ?? ['US']
    const tplBudget = tplAdset?.daily_budget as number | undefined
    const budgetStr = tplBudget ? String(tplBudget / 100) : '50'

    let pixelId = ''
    let eventType = ''

    if (tpl.template_type === 'web_to_app') {
      const c = (tpl.creative ?? {}) as Record<string, string>
      const po = (tplAdset?.promoted_object ?? {}) as Record<string, string>
      pixelId = po.pixel_id || ''
      eventType = po.custom_event_type || ''
      setW2a(prev => ({
        ...prev,
        primaryText: c.primary_text || prev.primaryText,
        headline: c.headline || prev.headline,
        callToAction: c.call_to_action || 'LEARN_MORE',
        pageId: c.page_id || '',
        landingPageUrl: c.link || '',
        pixelId,
        customEventType: eventType,
      }))
    } else {
      setW2a(emptyW2a())
    }

    const tplAdAccount = tpl.default_ad_account_id as string | undefined
    if (tplAdAccount) setAdAccountId(tplAdAccount)

    const newName = `${tpl.name}_${new Date().toISOString().slice(5, 10)}`
    setAdSets([createDefaultAdSet(newName, countries, budgetStr, pixelId, eventType)])
    setMaterials([])
    setResult(null)
  }, [selectedTpl, templates])

  // ── 素材批量上传 ──
  const handleFileSelect = useCallback(async (fileList: FileList) => {
    if (!adAccountId) return
    const files = Array.from(fileList)
    const currentCount = materials.length
    const remaining = MAX_MATERIALS - currentCount
    if (remaining <= 0) {
      alert(`素材池已满（最多 ${MAX_MATERIALS} 个）`)
      return
    }
    const toUpload = files.slice(0, remaining)
    if (toUpload.length < files.length) {
      alert(`只能再上传 ${remaining} 个素材，已自动截取前 ${remaining} 个`)
    }

    const newItems: UploadingMaterial[] = toUpload.map(f => {
      const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
      const isVideo = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v'].includes(ext)
      return {
        id: nextMatId(),
        file: f,
        type: isVideo ? 'video' : 'image',
        original_name: f.name,
        ad_name: fileNameToAdName(f.name),
        status: 'uploading' as const,
        progress: 0,
        source: 'local_upload',
      }
    })

    setMaterials(prev => [...prev, ...newItems])

    for (const item of newItems) {
      const file = item.file as File
      if (item.type === 'image') {
        const err = validateImageFile(file)
        if (err) {
          setMaterials(prev => prev.map(m => m.id === item.id ? { ...m, status: 'error', error: err } : m))
          continue
        }
        const r = await uploadMetaImage(adAccountId, file)
        setMaterials(prev => prev.map(m => m.id === item.id
          ? r.success && r.image_hash
            ? { ...m, status: 'success', image_hash: r.image_hash, progress: 100 }
            : { ...m, status: 'error', error: r.error || '上传失败' }
          : m))
      } else {
        const err = validateVideoFile(file)
        if (err) {
          setMaterials(prev => prev.map(m => m.id === item.id ? { ...m, status: 'error', error: err } : m))
          continue
        }
        try {
          const dur = await getVideoDuration(file)
          setMaterials(prev => prev.map(m => m.id === item.id ? { ...m, duration_sec: dur } : m))
        } catch { /* duration detection optional */ }
        const { promise, abort } = uploadMetaVideo(adAccountId, file, pct => {
          setMaterials(prev => prev.map(m => m.id === item.id ? { ...m, progress: pct } : m))
        })
        setMaterials(prev => prev.map(m => m.id === item.id ? { ...m, abort } : m))
        const r = await promise
        setMaterials(prev => prev.map(m => m.id === item.id
          ? r.success && r.video_id
            ? { ...m, status: 'success', video_id: r.video_id, picture_url: r.picture_url || undefined, progress: 100, abort: undefined }
            : { ...m, status: 'error', error: r.error || '上传失败', abort: undefined }
          : m))
      }
    }
  }, [adAccountId, materials.length])

  const removeMaterial = useCallback((matId: string) => {
    const mat = materials.find(m => m.id === matId)
    if (mat?.abort) mat.abort()
    setMaterials(prev => prev.filter(m => m.id !== matId))
    setAdSets(prev => prev.map(a => ({
      ...a,
      material_ids: a.material_ids.filter(id => id !== matId),
    })))
  }, [materials])

  const uploadThumbnail = useCallback(async (matId: string, file: File) => {
    if (!adAccountId) return
    const err = validateImageFile(file)
    if (err) {
      setMaterials(prev => prev.map(m => m.id === matId ? { ...m, thumbnail_error: err } : m))
      return
    }
    setMaterials(prev => prev.map(m => m.id === matId ? { ...m, thumbnail_uploading: true, thumbnail_error: undefined } : m))
    const r = await uploadMetaImage(adAccountId, file)
    if (r.success && r.image_hash) {
      setMaterials(prev => prev.map(m => m.id === matId ? { ...m, image_hash: r.image_hash, thumbnail_uploading: false } : m))
    } else {
      setMaterials(prev => prev.map(m => m.id === matId ? { ...m, thumbnail_uploading: false, thumbnail_error: r.error || '封面上传失败' } : m))
    }
  }, [adAccountId])

  // ── AdSet 操作 ──
  const addAdSet = useCallback(() => {
    if (adSets.length >= MAX_ADSETS) return
    const idx = adSets.length + 1
    setAdSets(prev => [...prev, {
      key: nextAdSetKey(),
      name: `${campaignName}_${String(idx).padStart(2, '0')}`,
      daily_budget: prev[0]?.daily_budget || '50',
      countries: prev[0]?.countries ?? ['US'],
      pixel_id: w2a.pixelId,
      custom_event_type: w2a.customEventType,
      material_ids: [],
      collapsed: false,
    }])
  }, [adSets, campaignName, w2a.pixelId, w2a.customEventType])

  const removeAdSet = useCallback((key: string) => {
    if (adSets.length <= 1) return
    setAdSets(prev => prev.filter(a => a.key !== key))
  }, [adSets.length])

  const duplicateAdSet = useCallback((key: string) => {
    if (adSets.length >= MAX_ADSETS) return
    const src = adSets.find(a => a.key === key)
    if (!src) return
    setAdSets(prev => [...prev, { ...src, key: nextAdSetKey(), name: `${src.name}_copy` }])
  }, [adSets])

  const updateAdSet = useCallback((key: string, patch: Partial<AdSetLocal>) => {
    setAdSets(prev => prev.map(a => a.key === key ? { ...a, ...patch } : a))
  }, [])

  const toggleMaterial = useCallback((adSetKey: string, matId: string) => {
    setAdSets(prev => prev.map(a => {
      if (a.key !== adSetKey) return a
      const has = a.material_ids.includes(matId)
      return { ...a, material_ids: has ? a.material_ids.filter(id => id !== matId) : [...a.material_ids, matId] }
    }))
  }, [])

  const selectAllMaterials = useCallback((adSetKey: string) => {
    const allIds = readyMaterials.map(m => m.id)
    setAdSets(prev => prev.map(a => a.key === adSetKey ? { ...a, material_ids: allIds } : a))
  }, [readyMaterials])

  const clearMaterials = useCallback((adSetKey: string) => {
    setAdSets(prev => prev.map(a => a.key === adSetKey ? { ...a, material_ids: [] } : a))
  }, [])

  // ── 自动为只有 1 个 adset 时同步 campaign name ──
  useEffect(() => {
    if (adSets.length === 1) {
      setAdSets(prev => prev.map((a, i) => i === 0 ? { ...a, name: campaignName } : a))
    }
  }, [campaignName, adSets.length])

  // ── 切换 ad_account_id 时清空账户素材选择（避免跨账户素材误用），本地素材保留 ──
  const prevAdAccountRef = useRef(adAccountId)
  useEffect(() => {
    const prev = prevAdAccountRef.current
    if (prev && prev !== adAccountId) {
      const removedAccountIds = materials.filter(m => m.source === 'account_asset').map(m => m.id)
      if (removedAccountIds.length > 0) {
        setMaterials(prevList => prevList.filter(m => m.source !== 'account_asset'))
        setAdSets(prevList => prevList.map(a => ({
          ...a,
          material_ids: a.material_ids.filter(id => !removedAccountIds.includes(id)),
        })))
      }
    }
    prevAdAccountRef.current = adAccountId
  }, [adAccountId, materials])

  // ── 把账户素材 picker 的选择并入素材池（标记 source='account_asset'） ──
  const addAccountAssets = useCallback((assets: MetaAccountAsset[]) => {
    if (assets.length === 0) return
    const remaining = MAX_MATERIALS - materials.length
    if (remaining <= 0) {
      alert(`素材池已满（最多 ${MAX_MATERIALS} 个）`)
      return
    }
    const slice = assets.slice(0, remaining)
    if (slice.length < assets.length) {
      alert(`只能再添加 ${remaining} 个素材，已自动截取前 ${remaining} 个`)
    }
    const newItems: UploadingMaterial[] = slice.map(a => ({
      id: nextMatId(),
      type: a.type,
      original_name: a.name,
      ad_name: fileNameToAdName(a.name),
      status: 'success',
      progress: 100,
      image_hash: a.image_hash,
      video_id: a.video_id,
      picture_url: a.thumbnail_url || a.preview_url,
      duration_sec: a.duration_sec ? a.duration_sec / 1000 : undefined,
      source: 'account_asset',
      meta_asset_id: a.meta_asset_id,
    }))
    setMaterials(prev => [...prev, ...newItems])
  }, [materials.length])

  /** 已选账户素材 key（用于 picker 内 disable） */
  const accountAssetPickedKeys = useMemo(() => {
    const s = new Set<string>()
    for (const m of materials) {
      if (m.source !== 'account_asset') continue
      const id = m.meta_asset_id || m.video_id || m.image_hash || ''
      if (id) s.add(`${m.type}:${id}`)
    }
    return s
  }, [materials])

  // ── 投放时间工具（仅 Meta W2A Conversion ABO 使用） ──
  // datetime-local → ISO 8601 with timezone offset；浏览器本地时区
  function localToIso(local: string): string {
    if (!local) return ''
    const d = new Date(local)
    if (Number.isNaN(d.getTime())) return ''
    const tz = -d.getTimezoneOffset()
    const sign = tz >= 0 ? '+' : '-'
    const abs = Math.abs(tz)
    const hh = String(Math.floor(abs / 60)).padStart(2, '0')
    const mm = String(abs % 60).padStart(2, '0')
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${sign}${hh}${mm}`
  }
  const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

  // ── 校验 ──
  function validate(): string | null {
    if (!selectedTpl) return '请先选择模板'
    if (!campaignName.trim()) return '请输入广告系列名称'
    if (isMeta && !adAccountId) return '请选择 Meta 广告账户'
    if (isW2a) {
      if (!w2a.pageId.trim()) return '请选择或填写 Page ID'
      if (!w2a.landingPageUrl.trim()) return '请填写 Landing Page URL'
      if (!w2a.primaryText.trim()) return '请填写 Primary Text'
      if (!w2a.headline.trim()) return '请填写 Headline'
    }
    const videosWithoutCover = readyMaterials.filter(m => m.type === 'video' && !m.image_hash && !m.picture_url)
    if (videosWithoutCover.length > 0) {
      return `视频素材 "${videosWithoutCover[0].ad_name}" 缺少封面图，请上传封面或等待自动获取`
    }
    if (readyMaterials.length === 0) return '至少上传 1 个素材'
    if (adSets.length === 0) return '至少需要 1 个 AdSet'
    // CBO 模式：Campaign 层日预算必填；AdSet 不再校验日预算
    if (isW2aCbo) {
      const cbo = Number(campaignDailyBudget)
      if (!campaignDailyBudget || !Number.isFinite(cbo) || cbo <= 0 || Math.abs(cbo*100-Math.round(cbo*100)) > 0.000001) {
        return 'CBO 模板必须填写 Campaign Daily Budget（账户币种），且大于 0'
      }
    }
    for (let i = 0; i < adSets.length; i++) {
      const a = adSets[i]
      if (!a.name.trim()) return `AdSet #${i + 1} 名称不能为空`
      if (!isW2aCbo) {
        const amount = Number(a.daily_budget)
        if (!a.daily_budget || !Number.isFinite(amount) || amount <= 0 || Math.abs(amount*100-Math.round(amount*100)) > 0.000001) return `AdSet #${i + 1} 日预算必须大于 0，且最多保留两位小数`
      }
      if (a.countries.length === 0) return `AdSet #${i + 1} 至少选择一个国家`
      if (a.material_ids.length === 0) return `AdSet #${i + 1} 至少选择 1 个素材`
      if (isW2aConversion) {
        if (!a.pixel_id.trim()) return `AdSet #${i + 1} Pixel ID 必填`
        if (!a.custom_event_type.trim()) return `AdSet #${i + 1} Custom Event Type 必填`
      }
    }
    // 投放时间校验（仅 Meta W2A Conversion ABO；start_time 必填）
    if (isW2aConversion) {
      if (!scheduleStartLocal) return '请填写开始时间（投放时间 → 开始时间）'
      const sd = new Date(scheduleStartLocal)
      if (Number.isNaN(sd.getTime())) return '开始时间格式无效'
      if (sd.getTime() < Date.now() + 10 * 60 * 1000) {
        return '开始时间必须晚于当前时间至少 10 分钟（Meta API 要求）'
      }
      if (scheduleEndLocal) {
        const ed = new Date(scheduleEndLocal)
        if (Number.isNaN(ed.getTime())) return '结束时间格式无效'
        if (ed.getTime() <= sd.getTime()) return '结束时间必须晚于开始时间'
        // 使用 daily_budget 时，end-start 建议 > 24h
        const usingDailyBudget = adSets.some(a => Number(a.daily_budget) > 0)
        if (usingDailyBudget && (ed.getTime() - sd.getTime()) < 24 * 3600 * 1000) {
          return '使用日预算时，结束时间与开始时间间隔需大于 24 小时（Meta 限制）'
        }
      }
    }
    return null
  }

  const isUploading = materials.some(m => m.status === 'uploading' || m.thumbnail_uploading)
  const validationError = validate()
  const canSubmit = !submitting && !isUploading && !validationError

  const setField = (field: keyof W2aFields, value: string) => {
    setW2a(prev => ({ ...prev, [field]: value })); setResult(null)
  }

  // ── 提交 ──
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const err = validate()
    if (err) { setResult({ success: false, message: err }); return }

    const mats: MaterialItem[] = readyMaterials.map(m => ({
      id: m.id,
      type: m.type,
      image_hash: m.image_hash,
      video_id: m.video_id,
      picture_url: m.picture_url,
      original_name: m.original_name,
      ad_name: m.ad_name,
      source: m.source,
      meta_asset_id: m.meta_asset_id,
    }))

    const adsetConfigs: AdSetConfig[] = adSets.map(a => {
      const rRef = regionRefs[a.key]
      return {
        name: a.name,
        daily_budget: Math.round(Number(a.daily_budget) * 100),
        countries: a.countries,
        pixel_id: a.pixel_id || w2a.pixelId,
        custom_event_type: a.custom_event_type || w2a.customEventType,
        material_ids: a.material_ids,
        region_group_id: rRef?.id,
        region_group_name: rRef?.name,
        country_codes_snapshot: rRef?.snapshot,
      }
    })

    setSubmitting(true); setResult(null)
    const res = await createAds({
      launch,
      mode: 'template',
      platform: (tplPlatform as 'tiktok' | 'meta') || 'meta',
      campaignName: campaignName.trim(),
      country: adSets[0]?.countries[0] || 'US',
      countries: adSets[0]?.countries ?? ['US'],
      // CBO：用 Campaign 层日预算作为兜底 budget；ABO：取首个 AdSet 日预算
      budget: isW2aCbo
        ? (Number(campaignDailyBudget) || 50)
        : (Number(adSets[0]?.daily_budget) || 50),
      campaignDailyBudget: isW2aCbo ? Number(campaignDailyBudget) : undefined,
      templateId: selectedTpl,
      template: currentTpl ?? null,
      adAccountId: isMeta ? adAccountId : undefined,
      budgetCurrency,
      w2a: isW2a ? w2a : undefined,
      materials: mats,
      adsets: adsetConfigs,
      assetRefs: {
        landing_page_asset_id: lpRef?.id,
        landing_page_asset_name: lpRef?.name,
        landing_page_url_snapshot: lpRef?.snapshot,
        copy_asset_id: copyRef?.id,
        copy_asset_name: copyRef?.name,
        primary_text_snapshot: copyRef?.primaryTextSnapshot,
        headline_snapshot: copyRef?.headlineSnapshot,
        description_snapshot: copyRef?.descriptionSnapshot,
      },
      // Meta Web to App Conversion ABO 投放时间
      metaSchedule: isW2aConversion && scheduleStartLocal ? {
        start_time: localToIso(scheduleStartLocal),
        end_time: scheduleEndLocal ? localToIso(scheduleEndLocal) : undefined,
        timezone: browserTz,
      } : undefined,
      selectedDeliveryLanguage,
    })
    setSubmitting(false); setResult(res)
  }

  return (
    <div className="max-w-4xl mx-auto">
      {dialog}
      <PageHeader title="新建广告" description="基于模板快速创建广告投放计划"
        action={<button onClick={() => navigate('/ads')} className="text-sm text-gray-500 hover:text-gray-700 transition">返回广告数据</button>}
      />

      <form onSubmit={handleSubmit}>
        {/* ══ 选择模板 ══ */}
        <SectionCard title="选择模板" className="mb-6">
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">投放模板 <span className="text-red-400">*</span></label>
              <select value={selectedTpl} onChange={e => { setSelectedTpl(e.target.value); setResult(null) }} className={`${inputCls} bg-white`}>
                <option value="">请选择模板</option>
                {systemTpls.length > 0 && (
                  <optgroup label={`系统母版（${systemTpls.length}）`}>
                    {systemTpls.map(t => (
                      <option key={t.id} value={t.id}>{platformPrefix(t.platform)} {t.name}</option>
                    ))}
                  </optgroup>
                )}
                {businessTpls.length > 0 && (
                  <optgroup label={`我的业务模板（${businessTpls.length}）`}>
                    {businessTpls.map(t => (
                      <option key={t.id} value={t.id}>{platformPrefix(t.platform)} {t.name}</option>
                    ))}
                  </optgroup>
                )}
              </select>
            </div>
            {currentTpl && (
              <div className="flex items-center gap-2 text-xs text-gray-400">
                {tplPlatform === 'tiktok' ? (
                  <span className="inline-block px-2 py-0.5 rounded-full font-medium bg-pink-50 text-pink-600">TikTok</span>
                ) : (
                  <span className="inline-block px-2 py-0.5 rounded-full font-medium bg-indigo-50 text-indigo-600">Meta</span>
                )}
                {isMinis && (
                  <span className="inline-block px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">Minis Basic</span>
                )}
                {isTikTokW2a && (
                  <span className="inline-block px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">Web to App</span>
                )}
                {!isMinis && !isTikTokW2a && isMeta && !isW2aCbo && (
                  <span className="inline-block px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">W2A Conversion (ABO)</span>
                )}
                {isW2aCbo && (
                  <span className="inline-block px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-600 font-medium">W2A Conversion (CBO)</span>
                )}
                {(currentTpl.is_system || currentTpl.id === MASTER_TPL_ID || currentTpl.is_builtin) && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-50 text-amber-600 font-medium">
                    <Shield className="w-3 h-3" /> {currentTpl.is_system ? '系统母版' : '系统默认'}
                  </span>
                )}
              </div>
            )}
          </div>
        </SectionCard>

        {currentTpl && isMinis && (
          <TikTokMinisCreateForm tpl={currentTpl} />
        )}

        {currentTpl && isTikTokW2a && (
          <TikTokWebToAppCreateForm tpl={currentTpl} />
        )}

        {currentTpl && !isTikTokSingleForm && (
          <>
            {/* ══ 投放配置（全局） ══ */}
            <SectionCard title="投放配置" className="mb-6">
              <div className="space-y-5">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Campaign Name <span className="text-red-400">*</span></label>
                  <input type="text" value={campaignName} onChange={e => { setCampaignName(e.target.value); setResult(null) }}
                    placeholder="例如：US_iOS_Summer_Campaign" className={inputCls} />
                </div>
                <DeliveryLanguageSelect
                  value={selectedDeliveryLanguage}
                  onChange={(c) => { setSelectedDeliveryLanguage(c); setResult(null) }}
                  deliveryLanguages={currentTpl?.delivery_languages}
                  defaultDeliveryLanguage={currentTpl?.default_delivery_language}
                  templateId={currentTpl?.id ?? null}
                  inputClassName={inputCls}
                />
                {isMeta && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">Meta 广告账户 <span className="text-red-400">*</span></label>
                    <select value={adAccountId} onChange={e => { setAdAccountId(e.target.value); setResult(null) }} className={`${inputCls} bg-white`}>
                      <option value="">请选择 Meta 广告账户</option>
                      {metaAccounts.map(a => <option key={a.id} value={a.id}>{a.name} ({a.id})</option>)}
                    </select>
                  </div>
                )}
                {/* CBO：Campaign 层日预算（仅 web_to_app_conversion_cbo 模板显示） */}
                {isW2aCbo && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">
                      Campaign Daily Budget / 广告系列日预算 ({budgetCurrency || '请选择账户'}) <span className="text-red-400">*</span>
                    </label>
                    <input type="number" value={campaignDailyBudget}
                      onChange={e => { setCampaignDailyBudget(e.target.value); setResult(null) }}
                      min="1" step="1" className={inputCls} placeholder="50" />
                    <p className="text-[11px] text-gray-400 mt-1">
                      CBO 模式：预算在广告系列层统一分配，AdSet 不再单独设置日预算。
                    </p>
                  </div>
                )}
              </div>
            </SectionCard>

            {/* ══ W2A: 创意与文案（全局共享） ══ */}
            {isW2a && (
              <SectionCard title="创意与文案（全局共享）" className="mb-6">
                <div className="space-y-4">
                  {/* Page */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="block text-xs font-medium text-gray-600">主页 (Page) <span className="text-red-400">*</span></label>
                      <button type="button" onClick={() => setPageManual(!pageManual)} className="text-[11px] text-blue-500 hover:text-blue-600">
                        {pageManual ? '切换为下拉选择' : '手动输入 Page ID'}
                      </button>
                    </div>
                    {pageManual ? (
                      <input type="text" value={w2a.pageId} onChange={e => setField('pageId', e.target.value)} placeholder="手动输入 Facebook Page ID" className={inputCls} />
                    ) : (
                      <>
                        <select value={w2a.pageId} onChange={e => setField('pageId', e.target.value)} disabled={!adAccountId || pagesLoading} className={`${inputCls} bg-white`}>
                          <option value="">{!adAccountId ? '请先选择广告账户' : pagesLoading ? '加载中...' : '请选择主页'}</option>
                          {pages.map(p => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}
                        </select>
                        {pagesError && <p className="text-xs text-red-400 mt-1">拉取失败: {pagesError}</p>}
                        {!pagesLoading && adAccountId && pages.length === 0 && !pagesError && (
                          <p className="text-xs text-gray-400 mt-1">未找到可用主页，<button type="button" onClick={() => setPageManual(true)} className="text-blue-500 hover:underline">手动输入</button></p>
                        )}
                      </>
                    )}
                  </div>
                  {/* URL + 落地页库 */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="block text-xs font-medium text-gray-600">Landing Page URL <span className="text-red-400">*</span></label>
                      <button type="button" onClick={() => setShowLPPicker(true)} className="text-xs text-blue-500 hover:text-blue-600 flex items-center gap-1">
                        <Package className="w-3 h-3" />从落地页库选择
                      </button>
                    </div>
                    <input type="url" value={w2a.landingPageUrl} onChange={e => setField('landingPageUrl', e.target.value)} placeholder="https://example.com/landing" className={inputCls} />
                    {lpRef && (
                      <p className="text-xs text-blue-400 mt-1">
                        来源资产: {lpRef.name}
                        <button type="button" className="text-gray-400 hover:text-red-400 ml-2" onClick={() => setLpRef(null)}>清除引用</button>
                      </p>
                    )}
                  </div>
                  {/* Texts + 文案库 */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="block text-xs font-medium text-gray-600">Primary Text <span className="text-red-400">*</span></label>
                      <button type="button" onClick={() => setShowCopyPicker(true)} className="text-xs text-blue-500 hover:text-blue-600 flex items-center gap-1">
                        <Package className="w-3 h-3" />从文案库选择
                      </button>
                    </div>
                    <textarea value={w2a.primaryText} onChange={e => setField('primaryText', e.target.value)} rows={2} placeholder="广告主文案" className={inputCls} />
                    {copyRef && (
                      <p className="text-xs text-blue-400 mt-1">
                        来源文案: {copyRef.name}
                        <button type="button" className="text-gray-400 hover:text-red-400 ml-2" onClick={() => setCopyRef(null)}>清除引用</button>
                      </p>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Headline <span className="text-red-400">*</span></label>
                      <input type="text" value={w2a.headline} onChange={e => setField('headline', e.target.value)} placeholder="标题" className={inputCls} />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Call To Action</label>
                      <select value={w2a.callToAction} onChange={e => setField('callToAction', e.target.value)} className={`${inputCls} bg-white`}>
                        {CTA_OPTIONS.map(c => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
                    <input type="text" value={w2a.description} onChange={e => setField('description', e.target.value)} placeholder="可选描述" className={inputCls} />
                  </div>
                </div>
              </SectionCard>
            )}

            {/* ══ 素材池 ══ */}
            <SectionCard title={`素材池 (${readyMaterials.length}/${MAX_MATERIALS})`} className="mb-6">
              <div className="space-y-4">
                {materials.some(m => m.type === 'video' && m.duration_sec != null && m.duration_sec > LONG_VIDEO_THRESHOLD) && (
                  <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-50 border border-amber-200 text-sm text-amber-800">
                    <AlertCircle className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
                    <div>
                      <div className="font-medium">包含超过 10 分钟的长视频素材</div>
                      <div className="text-amber-700 mt-0.5">TikTok Non-Spark Ads 视频时长上限为 10 分钟。长视频是否可直接用于广告投放，以 TikTok 广告规格和账户能力为准。</div>
                    </div>
                  </div>
                )}
                <div className="flex items-center gap-3 flex-wrap">
                  <input ref={fileInputRef} type="file" multiple
                    accept=".jpg,.jpeg,.png,.gif,.bmp,.webp,.mp4,.mov,.avi,.mkv,.webm,.m4v"
                    className="hidden"
                    onChange={e => { if (e.target.files?.length) handleFileSelect(e.target.files); e.target.value = '' }}
                  />
                  <button type="button" onClick={() => fileInputRef.current?.click()}
                    disabled={!adAccountId || materials.length >= MAX_MATERIALS}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl border border-gray-200 text-sm text-gray-600 hover:bg-white hover:border-gray-300 transition disabled:opacity-50">
                    <Plus className="w-4 h-4" /> 本地批量上传
                  </button>
                  {isMeta && (
                    <button type="button"
                      onClick={() => {
                        if (!adAccountId) { alert('请先选择 Meta 广告账户'); return }
                        setShowAccountAssetPicker(true)
                      }}
                      disabled={!adAccountId || materials.length >= MAX_MATERIALS}
                      className="flex items-center gap-2 px-4 py-2 rounded-xl border border-gray-200 text-sm text-gray-600 hover:bg-white hover:border-gray-300 transition disabled:opacity-50"
                      title={adAccountId ? '从当前广告账户已上传素材中选择（含 Meta 平台手动上传）' : '请先选择 Meta 广告账户'}>
                      <Package className="w-4 h-4" /> 账户已有素材
                    </button>
                  )}
                  <span className="text-xs text-gray-400">支持批量选择，图片和视频可混合，最多 {MAX_MATERIALS} 个</span>
                </div>

                {materials.length > 0 && (
                  <div className="border border-gray-100 rounded-xl overflow-hidden">
                    <table className="w-full text-xs">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="text-left px-3 py-2 font-medium text-gray-500 w-8">#</th>
                          <th className="text-left px-3 py-2 font-medium text-gray-500">文件名</th>
                          <th className="text-left px-3 py-2 font-medium text-gray-500 w-16">类型</th>
                          <th className="text-left px-3 py-2 font-medium text-gray-500 w-20">状态</th>
                          <th className="text-left px-3 py-2 font-medium text-gray-500">Hash / ID</th>
                          <th className="text-left px-3 py-2 font-medium text-gray-500">封面图</th>
                          <th className="text-left px-3 py-2 font-medium text-gray-500">Ad 名称</th>
                          <th className="text-left px-3 py-2 font-medium text-gray-500 w-10"></th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {materials.map((m, i) => (
                          <tr key={m.id} className={m.status === 'error' ? 'bg-red-50/50' : ''}>
                            <td className="px-3 py-2 text-gray-400">{i + 1}</td>
                            <td className="px-3 py-2 text-gray-700 max-w-[160px] truncate" title={m.original_name}>{m.original_name}</td>
                            <td className="px-3 py-2">
                              <span className={`inline-flex items-center gap-1 ${m.type === 'video' ? 'text-purple-600' : 'text-blue-600'}`}>
                                {m.type === 'video' ? <Film className="w-3 h-3" /> : <Image className="w-3 h-3" />}
                                {m.type}
                              </span>
                              {m.source === 'account_asset' && (
                                <span className="ml-1 inline-block px-1.5 py-0.5 rounded text-[9px] bg-emerald-50 text-emerald-600 border border-emerald-100" title="来自当前广告账户已上传素材">账户</span>
                              )}
                              {m.source === 'local_upload' && (
                                <span className="ml-1 inline-block px-1.5 py-0.5 rounded text-[9px] bg-gray-50 text-gray-500 border border-gray-100" title="本地批量上传">本地</span>
                              )}
                            </td>
                            <td className="px-3 py-2">
                              {m.status === 'uploading' && (
                                <span className="flex items-center gap-1 text-amber-500">
                                  <Loader2 className="w-3 h-3 animate-spin" />
                                  {m.progress < 100 ? `${m.progress}%` : '处理中...'}
                                </span>
                              )}
                              {m.status === 'success' && <span className="text-green-600 flex items-center gap-1"><CheckCircle className="w-3 h-3" /> 就绪</span>}
                              {m.status === 'error' && <span className="text-red-500" title={m.error}>失败</span>}
                            </td>
                            <td className="px-3 py-2 text-gray-500 font-mono text-[11px] max-w-[100px] truncate">
                              {m.type === 'video' ? (m.video_id || '-') : (m.image_hash || '-')}
                              {m.error && !m.video_id && !m.image_hash && <span className="text-red-400 font-sans">{m.error}</span>}
                              {m.type === 'video' && m.duration_sec != null && m.duration_sec > LONG_VIDEO_THRESHOLD && (
                                <div className="mt-1 flex items-center gap-1 text-amber-600 font-sans text-[10px]" title="该视频超过 10 分钟，是否可直接用于广告投放以 TikTok 广告规格和账户能力为准">
                                  <AlertCircle className="w-3 h-3" />长视频
                                </div>
                              )}
                            </td>
                            {/* 封面图列 */}
                            <td className="px-3 py-2">
                              {m.type === 'video' ? (
                                m.image_hash ? (
                                  <span className="text-green-600 text-[11px] font-mono" title={`hash: ${m.image_hash}`}>
                                    <CheckCircle className="w-3 h-3 inline mr-0.5" />{m.image_hash.slice(0, 8)}...
                                  </span>
                                ) : m.picture_url ? (
                                  <span className="text-green-600 text-[11px]" title={m.picture_url}>
                                    <CheckCircle className="w-3 h-3 inline mr-0.5" />自动封面
                                  </span>
                                ) : m.status === 'uploading' ? (
                                  <span className="text-gray-400 text-[11px]">
                                    <Loader2 className="w-3 h-3 inline mr-0.5 animate-spin" />等待上传完成
                                  </span>
                                ) : m.thumbnail_uploading ? (
                                  <span className="flex items-center gap-1 text-amber-500">
                                    <Loader2 className="w-3 h-3 animate-spin" /> 上传中
                                  </span>
                                ) : m.status === 'success' ? (
                                  <div className="flex flex-col gap-0.5">
                                    <label className="cursor-pointer text-blue-500 hover:text-blue-600 whitespace-nowrap">
                                      <Image className="w-3 h-3 inline mr-0.5" />上传封面
                                      <input type="file" accept=".jpg,.jpeg,.png" className="hidden"
                                        onChange={e => {
                                          const f = e.target.files?.[0]
                                          if (f) uploadThumbnail(m.id, f)
                                          e.target.value = ''
                                        }} />
                                    </label>
                                    {m.thumbnail_error && <span className="text-red-400 text-[10px]">{m.thumbnail_error}</span>}
                                    <input type="text" placeholder="或输入 hash"
                                      className="w-full px-1 py-0.5 border border-gray-200 rounded text-[11px] focus:outline-none focus:ring-1 focus:ring-blue-400 mt-0.5"
                                      onBlur={e => {
                                        const v = e.target.value.trim()
                                        if (v) setMaterials(prev => prev.map(x => x.id === m.id ? { ...x, image_hash: v } : x))
                                      }} />
                                  </div>
                                ) : (
                                  <span className="text-gray-300">—</span>
                                )
                              ) : (
                                <span className="text-gray-300">—</span>
                              )}
                            </td>
                            <td className="px-3 py-2">
                              <input type="text" value={m.ad_name}
                                onChange={e => setMaterials(prev => prev.map(x => x.id === m.id ? { ...x, ad_name: e.target.value } : x))}
                                className="w-full px-2 py-1 border border-gray-200 rounded text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                              />
                            </td>
                            <td className="px-3 py-2">
                              <button type="button" onClick={() => removeMaterial(m.id)} className="text-gray-400 hover:text-red-500 transition">
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {materials.length === 0 && (
                  <p className="text-sm text-gray-400 text-center py-6">暂无素材，请点击上方按钮上传</p>
                )}
                {readyMaterials.some(m => m.type === 'video' && !m.image_hash && !m.picture_url) && (
                  <p className="text-xs text-amber-600 bg-amber-50 rounded-lg px-3 py-2">
                    <AlertCircle className="w-3.5 h-3.5 inline mr-1" />
                    有视频素材缺少封面图 — 请手动上传封面，或等待 Meta 自动生成
                  </p>
                )}
              </div>
            </SectionCard>

            {/* ══ Meta W2A Conversion ABO：投放时间（AdSet 级字段） ══ */}
            {isW2aConversion && (
              <SectionCard title="投放时间" className="mb-6">
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1.5">
                        开始时间 <span className="text-red-400">*</span>
                      </label>
                      <input type="datetime-local" value={scheduleStartLocal}
                        onChange={e => { setScheduleStartLocal(e.target.value); setResult(null) }}
                        className={inputCls} />
                      <p className="text-[11px] text-gray-400 mt-1">必须晚于当前时间至少 10 分钟（Meta API 要求）</p>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1.5">
                        结束时间 <span className="text-gray-300">(可选)</span>
                      </label>
                      <input type="datetime-local" value={scheduleEndLocal}
                        onChange={e => { setScheduleEndLocal(e.target.value); setResult(null) }}
                        className={inputCls} />
                      <p className="text-[11px] text-gray-400 mt-1">不填表示长期投放；使用日预算时与开始时间间隔需 &gt; 24 小时</p>
                    </div>
                  </div>
                  <div className="text-xs text-gray-400 bg-gray-50 border border-gray-100 rounded-lg px-3 py-2 flex items-center gap-2">
                    <Shield className="w-3.5 h-3.5 text-gray-300" />
                    时区：使用浏览器本地时区 <span className="font-mono text-gray-500">{browserTz}</span>，提交时自动转为 ISO 8601 带时区偏移格式发往 Meta。
                  </div>
                </div>
              </SectionCard>
            )}

            {/* ══ AdSet 配置区 ══ */}
            <SectionCard title={`AdSet 配置 (${adSets.length})`} className="mb-6">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">每个 AdSet 可独立配置预算、国家和素材，最多 {MAX_ADSETS} 个</span>
                  <button type="button" onClick={addAdSet} disabled={adSets.length >= MAX_ADSETS}
                    className="flex items-center gap-1 text-sm text-blue-500 hover:text-blue-600 disabled:opacity-40 transition">
                    <Plus className="w-4 h-4" /> 添加 AdSet
                  </button>
                </div>

                {adSets.map((adSet, idx) => (
                  <div key={adSet.key} className="border border-gray-200 rounded-xl overflow-hidden">
                    {/* header */}
                    <div className="flex items-center justify-between px-4 py-2.5 bg-gray-50 border-b border-gray-100">
                      <button type="button" onClick={() => updateAdSet(adSet.key, { collapsed: !adSet.collapsed })}
                        className="flex items-center gap-2 text-sm font-medium text-gray-700 hover:text-blue-600 transition">
                        {adSet.collapsed ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
                        AdSet #{idx + 1}: {adSet.name || '未命名'}
                        <span className="text-xs font-normal text-gray-400">
                          ({adSet.material_ids.length} 素材 / {isW2aCbo ? 'CBO' : `$${adSet.daily_budget}/天`} / {adSet.countries.join(',')})
                        </span>
                      </button>
                      <div className="flex items-center gap-2">
                        <button type="button" onClick={() => duplicateAdSet(adSet.key)} title="复制"
                          className="text-gray-400 hover:text-blue-500 transition"><Copy className="w-3.5 h-3.5" /></button>
                        {adSets.length > 1 && (
                          <button type="button" onClick={() => removeAdSet(adSet.key)} title="删除"
                            className="text-gray-400 hover:text-red-500 transition"><Trash2 className="w-3.5 h-3.5" /></button>
                        )}
                      </div>
                    </div>

                    {!adSet.collapsed && (
                      <div className="p-4 space-y-4">
                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <label className="block text-xs font-medium text-gray-600 mb-1">AdSet 名称 <span className="text-red-400">*</span></label>
                            <input type="text" value={adSet.name}
                              onChange={e => updateAdSet(adSet.key, { name: e.target.value })}
                              className={inputCls} placeholder="AdSet 名称" />
                          </div>
                          {isW2aCbo ? (
                            <div>
                              <label className="block text-xs font-medium text-gray-600 mb-1">AdSet 日预算 (CBO)</label>
                              <div className="px-3 py-2 rounded-lg bg-gray-50 text-xs text-gray-500 border border-dashed border-gray-200">
                                CBO：预算由广告系列统一分配
                              </div>
                            </div>
                          ) : (
                            <div>
                              <label className="block text-xs font-medium text-gray-600 mb-1">日预算 ({budgetCurrency || '请选择账户'}) <span className="text-red-400">*</span></label>
                              <input type="number" value={adSet.daily_budget}
                                onChange={e => updateAdSet(adSet.key, { daily_budget: e.target.value })}
                                min="1" step="1" className={inputCls} placeholder="50" />
                            </div>
                          )}
                        </div>

                        <div>
                          <div className="flex items-center justify-between mb-1">
                            <label className="block text-xs font-medium text-gray-600">投放国家 <span className="text-red-400">*</span></label>
                            <button type="button" onClick={() => setShowRegionPicker(adSet.key)} className="text-xs text-blue-500 hover:text-blue-600 flex items-center gap-1">
                              <Package className="w-3 h-3" />选择地区组
                            </button>
                          </div>
                          <CountryMultiSelect value={adSet.countries}
                            onChange={c => updateAdSet(adSet.key, { countries: c })} />
                          {regionRefs[adSet.key] && (
                            <p className="text-xs text-blue-400 mt-1">
                              来源地区组: {regionRefs[adSet.key].name}
                              <button type="button" className="text-gray-400 hover:text-red-400 ml-2" onClick={() => setRegionRefs(prev => { const n = { ...prev }; delete n[adSet.key]; return n })}>清除引用</button>
                            </p>
                          )}
                        </div>

                        {/* Pixel / Event per adset (for conversion templates) */}
                        {isW2aConversion && (
                          <div className="grid grid-cols-2 gap-4">
                            <div>
                              <label className="block text-xs font-medium text-gray-600 mb-1">Pixel ID {isW2aConversion && <span className="text-red-400">*</span>}</label>
                              {pixelManual ? (
                                <input type="text" value={adSet.pixel_id}
                                  onChange={e => updateAdSet(adSet.key, { pixel_id: e.target.value })}
                                  placeholder="Pixel ID" className={inputCls} />
                              ) : (
                                <select value={adSet.pixel_id}
                                  onChange={e => updateAdSet(adSet.key, { pixel_id: e.target.value })}
                                  disabled={!adAccountId || pixelsLoading} className={`${inputCls} bg-white`}>
                                  <option value="">{pixelsLoading ? '加载中...' : '请选择 Pixel'}</option>
                                  {pixels.map(p => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}
                                </select>
                              )}
                            </div>
                            <div>
                              <label className="block text-xs font-medium text-gray-600 mb-1">Custom Event Type {isW2aConversion && <span className="text-red-400">*</span>}</label>
                              <select value={adSet.custom_event_type}
                                onChange={e => updateAdSet(adSet.key, { custom_event_type: e.target.value })}
                                className={`${inputCls} bg-white`}>
                                <option value="">请选择</option>
                                {EVENT_TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                              </select>
                            </div>
                          </div>
                        )}

                        {/* 素材勾选 */}
                        <div>
                          <div className="flex items-center justify-between mb-2">
                            <label className="text-xs font-medium text-gray-600">选择素材 <span className="text-red-400">*</span></label>
                            <div className="flex gap-2">
                              <button type="button" onClick={() => selectAllMaterials(adSet.key)}
                                className="text-[11px] text-blue-500 hover:text-blue-600">全选</button>
                              <button type="button" onClick={() => clearMaterials(adSet.key)}
                                className="text-[11px] text-gray-400 hover:text-gray-600">清空</button>
                            </div>
                          </div>
                          {readyMaterials.length === 0 ? (
                            <p className="text-xs text-gray-400 py-2">请先在素材池中上传素材</p>
                          ) : (
                            <div className="grid grid-cols-2 gap-2 max-h-40 overflow-y-auto pr-1">
                              {readyMaterials.map(m => {
                                const checked = adSet.material_ids.includes(m.id)
                                return (
                                  <label key={m.id}
                                    className={`flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition text-xs
                                      ${checked ? 'border-blue-300 bg-blue-50' : 'border-gray-100 hover:border-gray-200'}`}>
                                    <input type="checkbox" checked={checked}
                                      onChange={() => toggleMaterial(adSet.key, m.id)}
                                      className="w-3.5 h-3.5 rounded border-gray-300 text-blue-500 focus:ring-blue-400" />
                                    <span className={`${m.type === 'video' ? 'text-purple-600' : 'text-blue-600'}`}>
                                      {m.type === 'video' ? <Film className="w-3 h-3 inline" /> : <Image className="w-3 h-3 inline" />}
                                    </span>
                                    <span className="truncate flex-1" title={m.original_name}>{m.ad_name}</span>
                                  </label>
                                )
                              })}
                            </div>
                          )}
                          <p className="text-[11px] text-gray-400 mt-1">已选 {adSet.material_ids.length} / {readyMaterials.length} 个素材</p>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </SectionCard>

            {/* ══ Pixel 转化追踪（非 conversion 模板时全局配置） ══ */}
            {isW2a && !isW2aConversion && (
              <SectionCard title="Pixel 与转化追踪" className="mb-6">
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-xs font-medium text-gray-600">Pixel ID</label>
                        <button type="button" onClick={() => setPixelManual(!pixelManual)} className="text-[11px] text-blue-500 hover:text-blue-600">
                          {pixelManual ? '切换为下拉选择' : '手动输入'}
                        </button>
                      </div>
                      {pixelManual ? (
                        <input type="text" value={w2a.pixelId} onChange={e => setField('pixelId', e.target.value)} placeholder="手动输入 Pixel ID" className={inputCls} />
                      ) : (
                        <>
                          <select value={w2a.pixelId} onChange={e => setField('pixelId', e.target.value)} disabled={!adAccountId || pixelsLoading} className={`${inputCls} bg-white`}>
                            <option value="">{!adAccountId ? '请先选择广告账户' : pixelsLoading ? '加载中...' : '请选择 Pixel'}</option>
                            {pixels.map(p => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}
                          </select>
                          {pixelsError && <p className="text-xs text-red-400 mt-1">{pixelsError}</p>}
                        </>
                      )}
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Custom Event Type</label>
                      <select value={w2a.customEventType} onChange={e => setField('customEventType', e.target.value)} className={`${inputCls} bg-white`}>
                        <option value="">请选择转化事件</option>
                        {EVENT_TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    </div>
                  </div>
                </div>
              </SectionCard>
            )}
          </>
        )}

        {/* ══ 创建预览 ══ */}
        {currentTpl && readyMaterials.length > 0 && adSets.length > 0 && (
          <div className="mb-6 p-4 bg-blue-50/50 border border-blue-100 rounded-xl">
            <p className="text-sm font-medium text-blue-700 mb-2">创建预览</p>
            <div className="text-xs text-blue-600 space-y-1">
              <p>Campaign: <strong>{campaignName}</strong></p>
              {isW2aCbo && (
                <>
                  <p>预算模式: <strong>CBO / 广告系列预算</strong></p>
                  <p>Campaign 日预算: <strong>{budgetCurrency} {campaignDailyBudget || '0'}/天</strong></p>
                </>
              )}
              <p>AdSet 数量: <strong>{adSets.length}</strong></p>
              <p>素材总数: <strong>{readyMaterials.length}</strong></p>
              <p>预计 Ad 总数: <strong>{adSets.reduce((s, a) => s + a.material_ids.length, 0)}</strong></p>
              {adSets.map((a, i) => (
                <p key={a.key} className="pl-4">
                  AdSet #{i + 1} ({a.name}): {a.material_ids.length} 个 Ad
                  {!isW2aCbo && <> · {budgetCurrency} {a.daily_budget}/天</>}
                  {' · '}{a.countries.join(',')}
                </p>
              ))}
            </div>
          </div>
        )}

        {/* ══ 结果反馈 ══ */}
        {result && (
          <BatchResultDisplay result={result} />
        )}

        {/* ══ 校验提示 ══ */}
        {validationError && !result && (
          <p className="text-xs text-amber-500 mb-4">{validationError}</p>
        )}

        {/* ══ 提交按钮 ══ */}
        <div className="flex justify-end">
          <button type="submit" disabled={!canSubmit}
            className="px-6 py-2.5 bg-blue-500 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-xl shadow-sm shadow-blue-500/20 transition-all flex items-center gap-2">
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            {submitting ? '批量创建中...' : isUploading ? '素材上传中...' : '提交创建'}
          </button>
        </div>
      </form>

      {/* ── 资产库弹窗 ── */}
      <LandingPagePickerDialog
        open={showLPPicker}
        onClose={() => setShowLPPicker(false)}
        onSelect={(item: LandingPageAsset) => {
          setField('landingPageUrl', item.landing_page_url)
          setLpRef({ id: item.id, name: item.name, snapshot: item.landing_page_url })
        }}
      />
      <CopyPackPickerDialog
        open={showCopyPicker}
        onClose={() => setShowCopyPicker(false)}
        onSelect={(item: CopyPackAsset, mode: 'all' | 'empty') => {
          if (mode === 'all') {
            setField('primaryText', item.primary_text || '')
            setField('headline', item.headline || '')
            setField('description', item.description || '')
          } else {
            if (!w2a.primaryText) setField('primaryText', item.primary_text || '')
            if (!w2a.headline) setField('headline', item.headline || '')
            if (!w2a.description) setField('description', item.description || '')
          }
          setCopyRef({
            id: item.id, name: item.name,
            primaryTextSnapshot: item.primary_text || '',
            headlineSnapshot: item.headline || '',
            descriptionSnapshot: item.description || '',
          })
        }}
      />
      <RegionGroupPickerDialog
        open={!!showRegionPicker}
        onClose={() => setShowRegionPicker(null)}
        onSelect={(item: RegionGroupAsset) => {
          if (showRegionPicker) {
            updateAdSet(showRegionPicker, { countries: item.country_codes })
            setRegionRefs(prev => ({ ...prev, [showRegionPicker]: { id: item.id, name: item.name, snapshot: [...item.country_codes] } }))
          }
        }}
      />

      {/* Meta 账户已上传素材选择器 */}
      <MetaAccountAssetPicker
        open={showAccountAssetPicker}
        adAccountId={adAccountId}
        pickedKeys={accountAssetPickedKeys}
        onConfirm={addAccountAssets}
        onClose={() => setShowAccountAssetPicker(false)}
      />
    </div>
  )
}

// ─── 批量结果展示组件 ───
function BatchResultDisplay({ result }: { result: CreateResult }) {
  const details = result.details as BatchLaunchResult | undefined
  const isPartial = result.success && result.message.includes('部分')

  return (
    <div className={`mb-6 p-4 rounded-xl border ${
      result.draftSaved ? 'bg-blue-50 border-blue-200' : !result.success ? 'bg-red-50 border-red-200'
        : isPartial ? 'bg-amber-50 border-amber-200'
          : 'bg-green-50 border-green-200'
    }`}>
      <div className="flex items-start gap-3">
        {result.draftSaved ? <CheckCircle className="w-5 h-5 text-blue-500 shrink-0 mt-0.5" /> : !result.success
          ? <AlertCircle className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
          : isPartial
            ? <AlertCircle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
            : <CheckCircle className="w-5 h-5 text-green-500 shrink-0 mt-0.5" />}
        <div className="min-w-0 flex-1">
          <p className={`text-sm font-medium ${result.draftSaved ? 'text-blue-700' : !result.success ? 'text-red-700' : isPartial ? 'text-amber-700' : 'text-green-700'}`}>
            {result.draftSaved ? '草稿已保存' : !result.success ? '创建失败' : isPartial ? '部分创建成功' : '创建成功'}
          </p>
          <p className={`text-xs mt-1 ${result.draftSaved ? 'text-blue-600' : !result.success ? 'text-red-600' : isPartial ? 'text-amber-600' : 'text-green-600'}`}>{result.message}</p>

          {details && (
            <div className="mt-3 space-y-2">
              {/* 预算模式徽章（仅 Meta 链路返回 budget_mode 时展示） */}
              {(details.requested_budget_mode || details.actual_budget_mode) && (
                <div className="flex items-center gap-2 text-[11px]">
                  <span className="text-gray-500">预算模式:</span>
                  <span className={`px-2 py-0.5 rounded-full font-medium ${
                    details.actual_budget_mode === 'CBO'
                      ? 'bg-emerald-100 text-emerald-700'
                      : details.actual_budget_mode === 'CBO_FAILED'
                        ? 'bg-red-100 text-red-700'
                        : 'bg-gray-100 text-gray-600'
                  }`}>
                    {details.actual_budget_mode || details.requested_budget_mode}
                  </span>
                  {details.actual_budget_mode === 'CBO_FAILED' && (
                    <span className="text-red-500">CBO 创建失败，未自动切换到 ABO</span>
                  )}
                </div>
              )}
              {details.campaign && (
                <div className="text-xs">
                  <span className="font-medium text-gray-600">Campaign: </span>
                  {details.campaign.success
                    ? <span className="text-green-600">成功 (ID: {details.campaign.campaign_id})</span>
                    : (
                      <span className="text-red-600">失败 - {
                        details.campaign.error
                        || details.campaign.meta_error_message
                        || (details.campaign.meta_error_code ? `Meta API 错误 (code=${details.campaign.meta_error_code}${details.campaign.meta_error_subcode ? `, subcode=${details.campaign.meta_error_subcode}` : ''})` : '未知错误（请查看后端日志）')
                      }</span>
                    )}
                  {/* Meta error 详情 */}
                  {!details.campaign.success && (details.campaign.meta_error_code || details.campaign.meta_error_subcode) && (
                    <div className="mt-1 ml-1 text-[11px] text-red-500 space-y-0.5">
                      <div>code: <span className="font-mono">{details.campaign.meta_error_code ?? '-'}</span> / subcode: <span className="font-mono">{details.campaign.meta_error_subcode ?? '-'}</span></div>
                      {details.campaign.meta_error_message && <div>message: {details.campaign.meta_error_message}</div>}
                      {details.campaign.campaign_payload_debug && (
                        <details>
                          <summary className="cursor-pointer text-red-400 hover:text-red-600">查看 campaign payload</summary>
                          <pre className="mt-1 bg-white/60 rounded p-2 overflow-x-auto max-h-40">{JSON.stringify(details.campaign.campaign_payload_debug, null, 2)}</pre>
                        </details>
                      )}
                    </div>
                  )}
                </div>
              )}

              {details.adsets?.map((as, i) => (
                <div key={i} className="border border-gray-200 rounded-lg p-3 bg-white/60">
                  <div className="flex items-center gap-2 text-xs mb-1">
                    {as.success
                      ? <CheckCircle className="w-3 h-3 text-green-500" />
                      : <AlertCircle className="w-3 h-3 text-red-500" />}
                    <span className="font-medium text-gray-700">AdSet #{i + 1}: {as.adset_name}</span>
                    {as.success && <span className="text-green-600 text-[11px]">ID: {as.adset_id}</span>}
                    {!as.success && (
                      <span className="text-red-500 text-[11px]">{
                        as.error
                        || as.meta_error_message
                        || (as.meta_error_code ? `Meta API 错误 (code=${as.meta_error_code}${as.meta_error_subcode ? `, subcode=${as.meta_error_subcode}` : ''})` : '未知错误（请查看后端日志）')
                      }</span>
                    )}
                  </div>
                  {!as.success && (as.meta_error_code || as.meta_error_subcode) && (
                    <div className="ml-5 text-[11px] text-red-500 space-y-0.5">
                      <div>code: <span className="font-mono">{as.meta_error_code ?? '-'}</span> / subcode: <span className="font-mono">{as.meta_error_subcode ?? '-'}</span></div>
                      {as.meta_error_message && as.meta_error_message !== as.error && <div>message: {as.meta_error_message}</div>}
                    </div>
                  )}
                  {as.ads && as.ads.length > 0 && (
                    <div className="ml-5 space-y-0.5">
                      {as.ads.map((ad, j) => (
                        <div key={j} className="text-[11px] flex items-center gap-1">
                          {ad.success
                            ? <span className="text-green-600">OK</span>
                            : <span className="text-red-500">FAIL</span>}
                          <span className="text-gray-600">{ad.ad_name}</span>
                          <span className="text-gray-400">({ad.material_name})</span>
                          {ad.ad_id && <span className="text-gray-400 font-mono">ID:{ad.ad_id}</span>}
                          {ad.error && <span className="text-red-400">{ad.error}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {!details && result.details && (
            <details className="mt-2">
              <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600">查看原始详情</summary>
              <pre className="mt-1 text-[11px] text-gray-500 bg-white/60 rounded-lg p-2 overflow-x-auto max-h-40">
                {JSON.stringify(result.details, null, 2)}
              </pre>
            </details>
          )}
        </div>
      </div>
    </div>
  )
}
