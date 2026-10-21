import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PageHeader } from '@/components/common/PageHeader'
import { StatCard } from '@/components/common/StatCard'
import { FilterBar } from '@/components/common/FilterBar'
import { DateRangeFilter, getDefaultDateRange, type DateRange } from '@/components/common/DateRangeFilter'
import { GlobalSyncBar } from '@/components/common/GlobalSyncBar'
import {
  DollarSign, TrendingUp, BarChart3, Target, MousePointerClick,
  PlusCircle, Columns3, ChevronRight, ChevronDown,
  Loader2, AlertCircle, AlertTriangle, ArrowUpDown, ExternalLink, X,
  Play, Pause, Pencil, Search, RefreshCw,
} from 'lucide-react'
import { useBizOverview } from '@/hooks/use-biz'
import { useAuth } from '@/contexts/AuthContext'
import { fetchAdAccounts } from '@/services/accounts-mgmt'
import { readConsoleState, statusLabel } from './console-state'
import { useInsightConfig } from '@/hooks/use-insight'
import {
  fetchConsolePage, fetchConsoleChildren,
  updateBizEntityStatus,
  type AggRow, type AggParams,
} from '@/services/biz'
import { fetchSyncStatus, triggerSync } from '@/services/sync'
import { updateTikTokCampaign, updateTikTokCampaignStatus } from '@/services/tiktok-campaigns'
import { updateTikTokAdGroupStatus, updateTikTokAdGroup } from '@/services/tiktok-adgroups'
import { updateTikTokAdStatus } from '@/services/tiktok-ads'
import { updateMetaCampaignStatus } from '@/services/meta-campaigns'
import { updateMetaAdSetStatus } from '@/services/meta-adsets'
import { updateMetaAdStatus } from '@/services/meta-ads'

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function fmtUsd2(n: number | null) { return n != null ? `$${n.toFixed(2)}` : '-' }
function fmtPct(n: number | null) { return n != null ? `${(n * 100).toFixed(2)}%` : '-' }
function fmtRatio(n: number | null) { return n != null ? n.toFixed(2) : '-' }
function fmtNum(n: number | null) { return n != null ? n.toLocaleString() : '-' }

// ---------------------------------------------------------------------------
// 归因覆盖判定
// 判定规则：
//   normalized 端 spend > $5（排除浮点漂移/极小测试消耗），
//   但 attribution 数仓侧自报 spend 为 0 → 该账号/广告未被数仓的归因表覆盖。
//   此时 total_revenue / roas / 注册转化数大概率不可信，需在 UI 显著标注。
// 仅 source=blend/auto 时 attribution_spend 字段非 undefined。
// ---------------------------------------------------------------------------
const NO_ATTR_SPEND_THRESHOLD_USD = 5

function isMissingAttribution(row: Pick<AggRow, 'total_spend' | 'attribution_spend'>): boolean {
  if (row.attribution_spend === undefined) return false
  return row.total_spend > NO_ATTR_SPEND_THRESHOLD_USD && (row.attribution_spend || 0) <= 0
}

// ---------------------------------------------------------------------------
// Column defs for hierarchical table (aggregated data)
// ---------------------------------------------------------------------------



interface ColDef {
  key: string
  label: string
  group: 'core' | 'performance' | 'cost'
  defaultVisible: boolean
  align?: 'left' | 'right'
  format: (v: number | null) => string
  sortable?: boolean
}

const AGG_COLUMNS: ColDef[] = [
  { key: 'total_spend',         label: '消耗', group: 'core',        defaultVisible: true,  align: 'right', format: fmtUsd2,  sortable: true },
  { key: 'total_revenue',       label: '收入', group: 'core',        defaultVisible: true,  align: 'right', format: fmtUsd2,  sortable: true },
  { key: 'roas',                label: 'ROI',  group: 'performance', defaultVisible: true,  align: 'right', format: fmtRatio, sortable: true },
  { key: 'ctr',                 label: 'CTR',  group: 'performance', defaultVisible: true,  align: 'right', format: fmtPct,   sortable: true },
  { key: 'cpc',                 label: 'CPC',  group: 'cost',        defaultVisible: true,  align: 'right', format: fmtUsd2,  sortable: true },
  { key: 'total_registrations', label: '注册', group: 'performance', defaultVisible: true,  align: 'right', format: fmtNum,   sortable: true },
  { key: 'total_installs',      label: '安装', group: 'performance', defaultVisible: false, align: 'right', format: fmtNum,   sortable: true },
  { key: 'total_impressions',   label: '展示', group: 'performance', defaultVisible: false, align: 'right', format: fmtNum,   sortable: true },
  { key: 'total_clicks',        label: '点击', group: 'performance', defaultVisible: false, align: 'right', format: fmtNum,   sortable: true },
  { key: 'total_conversions',   label: '转化', group: 'performance', defaultVisible: false, align: 'right', format: fmtNum,   sortable: true },
  { key: 'cpi',                 label: 'CPI',  group: 'cost',        defaultVisible: false, align: 'right', format: fmtUsd2,  sortable: true },
  { key: 'cpa',                 label: 'CPA',  group: 'cost',        defaultVisible: false, align: 'right', format: fmtUsd2,  sortable: true },
  { key: 'cpm',                 label: 'CPM',  group: 'cost',        defaultVisible: false, align: 'right', format: fmtUsd2,  sortable: true },
]

// ---------------------------------------------------------------------------
// Row type for flat rendering
// ---------------------------------------------------------------------------

type RowLevel = 'campaign' | 'adset' | 'ad'
type StatusRowType = 'loading' | 'error' | 'empty'

interface DataRow {
  kind: 'data'
  rowType: RowLevel
  level: 0 | 1 | 2
  id: string
  name: string
  parentId: string
  data: AggRow
}

interface StatusRow {
  kind: 'status'
  statusType: StatusRowType
  level: 1 | 2
  parentId: string
  parentType: 'campaign' | 'adset'
}

type FlatRow = DataRow | StatusRow

// ---------------------------------------------------------------------------
// Toast helper
// ---------------------------------------------------------------------------

function useToast() {
  const [msg, setMsg] = useState<{ text: string; type: 'success' | 'error' } | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const show = useCallback((text: string, type: 'success' | 'error' = 'success') => {
    clearTimeout(timer.current)
    setMsg({ text, type })
    timer.current = setTimeout(() => setMsg(null), 3000)
  }, [])
  const Toast = msg ? (
    <div className={`fixed top-6 right-6 z-[100] px-4 py-2.5 rounded-lg shadow-lg text-sm font-medium ${
      msg.type === 'success' ? 'bg-green-600 text-white' : 'bg-red-600 text-white'
    }`}>{msg.text}</div>
  ) : null
  return { show, Toast }
}

// ---------------------------------------------------------------------------
// Budget edit modal
// ---------------------------------------------------------------------------

function BudgetModal({ currentBudget, onSave, onClose, saving }: {
  currentBudget: number; onSave: (budget: number) => void; onClose: () => void; saving: boolean
}) {
  const [value, setValue] = useState(String(currentBudget || ''))
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl p-6 w-80 space-y-4" onClick={e => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-gray-800">编辑预算</h3>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">日预算 (USD)</label>
          <input type="number" step="0.01" min="0" value={value} onChange={e => setValue(e.target.value)} autoFocus
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400 transition" placeholder="输入新预算" />
        </div>
        <div className="flex items-center justify-end gap-2">
          <button onClick={onClose} disabled={saving}
            className="px-4 py-2 text-xs text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition disabled:opacity-50">取消</button>
          <button onClick={() => { const n = parseFloat(value); if (!isNaN(n) && n >= 0) onSave(n) }}
            disabled={saving || !value || isNaN(parseFloat(value))}
            className="px-4 py-2 text-xs text-white bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition disabled:opacity-50 flex items-center gap-1.5">
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />} 确认
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

interface EntityMeta { status: string; budget: number; accountId: string }
function isTikTokEnabled(status: string) { return status === 'ENABLE' || status === 'ENABLED' || status === 'ACTIVE' }
function isMetaActive(status: string) { return status === 'ACTIVE' }
function isEnabled(platform: string, status: string) {
  return platform === 'tiktok' ? isTikTokEnabled(status) : isMetaActive(status)
}
// ---------------------------------------------------------------------------
// Level styling
// ---------------------------------------------------------------------------

const LEVEL_BG: Record<RowLevel, string> = {
  campaign: '',
  adset: 'bg-slate-50/70',
  ad: 'bg-blue-50/30',
}

const LEVEL_INDENT: Record<number, string> = {
  0: 'pl-3',
  1: 'pl-10',
  2: 'pl-16',
}

const LEVEL_BADGE: Record<RowLevel, { label: string; cls: string }> = {
  campaign: { label: 'C', cls: 'bg-blue-100 text-blue-700' },
  adset:    { label: 'AG', cls: 'bg-violet-100 text-violet-700' },
  ad:       { label: 'Ad', cls: 'bg-emerald-100 text-emerald-700' },
}

// ---------------------------------------------------------------------------
// Column persistence
// ---------------------------------------------------------------------------

function colStorageKey(platform: string) { return `console_hier_cols_v2_${platform}` }
function loadVisibleCols(platform: string): string[] {
  try {
    const raw = localStorage.getItem(colStorageKey(platform))
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return AGG_COLUMNS.filter(c => c.defaultVisible).map(c => c.key)
}
function saveVisibleCols(platform: string, cols: string[]) {
  localStorage.setItem(colStorageKey(platform), JSON.stringify(cols))
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface AdConsoleProps {
  platform: 'tiktok' | 'meta'
  title: string
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AdConsole({ platform, title }: AdConsoleProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const platformLabel = platform === 'tiktok' ? 'TikTok' : 'Meta'
  const { show: toast, Toast } = useToast()

  // ── State ──
  const { currentApplication } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = readConsoleState(searchParams, getDefaultDateRange('7d'))
  const { dateRange, accountId, search: searchFilter, sortKey, sortDir, page } = filters
  const [searchText, setSearchText] = useState(searchFilter)
  useEffect(() => setSearchText(searchFilter), [searchFilter])
  const patchFilters = useCallback((patch: Record<string, string | null>) => {
    setSearchParams(previous => {
      const next = new URLSearchParams(previous)
      const range = readConsoleState(previous, getDefaultDateRange('7d')).dateRange
      next.set('start_date', range.startDate)
      next.set('end_date', range.endDate)
      for (const [key, value] of Object.entries(patch)) {
        if (value == null || value === '') next.delete(key)
        else next.set(key, value)
      }
      return next
    })
  }, [setSearchParams])
  const scopeKey = `${platform}:${currentApplication?.id}:${dateRange.startDate}:${dateRange.endDate}:${accountId}:${sortKey}:${sortDir}:${searchFilter}:${page}`
  const requestScope = useRef(scopeKey)
  const epoch = useRef(0)
  if (requestScope.current !== scopeKey) {
    requestScope.current = scopeKey
    epoch.current++
  }
  const [childErrors, setChildErrors] = useState<Record<string, string>>({})
  const [batchResults, setBatchResults] = useState<{ id: string; error?: string }[]>([])

  const [visibleCols, setVisibleCols] = useState<string[]>(() => loadVisibleCols(platform))
  const [showColPicker, setShowColPicker] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [budgetEdit, setBudgetEdit] = useState<{ campaignId: string; entityType: 'campaign' | 'adset'; budget: number; accountId?: string } | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  // Expand state
  const [expandedCampaigns, setExpandedCampaigns] = useState<Set<string>>(new Set())
  const [expandedAdsets, setExpandedAdsets] = useState<Set<string>>(new Set())

  // Child data cache: campaignId -> AggRow[] , adsetId -> AggRow[]
  const [adsetCache, setAdsetCache] = useState<Record<string, AggRow[]>>({})
  const [adCache, setAdCache] = useState<Record<string, AggRow[]>>({})
  const [loadingIds, setLoadingIds] = useState<Set<string>>(new Set())
  const [errorIds, setErrorIds] = useState<Set<string>>(new Set())

  // persist columns
  const handleColChange = useCallback((cols: string[]) => {
    setVisibleCols(cols)
    saveVisibleCols(platform, cols)
  }, [platform])

  const clearChildren = useCallback(() => {
    epoch.current++
    setExpandedCampaigns(new Set())
    setExpandedAdsets(new Set())
    setAdsetCache({})
    setAdCache({})
    setLoadingIds(new Set())
    setErrorIds(new Set())
    setChildErrors({})
    setSelectedIds(new Set())
    setBudgetEdit(null)
  }, [])
  useEffect(() => {
    clearChildren()
    setBatchResults([])
  }, [scopeKey, clearChildren])

  const handleDateChange = useCallback((range: DateRange) => {
    patchFilters({ start_date: range.startDate, end_date: range.endDate, page: null })
  }, [patchFilters])

  const { data: accountsResponse, error: accountsError } = useQuery({
    queryKey: ['ad-accounts', platform, currentApplication?.id],
    queryFn: () => fetchAdAccounts(platform),
  })
  const accounts = accountsResponse?.data ?? []
  const selectedAccount = accounts.find(a => a.account_id === accountId)
  const { data: overview, isLoading: ovLoading, error: overviewError } = useBizOverview({ ...dateRange, platform, account_id: accountId || undefined })
  const aggParams: AggParams = useMemo(() => ({
    startDate: dateRange.startDate, endDate: dateRange.endDate,
    platform, account_id: accountId || undefined, order_by: sortKey, order_dir: sortDir,
  }), [dateRange.startDate, dateRange.endDate, platform, accountId, sortKey, sortDir])
  const { data: campaignPage, isLoading: campLoading, isError: campError, error: campaignError } = useQuery({
    queryKey: ['biz', 'console', currentApplication?.id, aggParams, searchFilter, page],
    queryFn: () => fetchConsolePage('campaign', { ...aggParams, q: searchFilter, page, page_size: 50 }),
  })
  const campaignRows = campaignPage?.list
  const { data: insightCfg } = useInsightConfig()
  function metaMap(rows: AggRow[], key: 'campaign_id' | 'adgroup_id' | 'ad_id') {
    return new Map(rows.map(row => [row[key] || '', { status: row.status || 'UNKNOWN', budget: row.budget ?? 0, accountId: row.account_id }]))
  }
  const campaignMetaMap = metaMap(campaignRows ?? [], 'campaign_id')
  const adgroupMetaMap = metaMap(Object.values(adsetCache).flat(), 'adgroup_id')
  const adMetaMap = metaMap(Object.values(adCache).flat(), 'ad_id')

  const refreshAll = () => {
    clearChildren()
    void queryClient.invalidateQueries({ queryKey: ['biz'] })
    void queryClient.invalidateQueries({ queryKey: ['sync-status-all'] })
  }
  const lastSync = useRef<string | null>(null)
  const { data: syncStatus } = useQuery({
    queryKey: ['sync-status-all'], queryFn: fetchSyncStatus, refetchInterval: 15_000,
  })
  useEffect(() => {
    const stamp = JSON.stringify(Object.values(syncStatus ?? {}).map(s => s.last_synced_at))
    if (lastSync.current !== null && lastSync.current !== stamp) {
      clearChildren()
      void queryClient.invalidateQueries({ queryKey: ['biz'] })
    }
    lastSync.current = stamp
  }, [syncStatus, clearChildren, queryClient])

  // 页面加载时：若结构数据超过 15 分钟未同步，静默触发一次同步
  useEffect(() => {
    let cancelled = false
    async function autoSyncIfStale() {
      try {
        const status = await fetchSyncStatus()
        const lastSynced = status.structure?.last_synced_at
        if (!lastSynced) {
          if (!cancelled) await triggerSync(2)
          return
        }
        const ageMin = (Date.now() - new Date(lastSynced).getTime()) / 60_000
        if (ageMin > 15 && !cancelled) {
          await triggerSync(2)
        }
      } catch {
        // 静默失败，不影响页面使用
      }
    }
    if (accounts.length) void autoSyncIfStale()
    return () => { cancelled = true }
  }, [platform, accounts.length])

  // ── Expand handlers ──
  const toggleCampaign = useCallback(async (campaignId: string) => {
    const requestEpoch = epoch.current
    setExpandedCampaigns(prev => {
      const next = new Set(prev)
      if (next.has(campaignId)) {
        next.delete(campaignId)
        // also collapse child adsets
        setExpandedAdsets(prevAs => {
          const nextAs = new Set(prevAs)
          const adsets = adsetCache[campaignId] || []
          for (const a of adsets) nextAs.delete(a.adgroup_id || '')
          return nextAs
        })
        return next
      }
      next.add(campaignId)
      return next
    })

    // Fetch adsets if not cached
    if (!adsetCache[campaignId]) {
      setLoadingIds(prev => new Set(prev).add(campaignId))
      setErrorIds(prev => { const n = new Set(prev); n.delete(campaignId); return n })
      try {
        const rows = await fetchConsoleChildren('adgroup', {
          ...aggParams,
          campaign_id: campaignId,
        })
        if (requestEpoch === epoch.current) setAdsetCache(prev => ({ ...prev, [campaignId]: rows }))
      } catch (error) {
        if (requestEpoch === epoch.current) {
          setErrorIds(prev => new Set(prev).add(campaignId))
          setChildErrors(prev => ({ ...prev, [campaignId]: error instanceof Error ? error.message : '加载失败' }))
        }
      } finally {
        if (requestEpoch === epoch.current) setLoadingIds(prev => { const n = new Set(prev); n.delete(campaignId); return n })
      }
    }
  }, [aggParams, adsetCache])

  const toggleAdset = useCallback(async (adsetId: string) => {
    const requestEpoch = epoch.current
    setExpandedAdsets(prev => {
      const next = new Set(prev)
      if (next.has(adsetId)) next.delete(adsetId)
      else next.add(adsetId)
      return next
    })

    if (!adCache[adsetId]) {
      setLoadingIds(prev => new Set(prev).add(adsetId))
      setErrorIds(prev => { const n = new Set(prev); n.delete(adsetId); return n })
      try {
        const rows = await fetchConsoleChildren('ad', {
          ...aggParams,
          adgroup_id: adsetId,
        })
        if (requestEpoch === epoch.current) setAdCache(prev => ({ ...prev, [adsetId]: rows }))
      } catch (error) {
        if (requestEpoch === epoch.current) {
          setErrorIds(prev => new Set(prev).add(adsetId))
          setChildErrors(prev => ({ ...prev, [adsetId]: error instanceof Error ? error.message : '加载失败' }))
        }
      } finally {
        if (requestEpoch === epoch.current) setLoadingIds(prev => { const n = new Set(prev); n.delete(adsetId); return n })
      }
    }
  }, [aggParams, adCache])

  const retryLoad = useCallback(async (id: string, type: 'campaign' | 'adset') => {
    const requestEpoch = epoch.current
    setLoadingIds(prev => new Set(prev).add(id))
    setErrorIds(prev => { const n = new Set(prev); n.delete(id); return n })
    try {
      if (type === 'campaign') {
        const rows = await fetchConsoleChildren('adgroup', { ...aggParams, campaign_id: id })
        if (requestEpoch === epoch.current) setAdsetCache(prev => ({ ...prev, [id]: rows }))
      } else {
        const rows = await fetchConsoleChildren('ad', { ...aggParams, adgroup_id: id })
        if (requestEpoch === epoch.current) setAdCache(prev => ({ ...prev, [id]: rows }))
      }
    } catch (error) {
      if (requestEpoch === epoch.current) {
        setErrorIds(prev => new Set(prev).add(id))
        setChildErrors(prev => ({ ...prev, [id]: error instanceof Error ? error.message : '加载失败' }))
      }
    } finally {
      if (requestEpoch === epoch.current) setLoadingIds(prev => { const n = new Set(prev); n.delete(id); return n })
    }
  }, [aggParams])

  // ── Generic status toggle mutation ──
  const toggleMutation = useMutation({
    mutationFn: async ({ entityId, entityType, newStatus, accountId }: {
      entityId: string; entityType: RowLevel; newStatus: string; accountId: string
    }) => {
      if (entityType === 'campaign') {
        if (platform === 'tiktok') await updateTikTokCampaignStatus([entityId], newStatus, accountId)
        else await updateMetaCampaignStatus(entityId, newStatus, accountId)
      } else if (entityType === 'adset') {
        if (platform === 'tiktok') await updateTikTokAdGroupStatus([entityId], newStatus, accountId)
        else await updateMetaAdSetStatus(entityId, newStatus, accountId)
      } else {
        if (platform === 'tiktok') await updateTikTokAdStatus([entityId], newStatus, accountId)
        else await updateMetaAdStatus(entityId, newStatus, accountId)
      }
      const bizEntityType = entityType === 'adset' ? 'adgroup' : entityType
      await updateBizEntityStatus(platform, bizEntityType, entityId, newStatus)
    },
    onSuccess: () => { toast(`操作成功`, 'success'); refreshAll() },
    onError: (err: Error) => { toast(`操作失败: ${err.message}`, 'error') },
  })

  const batchMutation = useMutation({
    mutationFn: async (newStatus: string) => {
      const ids = Array.from(selectedIds)
      const groups = new Map<string, string[]>()
      for (const id of ids) {
        const account = campaignMetaMap.get(id)?.accountId
        if (!account) throw new Error('所选广告缺少账户信息，请刷新后重试')
        const group = groups.get(account) ?? []
        group.push(id)
        groups.set(account, group)
      }
      const results: { id: string; error?: string }[] = []
      for (const [account, group] of groups) {
        if (platform === 'tiktok') {
          try {
            await updateTikTokCampaignStatus(group, newStatus, account)
            results.push(...group.map(id => ({ id })))
          } catch (error) {
            results.push(...group.map(id => ({ id, error: error instanceof Error ? error.message : '操作失败' })))
          }
        } else {
          for (const id of group) {
            try { await updateMetaCampaignStatus(id, newStatus, account); results.push({ id }) }
            catch (error) { results.push({ id, error: error instanceof Error ? error.message : '操作失败' }) }
          }
        }
      }
      for (const item of results.filter(item => !item.error)) {
        try { await updateBizEntityStatus(platform, 'campaign', item.id, newStatus) }
        catch { /* Platform change succeeded; do not repeat it because the local refresh failed. */ }
      }
      return results
    },
    onSuccess: results => {
      const failed = results.filter(item => item.error)
      refreshAll()
      setBatchResults(results)
      setSelectedIds(new Set(failed.map(item => item.id)))
      toast(`批量操作：成功 ${results.length - failed.length} 个，失败 ${failed.length} 个`, failed.length ? 'error' : 'success')
    },
    onError: (err: Error) => toast(`批量操作失败: ${err.message}`, 'error'),
  })

  // Budget edit: supports campaign and adgroup (TikTok)
  const budgetMutation = useMutation({
    mutationFn: async ({ entityId, entityType, budget, accountId }: {
      entityId: string; entityType: 'campaign' | 'adset'; budget: number; accountId?: string
    }) => {
      if (entityType === 'campaign') {
        return updateTikTokCampaign({ campaign_id: entityId, budget }, accountId)
      }
      return updateTikTokAdGroup({ adgroup_id: entityId, budget }, accountId)
    },
    onSuccess: () => { toast('预算修改成功', 'success'); setBudgetEdit(null); refreshAll() },
    onError: (err: Error) => { toast(`预算修改失败: ${err.message}`, 'error') },
  })

  // ── Derived data ──
  const roiThreshold = insightCfg?.roi?.low ?? 1.5
  const activeCols = AGG_COLUMNS.filter(c => visibleCols.includes(c.key))

  const filteredCampaigns = useMemo(() => campaignRows ?? [], [campaignRows])

  // Build flat rows with inline status rows
  const flatRows = useMemo<FlatRow[]>(() => {
    const result: FlatRow[] = []
    for (const camp of filteredCampaigns) {
      result.push({
        kind: 'data', rowType: 'campaign', level: 0,
        id: camp.campaign_id, name: camp.campaign_name || camp.campaign_id,
        parentId: '', data: camp,
      })
      if (expandedCampaigns.has(camp.campaign_id)) {
        const adsets = adsetCache[camp.campaign_id]
        if (!adsets && loadingIds.has(camp.campaign_id)) {
          result.push({ kind: 'status', statusType: 'loading', level: 1, parentId: camp.campaign_id, parentType: 'campaign' })
        } else if (!adsets && errorIds.has(camp.campaign_id)) {
          result.push({ kind: 'status', statusType: 'error', level: 1, parentId: camp.campaign_id, parentType: 'campaign' })
        } else if (adsets && adsets.length === 0) {
          result.push({ kind: 'status', statusType: 'empty', level: 1, parentId: camp.campaign_id, parentType: 'campaign' })
        } else if (adsets) {
          for (const ag of adsets) {
            const agId = ag.adgroup_id || ''
            result.push({
              kind: 'data', rowType: 'adset', level: 1,
              id: agId, name: ag.adgroup_name || agId,
              parentId: camp.campaign_id, data: ag,
            })
            if (expandedAdsets.has(agId)) {
              const ads = adCache[agId]
              if (!ads && loadingIds.has(agId)) {
                result.push({ kind: 'status', statusType: 'loading', level: 2, parentId: agId, parentType: 'adset' })
              } else if (!ads && errorIds.has(agId)) {
                result.push({ kind: 'status', statusType: 'error', level: 2, parentId: agId, parentType: 'adset' })
              } else if (ads && ads.length === 0) {
                result.push({ kind: 'status', statusType: 'empty', level: 2, parentId: agId, parentType: 'adset' })
              } else if (ads) {
                for (const ad of ads) {
                  result.push({
                    kind: 'data', rowType: 'ad', level: 2,
                    id: ad.ad_id || '', name: ad.ad_name || ad.ad_id || '',
                    parentId: agId, data: ad,
                  })
                }
              }
            }
          }
        }
      }
    }
    return result
  }, [filteredCampaigns, expandedCampaigns, expandedAdsets, adsetCache, adCache, loadingIds, errorIds])

  const uniqueCampaignIds = useMemo(() => filteredCampaigns.map(c => c.campaign_id), [filteredCampaigns])
  const allSelected = uniqueCampaignIds.length > 0 && uniqueCampaignIds.every(id => selectedIds.has(id))

  const toggleSelectAll = useCallback(() => {
    setSelectedIds(allSelected ? new Set() : new Set(uniqueCampaignIds))
  }, [allSelected, uniqueCampaignIds])

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next })
  }, [])

  const handleSort = useCallback((key: string) => {
    patchFilters({ sort: key, dir: sortKey === key && sortDir === 'desc' ? 'asc' : 'desc', page: null })
  }, [sortKey, sortDir, patchFilters])

  function toggleCol(key: string) {
    const next = visibleCols.includes(key) ? visibleCols.filter(k => k !== key) : [...visibleCols, key]
    handleColChange(next)
  }

  // Insight warnings
  const lowRoiCampaigns = useMemo(() => filteredCampaigns.filter(r => r.roas != null && r.roas > 0 && r.roas < roiThreshold), [filteredCampaigns, roiThreshold])
  const highSpendLowConv = useMemo(() => filteredCampaigns.filter(r => r.total_spend > 100 && r.total_conversions < 5), [filteredCampaigns])
  const noAttrCampaigns = useMemo(() => filteredCampaigns.filter(isMissingAttribution), [filteredCampaigns])
  const overviewMissingAttr = isMissingAttribution({
    total_spend: overview?.total_spend ?? 0,
    attribution_spend: overview?.attribution_spend,
  })

  // Generic meta lookup
  function getEntityMeta(entityId: string, entityType: RowLevel): EntityMeta | undefined {
    if (entityType === 'campaign') return campaignMetaMap?.get(entityId)
    if (entityType === 'adset') return adgroupMetaMap?.get(entityId)
    return adMetaMap?.get(entityId)
  }

  function handleToggleStatus(entityId: string, entityType: RowLevel) {
    const meta = getEntityMeta(entityId, entityType)
    if (!meta || !meta.accountId || !statusLabel(platform, meta.status).canToggle) return
    setActionLoading(entityId)
    const active = isEnabled(platform, meta.status)
    const newStatus = platform === 'tiktok'
      ? (active ? 'DISABLE' : 'ENABLE')
      : (active ? 'PAUSED' : 'ACTIVE')
    toggleMutation.mutate({ entityId, entityType, newStatus, accountId: meta.accountId }, {
      onSettled: () => setActionLoading(null),
    })
  }

  function renderStatusBadge(entityId: string, entityType: RowLevel) {
    const meta = getEntityMeta(entityId, entityType)
    if (!meta) return null
    const sl = statusLabel(platform, meta.status)
    return (
      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold ${
        sl.active ? 'bg-green-50 text-green-600' : 'bg-gray-100 text-gray-400'
      }`}>
        <span className={`w-1.5 h-1.5 rounded-full ${sl.active ? 'bg-green-500' : 'bg-gray-300'}`} />
        {sl.text}
      </span>
    )
  }

  function renderActions(entityId: string, entityType: RowLevel) {
    const meta = getEntityMeta(entityId, entityType)
    if (!meta) return null
    const active = isEnabled(platform, meta.status)
    const isThisLoading = actionLoading === entityId
    return (
      <div className="flex items-center gap-1">
        <button onClick={() => handleToggleStatus(entityId, entityType)} disabled={isThisLoading || toggleMutation.isPending || !meta.accountId || !statusLabel(platform, meta.status).canToggle}
          title={active ? '暂停' : '启动'}
          className={`p-1 rounded-md transition disabled:opacity-40 ${active ? 'text-amber-500 hover:bg-amber-50' : 'text-green-500 hover:bg-green-50'}`}>
          {isThisLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : active ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
        </button>
        {platform === 'tiktok' && (entityType === 'campaign' || entityType === 'adset') && (
          <button onClick={() => setBudgetEdit({ campaignId: entityId, entityType: entityType as 'campaign' | 'adset', budget: meta.budget, accountId: meta.accountId })} title="编辑预算"
            className="p-1 rounded-md text-blue-500 hover:bg-blue-50 transition">
            <Pencil className="w-3.5 h-3.5" />
          </button>
        )}
        {entityType === 'ad' && (
          <Link to={`/creatives?ad=${entityId}`} className="p-1 rounded-md text-gray-400 hover:bg-gray-50 hover:text-blue-500 transition" title="查看素材">
            <ExternalLink className="w-3.5 h-3.5" />
          </Link>
        )}
      </div>
    )
  }

  // ── KPIs ──
  const ov = overview
  const kpis = [
    { label: '总消耗', value: fmtUsd2(ov?.total_spend ?? null), icon: DollarSign },
    { label: '总收入', value: fmtUsd2(ov?.total_revenue ?? null), icon: TrendingUp },
    { label: 'ROI', value: fmtRatio(ov?.avg_roas ?? null), icon: BarChart3, warn: ov?.avg_roas != null && ov.avg_roas < roiThreshold },
    { label: 'CTR', value: fmtPct(ov?.avg_ctr ?? null), icon: MousePointerClick },
    { label: 'CPC', value: fmtUsd2(ov?.avg_cpc ?? null), icon: Target },
    { label: 'CVR', value: ov?.total_clicks ? `${((ov.total_conversions / ov.total_clicks) * 100).toFixed(2)}%` : '-', icon: BarChart3 },
  ]

  const isLoading = ovLoading || campLoading

  // ── Render ──
  return (
    <div className="max-w-[1400px] mx-auto space-y-5">
      {Toast}

      {/* Header */}
      <PageHeader title={title} description={`${platformLabel} 投放数据操作台 — 分层查看 Campaign → Adset → Ad`} />

      {/* 同步状态栏：显示最近同步时间，支持手动刷新 */}
      <GlobalSyncBar />

      {/* Time filter */}
      <FilterBar>
        <DateRangeFilter key={`${dateRange.startDate}:${dateRange.endDate}`} value={dateRange} onChange={handleDateChange} />
        <label className="text-xs text-gray-600 flex items-center gap-2">广告账户
          <select aria-label="广告账户" value={accountId} onChange={e => patchFilters({ account_id: e.target.value, page: null })} className="border border-gray-200 rounded-lg px-3 py-1.5 max-w-72 bg-white">
            <option value="">全部可查询账户</option>
            {accountId && !selectedAccount && <option value={accountId}>账户 {accountId}</option>}
            {accounts.map(account => <option key={account.id} value={account.account_id}>{account.account_name || account.account_id} · {account.account_id}</option>)}
          </select>
        </label>
        <button onClick={refreshAll} className="text-xs text-blue-600 flex items-center gap-1"><RefreshCw className="w-3.5 h-3.5" />刷新数据</button>
      </FilterBar>

      {selectedAccount && <p className="text-xs text-gray-500">当前账户：{selectedAccount.account_name || selectedAccount.account_id} · {selectedAccount.currency} · {selectedAccount.timezone}</p>}
      {(accountsError || overviewError) && <div role="alert" className="text-sm text-red-600">{(accountsError || overviewError)?.message}</div>}
      {/* KPIs */}
      <div className="grid grid-cols-3 lg:grid-cols-6 gap-3">
        {kpis.map(k => (
          <StatCard key={k.label} label={k.label} value={k.value} icon={k.icon}
            className={k.warn ? 'border-red-200 bg-red-50/40' : ''} />
        ))}
      </div>

      {/* Warnings */}
      {(lowRoiCampaigns.length > 0 || highSpendLowConv.length > 0 || noAttrCampaigns.length > 0 || overviewMissingAttr) && (
        <div className="flex flex-wrap gap-3">
          {(noAttrCampaigns.length > 0 || overviewMissingAttr) && (
            <div className="flex items-start gap-2 px-4 py-2.5 bg-orange-50 border border-orange-200 rounded-xl shadow-sm">
              <AlertCircle className="w-4 h-4 text-orange-500 mt-0.5 shrink-0" />
              <div className="flex flex-col">
                <span className="text-xs text-orange-700 font-semibold">
                  {noAttrCampaigns.length > 0
                    ? `${noAttrCampaigns.length} 个 Campaign 无归因数据`
                    : '所选区间整体无归因数据'}
                </span>
                <span className="text-[11px] text-orange-600/80 mt-0.5 leading-relaxed">
                  数仓归因表（dwd_media_stats_rt / dwd_invest_recharge_rt）未覆盖该账号广告事件，
                  收入 / ROI / 注册 / 转化数为 0 不准确，需联系数据团队补采。
                </span>
              </div>
            </div>
          )}
          {lowRoiCampaigns.length > 0 && (
            <div className="flex items-center gap-2 px-4 py-2.5 bg-amber-50 border border-amber-200 rounded-xl shadow-sm">
              <AlertTriangle className="w-4 h-4 text-amber-500" />
              <span className="text-xs text-amber-700 font-medium">{lowRoiCampaigns.length} 个 Campaign ROI &lt; {roiThreshold}</span>
            </div>
          )}
          {highSpendLowConv.length > 0 && (
            <div className="flex items-center gap-2 px-4 py-2.5 bg-red-50 border border-red-200 rounded-xl shadow-sm">
              <AlertCircle className="w-4 h-4 text-red-500" />
              <span className="text-xs text-red-700 font-medium">{highSpendLowConv.length} 个高消耗低转化（消耗&gt;$100 且转化&lt;5）</span>
            </div>
          )}
        </div>
      )}

      {/* Controls bar */}
      <div className="bg-white rounded-xl border border-[var(--color-card-border)] shadow-[var(--shadow-card)] px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-3">
          {/* Total count */}
          <span className="text-xs text-gray-400 shrink-0 tabular-nums">共 {campaignPage?.total ?? 0} 个 Campaign</span>
          <div className="flex-1" />

          {/* Search */}
          <div className="relative shrink-0">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
            <input aria-label="搜索广告系列" value={searchText} onChange={e => setSearchText(e.target.value)} maxLength={200}
              onKeyDown={e => { if (e.key === 'Enter') patchFilters({ q: searchText.trim(), page: null }) }}
              placeholder="系列名称或 ID，回车搜索…"
              className="pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs w-48 bg-gray-50/50 focus:bg-white focus:outline-none focus:border-blue-300 transition" />
          </div>

          <button onClick={() => patchFilters({ q: searchText.trim(), page: null })} className="text-xs text-blue-600">搜索</button>
          {searchFilter && <button onClick={() => patchFilters({ q: null, page: null })} className="text-xs text-gray-500">清除搜索</button>}
          {/* Column picker */}
          <div className="relative shrink-0">
            <button onClick={() => setShowColPicker(!showColPicker)}
              className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 transition bg-gray-50/50">
              <Columns3 className="w-3.5 h-3.5" /> 列
            </button>
            {showColPicker && (
              <div className="absolute top-full right-0 mt-1.5 w-56 bg-white rounded-xl border border-[var(--color-card-border)] shadow-lg z-50 p-3">
                <div className="flex items-center justify-between mb-2.5">
                  <span className="text-xs font-semibold text-gray-700">选择显示列</span>
                  <button onClick={() => setShowColPicker(false)} className="text-gray-400 hover:text-gray-600"><X className="w-3.5 h-3.5" /></button>
                </div>
                <div className="space-y-0.5 max-h-64 overflow-y-auto">
                  {AGG_COLUMNS.map(c => (
                    <label key={c.key} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-50 cursor-pointer">
                      <input type="checkbox" checked={visibleCols.includes(c.key)} onChange={() => toggleCol(c.key)}
                        className="w-3.5 h-3.5 rounded border-gray-300 text-blue-500 focus:ring-blue-500/20" />
                      <span className="text-xs text-gray-600">{c.label}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-400 ml-auto">{c.group}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Batch */}
          {selectedIds.size > 0 && (
            <div className="flex items-center gap-1.5 shrink-0">
              <span className="text-[11px] text-gray-500 font-medium">已选 {selectedIds.size}</span>
              <button onClick={() => batchMutation.mutate(platform === 'tiktok' ? 'ENABLE' : 'ACTIVE')} disabled={batchMutation.isPending}
                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-medium bg-green-50 text-green-600 hover:bg-green-100 transition disabled:opacity-50">
                {batchMutation.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />} 启动
              </button>
              <button onClick={() => batchMutation.mutate(platform === 'tiktok' ? 'DISABLE' : 'PAUSED')} disabled={batchMutation.isPending}
                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-medium bg-amber-50 text-amber-600 hover:bg-amber-100 transition disabled:opacity-50">
                {batchMutation.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Pause className="w-3 h-3" />} 暂停
              </button>
            </div>
          )}

          {/* Create */}
          <button onClick={() => navigate('/ads/create')}
            className="shrink-0 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded-lg font-medium transition flex items-center gap-1.5 shadow-sm">
            <PlusCircle className="w-3.5 h-3.5" /> 新建广告
          </button>
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex items-center justify-center py-32 text-gray-400">
          <Loader2 className="w-6 h-6 animate-spin mr-2" /><span className="text-sm">加载中...</span>
        </div>
      )}

      {/* Error state */}
      {campError && (
        <div className="flex flex-col items-center justify-center py-24 text-red-400">
          <AlertCircle className="w-8 h-8 mb-2" /><p className="text-sm font-medium">{campaignError instanceof Error ? campaignError.message : '数据加载失败'}</p>
          <button onClick={refreshAll} className="mt-3 text-sm underline">重新加载</button>
        </div>
      )}

      {/* Hierarchical table */}
      {!isLoading && !campError && (
        <div className="bg-white rounded-xl border border-[var(--color-card-border)] shadow-[var(--shadow-card)] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50">
                  <th className="px-3 py-3 w-10">
                    <input type="checkbox" checked={allSelected} onChange={toggleSelectAll}
                      className="w-3.5 h-3.5 rounded border-gray-300 text-blue-500 focus:ring-blue-500/20" />
                  </th>
                  <th className="px-4 py-3 text-[11px] font-semibold text-gray-400 uppercase tracking-wider text-left min-w-[280px]">名称</th>
                  {activeCols.map(col => (
                    <th key={col.key} onClick={() => col.sortable !== false && handleSort(col.key)}
                      className={`px-4 py-3 text-[11px] font-semibold text-gray-400 uppercase tracking-wider whitespace-nowrap ${
                        col.align === 'right' ? 'text-right' : 'text-left'
                      } ${col.sortable !== false ? 'cursor-pointer hover:text-gray-600 select-none' : ''}`}>
                      <span className="inline-flex items-center gap-1">
                        {col.label}
                        {col.sortable !== false && sortKey === col.key && <ArrowUpDown className="w-3 h-3 text-blue-500" />}
                      </span>
                    </th>
                  ))}
                  <th className="px-3 py-3 text-[11px] font-semibold text-gray-400 uppercase tracking-wider text-center whitespace-nowrap">状态</th>
                  <th className="px-3 py-3 text-[11px] font-semibold text-gray-400 uppercase tracking-wider text-center whitespace-nowrap">操作</th>
                </tr>
              </thead>
              <tbody>
                {flatRows.length === 0 ? (
                  <tr><td colSpan={activeCols.length + 4} className="px-4 py-14 text-center text-gray-400 text-sm">{searchFilter ? '没有符合搜索条件的广告系列，请修改搜索或日期范围。' : accounts.length === 0 ? '尚未配置广告账户，请先在账户管理中接入。' : '所选范围暂无数据，请检查日期或同步状态。'}</td></tr>
                ) : (
                  flatRows.map((row, idx) => {
                    if (row.kind === 'status') {
                      const bgCls = row.level === 1 ? 'bg-slate-50/70' : 'bg-blue-50/30'
                      const levelLabel = row.parentType === 'campaign' ? 'Adset' : 'Ad'
                      if (row.statusType === 'loading') {
                        return (
                          <tr key={`s-loading-${row.parentId}`} className={bgCls}>
                            <td colSpan={activeCols.length + 4} className="py-3 text-center">
                              <span className="inline-flex items-center gap-2 text-xs text-gray-400">
                                <Loader2 className="w-3.5 h-3.5 animate-spin" /> 加载 {levelLabel} 数据中...
                              </span>
                            </td>
                          </tr>
                        )
                      }
                      if (row.statusType === 'error') {
                        return (
                          <tr key={`s-error-${row.parentId}`} className="bg-red-50/50">
                            <td colSpan={activeCols.length + 4} className="py-3 text-center">
                              <span className="inline-flex items-center gap-2 text-xs text-red-500">
                                <AlertCircle className="w-3.5 h-3.5" /> {childErrors[row.parentId] || '加载失败'}
                                <button onClick={() => retryLoad(row.parentId, row.parentType)}
                                  className="ml-2 inline-flex items-center gap-1 px-2 py-1 rounded bg-red-100 text-red-600 hover:bg-red-200 transition text-[11px] font-medium">
                                  <RefreshCw className="w-3 h-3" /> 重试
                                </button>
                              </span>
                            </td>
                          </tr>
                        )
                      }
                      return (
                        <tr key={`s-empty-${row.parentId}`} className={bgCls}>
                          <td colSpan={activeCols.length + 4} className="py-3 text-center text-xs text-gray-400">
                            该 {row.parentType === 'campaign' ? 'Campaign' : 'Adset'} 下暂无 {levelLabel} 数据
                          </td>
                        </tr>
                      )
                    }

                    const roas = row.data.roas
                    const isLowRoi = roas != null && roas > 0 && roas < roiThreshold
                    const isHighSpend = row.data.total_spend > 100 && row.data.total_conversions < 5
                    const isExpanded = row.rowType === 'campaign'
                      ? expandedCampaigns.has(row.id)
                      : row.rowType === 'adset'
                      ? expandedAdsets.has(row.id)
                      : false
                    const isExpandable = row.rowType !== 'ad'
                    const badge = LEVEL_BADGE[row.rowType]

                    return (
                      <tr key={`${row.rowType}-${row.id}-${idx}`}
                        className={`border-b border-gray-50 last:border-0 transition-colors ${
                          selectedIds.has(row.id) && row.rowType === 'campaign' ? 'bg-blue-50/40 hover:bg-blue-50/60' :
                          isHighSpend && row.rowType === 'campaign' ? 'bg-red-50/40 hover:bg-red-50/60' :
                          isLowRoi && row.rowType === 'campaign' ? 'bg-amber-50/30 hover:bg-amber-50/50' :
                          `hover:bg-blue-50/30 ${LEVEL_BG[row.rowType]}`
                        }`}>
                        {/* Checkbox (campaign only) */}
                        <td className="px-3 py-2.5 w-10">
                          {row.rowType === 'campaign' && (
                            <input type="checkbox" checked={selectedIds.has(row.id)} onChange={() => toggleSelect(row.id)}
                              className="w-3.5 h-3.5 rounded border-gray-300 text-blue-500 focus:ring-blue-500/20" />
                          )}
                        </td>

                        {/* Name col with expand/collapse */}
                        <td className={`py-2.5 ${LEVEL_INDENT[row.level]}`}>
                          <div className="flex items-center gap-2 min-w-0">
                            {isExpandable ? (
                              <button
                                onClick={() => row.rowType === 'campaign' ? toggleCampaign(row.id) : toggleAdset(row.id)}
                                className="shrink-0 w-5 h-5 flex items-center justify-center rounded hover:bg-gray-200/60 transition text-gray-400 hover:text-gray-600"
                              >
                                {loadingIds.has(row.id) ? (
                                  <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-500" />
                                ) : isExpanded ? (
                                  <ChevronDown className="w-3.5 h-3.5" />
                                ) : (
                                  <ChevronRight className="w-3.5 h-3.5" />
                                )}
                              </button>
                            ) : (
                              <span className="shrink-0 w-5" />
                            )}
                            <span className={`shrink-0 px-1.5 py-0.5 rounded text-[9px] font-bold ${badge.cls}`}>
                              {badge.label}
                            </span>
                            <span className={`truncate ${
                              row.rowType === 'campaign' ? 'font-medium text-gray-800 text-sm' :
                              row.rowType === 'adset' ? 'font-normal text-gray-700 text-[13px]' :
                              'font-normal text-gray-500 text-xs'
                            }`} title={row.name}>
                              {row.name}
                            </span>
                            {isMissingAttribution(row.data) && (
                              <span
                                className="shrink-0 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-orange-50 text-orange-600 border border-orange-200 cursor-help"
                                title={
                                  '该' + (row.rowType === 'campaign' ? 'Campaign' : row.rowType === 'adset' ? 'Adset' : 'Ad') +
                                  ` 在所选区间消耗 $${row.data.total_spend.toFixed(2)}，但数仓归因表未采集到任何归因事件（attribution_spend = 0），\n` +
                                  '故此处的"收入 / ROI / 注册 / 转化"为 0 不可信，请联系数据团队检查。'
                                }
                              >
                                <AlertCircle className="w-3 h-3" />
                                无归因
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Metric columns */}
                        {activeCols.map(col => (
                          <td key={col.key}
                            className={`px-4 py-2.5 text-sm tabular-nums ${col.align === 'right' ? 'text-right' : 'text-left'} ${
                              col.key === 'roas' && isLowRoi ? 'text-red-600 font-semibold' :
                              col.key === 'total_spend' && isHighSpend ? 'text-red-600 font-semibold' :
                              row.rowType === 'ad' ? 'text-gray-500 text-xs' :
                              row.rowType === 'adset' ? 'text-gray-600 text-[13px]' :
                              'text-gray-600'
                            }`}>
                            {col.format(row.data[col.key as keyof AggRow] as number | null)}
                          </td>
                        ))}

                        {/* Status */}
                        <td className="px-3 py-2.5 text-center">
                          {renderStatusBadge(row.id, row.rowType)}
                        </td>

                        {/* Actions */}
                        <td className="px-3 py-2.5">
                          {renderActions(row.id, row.rowType)}
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {campaignPage && campaignPage.total > 50 && <div className="flex items-center justify-end gap-3 text-xs text-gray-600">
        <span>第 {campaignPage.page} / {Math.ceil(campaignPage.total / 50)} 页 · 每页 50 条</span>
        <button disabled={campaignPage.page <= 1} onClick={() => patchFilters({ page: String(campaignPage.page - 1) })} className="px-3 py-1.5 border rounded disabled:opacity-40">上一页</button>
        <button disabled={campaignPage.page * 50 >= campaignPage.total} onClick={() => patchFilters({ page: String(campaignPage.page + 1) })} className="px-3 py-1.5 border rounded disabled:opacity-40">下一页</button>
      </div>}
      {batchResults.length > 0 && <div role="status" className="border rounded-xl p-4 text-xs space-y-1">
        <p className="font-medium">批量操作结果：成功 {batchResults.filter(r => !r.error).length} 个，失败 {batchResults.filter(r => r.error).length} 个</p>
        {batchResults.filter(r => r.error).map(result => <p key={result.id} className="text-red-600">{result.id}：{result.error}</p>)}
        {batchResults.some(r => r.error) && <p className="text-gray-500">已保留失败项的选择，可再次执行以重试失败项。</p>}
      </div>}
      {/* Budget modal */}
      {budgetEdit && (
        <BudgetModal currentBudget={budgetEdit.budget} saving={budgetMutation.isPending}
          onClose={() => setBudgetEdit(null)}
          onSave={budget => budgetMutation.mutate({ entityId: budgetEdit.campaignId, entityType: budgetEdit.entityType, budget, accountId: budgetEdit.accountId })} />
      )}
    </div>
  )
}
