/**
 * DramaOverviewPage.tsx — 剧级分析总览页
 *
 * 功能：
 *  - 按 content_key 聚合展示剧级总览数据
 *  - 每行支持展开查看各语言版本（locale breakdown）
 *  - 支持 keyword / language_code / source_type / platform / country 筛选
 *  - 支持手动触发剧级数据同步
 *
 * 核心约束（与解析器保持一致）：
 *  - keyword 只搜索 localized_drama_name，不搜索 remark_raw
 *  - 同一部剧不同语言版本聚合在一行，language_count 显示版本数
 */

import React, { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Search,
  Film,
  DollarSign,
  MousePointerClick,
  UserPlus,
  Star,
  Languages,
  User,
} from 'lucide-react'

import { PageHeader } from '@/components/common/PageHeader'
import { StatCard } from '@/components/common/StatCard'
import { DateRangeFilter, getDefaultDateRange } from '@/components/common/DateRangeFilter'
import type { DateRange } from '@/components/common/DateRangeFilter'
import { FilterBar } from '@/components/common/FilterBar'
import { GlobalSyncBar } from '@/components/common/GlobalSyncBar'

import {
  fetchDramaSummary,
  fetchLocaleBreakdown,
  triggerDramaSync,
  type DramaSummaryRow,
  type LocaleBreakdownRow,
} from '@/services/drama'
import { fetchDirectoryList } from '@/services/optimizer-directory'

const UNKNOWN_OPTIMIZER = '未识别'

// ─────────────────────────────────────────────────────────────
// 工具函数
// ─────────────────────────────────────────────────────────────

function fmtUsd(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`
  return `$${v.toFixed(2)}`
}

function fmtNum(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`
  return String(v)
}

function fmtRoas(v: number): string {
  return `${v.toFixed(2)}x`
}

const LANG_LABEL: Record<string, string> = {
  en: 'English',
  es: 'Español',
  pt: 'Português',
  fr: 'Français',
  de: 'Deutsch',
  id: 'Bahasa ID',
  th: 'ภาษาไทย',
  ja: '日本語',
  ko: '한국어',
  ar: 'العربية',
  unknown: '未知',
}

// ─────────────────────────────────────────────────────────────
// 语言版本展开行
// ─────────────────────────────────────────────────────────────

function LocaleRows({
  contentKey,
  dateRange,
  colSpan,
  optimizer,
}: {
  contentKey: string
  dateRange: DateRange
  colSpan: number
  /** 与主表保持同口径 — 不传则后端不过滤 */
  optimizer?: string
}) {
  const { data, isLoading } = useQuery({
    queryKey: [
      'drama-locale',
      contentKey,
      dateRange.startDate,
      dateRange.endDate,
      optimizer ?? '',
    ],
    queryFn: () =>
      fetchLocaleBreakdown({
        startDate: dateRange.startDate,
        endDate: dateRange.endDate,
        contentKey,
        optimizer: optimizer || undefined,
      }),
    staleTime: 60_000,
  })

  if (isLoading) {
    return (
      <tr>
        <td colSpan={colSpan} className="px-4 py-3 text-center text-xs text-gray-400">
          加载中…
        </td>
      </tr>
    )
  }

  const rows = data?.rows ?? []
  if (rows.length === 0) {
    return (
      <tr>
        <td colSpan={colSpan} className="px-4 py-3 text-center text-xs text-gray-400">
          暂无语言版本数据
        </td>
      </tr>
    )
  }

  return (
    <>
      {rows.map((r: LocaleBreakdownRow) => (
        <tr key={r.language_code} className="bg-blue-50/40 border-b border-blue-100/60">
          {/* 缩进 + 语言标识 */}
          <td className="pl-12 pr-4 py-2.5">
            <div className="flex items-center gap-2">
              <Languages className="w-3.5 h-3.5 text-blue-400 shrink-0" />
              <span className="text-xs font-semibold text-blue-700 uppercase tracking-wide">
                {r.language_code}
              </span>
              <span className="text-xs text-gray-400">
                {LANG_LABEL[r.language_code] ?? r.language_code}
              </span>
            </div>
            <div className="text-xs text-gray-500 mt-0.5 pl-5 line-clamp-1">
              {r.localized_drama_name}
            </div>
          </td>
          {/* 指标列 */}
          <td className="px-4 py-2.5 text-right text-xs text-gray-700">{fmtUsd(r.spend)}</td>
          <td className="px-4 py-2.5 text-right text-xs text-gray-500">—</td>
          <td className="px-4 py-2.5 text-right text-xs text-gray-700">{fmtNum(r.clicks)}</td>
          <td className="px-4 py-2.5 text-right text-xs text-gray-700">{fmtNum(r.registrations)}</td>
          <td className="px-4 py-2.5 text-right text-xs text-gray-700">{fmtUsd(r.purchase_value)}</td>
          <td className="px-4 py-2.5 text-right text-xs font-medium text-emerald-600">
            {fmtRoas(r.roas)}
          </td>
          <td className="px-4 py-2.5 text-right text-xs text-gray-400">—</td>
        </tr>
      ))}
    </>
  )
}

// ─────────────────────────────────────────────────────────────
// 主页面
// ─────────────────────────────────────────────────────────────

export default function DramaOverviewPage() {
  const queryClient = useQueryClient()

  // 日期
  const [dateRange, setDateRange] = useState<DateRange>(getDefaultDateRange('7d'))

  // 筛选
  const [keyword, setKeyword] = useState('')
  const [sourceType, setSourceType] = useState('')
  const [platform, setPlatform] = useState('')
  const [country, _setCountry] = useState('')
  const [languageCode, setLanguageCode] = useState('')
  // 优化师筛选 — 空字符串=全部；'未识别' 表示未匹配的 campaign
  const [optimizer, setOptimizer] = useState('')

  // 展开状态（content_key set）
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  // 翻页
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 30

  const toggleExpand = useCallback((key: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  // ── 优化师下拉 ─────────────────────────────────────────────
  // 直接拉全量目录（按方案：1.直接拉全量）。is_active=1 过滤掉已停用的优化师。
  const { data: optimizerDirectory } = useQuery({
    queryKey: ['optimizer-directory-active'],
    queryFn: () => fetchDirectoryList({ is_active: 1 }),
    staleTime: 5 * 60_000, // 目录变化频率低，缓存 5 分钟
  })

  // ── 主查询 ─────────────────────────────────────────────────
  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: [
      'drama-summary',
      dateRange.startDate, dateRange.endDate,
      sourceType, platform, country, languageCode, keyword, optimizer, page,
    ],
    queryFn: () =>
      fetchDramaSummary({
        startDate: dateRange.startDate,
        endDate: dateRange.endDate,
        sourceType: sourceType || undefined,
        platform: platform || undefined,
        country: country || undefined,
        languageCode: languageCode || undefined,
        keyword: keyword || undefined,
        optimizer: optimizer || undefined,
        page,
        pageSize: PAGE_SIZE,
      }),
    staleTime: 60_000,
  })

  const rows: DramaSummaryRow[] = data?.rows ?? []
  const total = data?.total ?? 0

  // ── 汇总统计 ───────────────────────────────────────────────
  const totalSpend = rows.reduce((s, r) => s + r.spend, 0)
  const totalClicks = rows.reduce((s, r) => s + r.clicks, 0)
  const totalRegistrations = rows.reduce((s, r) => s + (r.registrations ?? 0), 0)
  const totalPurchase = rows.reduce((s, r) => s + r.purchase_value, 0)

  // ── 手动同步 ───────────────────────────────────────────────
  const syncMutation = useMutation({
    mutationFn: () => triggerDramaSync(dateRange.startDate, dateRange.endDate),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['drama-summary'] })
      queryClient.invalidateQueries({ queryKey: ['drama-locale'] })
    },
  })

  const handleSearch = () => {
    setPage(1)
    refetch()
  }

  // ── 总页数 ─────────────────────────────────────────────────
  const totalPages = Math.ceil(total / PAGE_SIZE)

  // ── 列数（含展开箭头列）─────────────────────────────────────
  const COL_COUNT = 8

  return (
    <div className="max-w-[1400px] mx-auto space-y-5">
      {/* 页头 */}
      <PageHeader
        title="剧级分析"
        description="按剧集内容聚合广告投放数据，支持语言版本展开 — 剧名来自活动名称第10字段"
      />

      {/* 全局同步状态 */}
      <GlobalSyncBar />

      {/* 筛选栏 */}
      <FilterBar>
        <DateRangeFilter value={dateRange} onChange={v => { setDateRange(v); setPage(1) }} />

        {/* 关键词搜索（仅匹配 localized_drama_name） */}
        <div className="flex items-center gap-1.5 border border-gray-200 rounded-lg px-3 py-1.5 bg-white">
          <Search className="w-3.5 h-3.5 text-gray-400 shrink-0" />
          <input
            type="text"
            placeholder="搜索剧名…"
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            className="text-sm outline-none placeholder:text-gray-300 w-40"
          />
        </div>

        {/* 来源类型 */}
        <select
          value={sourceType}
          onChange={e => { setSourceType(e.target.value); setPage(1) }}
          className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white outline-none text-gray-700"
        >
          <option value="">全部来源</option>
          <option value="小程序">小程序</option>
          <option value="APP">APP</option>
        </select>

        {/* 平台 */}
        <select
          value={platform}
          onChange={e => { setPlatform(e.target.value); setPage(1) }}
          className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white outline-none text-gray-700"
        >
          <option value="">全部平台</option>
          <option value="tiktok">TikTok</option>
          <option value="meta">Meta</option>
        </select>

        {/* 语言版本筛选 */}
        <select
          value={languageCode}
          onChange={e => { setLanguageCode(e.target.value); setPage(1) }}
          className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white outline-none text-gray-700"
        >
          <option value="">全部语言</option>
          {Object.entries(LANG_LABEL).filter(([k]) => k !== 'unknown').map(([k, label]) => (
            <option key={k} value={k}>{k.toUpperCase()} · {label}</option>
          ))}
          <option value="unknown">未知语言</option>
        </select>

        {/* 优化师筛选 */}
        <div className="flex items-center gap-1.5">
          <User className="w-3.5 h-3.5 text-gray-400 shrink-0" />
          <select
            value={optimizer}
            onChange={e => { setOptimizer(e.target.value); setPage(1) }}
            className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white outline-none text-gray-700 min-w-[140px]"
            title="按优化师 normalized 名筛选"
          >
            <option value="">全部优化师</option>
            {(optimizerDirectory ?? [])
              .slice()
              .sort((a, b) => a.optimizer_name.localeCompare(b.optimizer_name))
              .map(item => (
                <option key={item.id} value={item.optimizer_name}>
                  {item.optimizer_name}
                  {item.optimizer_code ? ` · ${item.optimizer_code}` : ''}
                </option>
              ))}
            <option value={UNKNOWN_OPTIMIZER}>{UNKNOWN_OPTIMIZER}</option>
          </select>
        </div>

        {/* 手动同步按钮 */}
        <button
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
          className="flex items-center gap-1.5 text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white text-gray-600 hover:bg-gray-50 disabled:opacity-50 ml-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${syncMutation.isPending ? 'animate-spin' : ''}`} />
          {syncMutation.isPending ? '同步中…' : '同步数据'}
        </button>
      </FilterBar>

      {/* 同步结果提示 */}
      {syncMutation.isSuccess && (
        <div className="text-xs text-emerald-600 bg-emerald-50 border border-emerald-100 rounded-lg px-4 py-2 space-y-1">
          <div>
            剧级同步完成：映射写入 {syncMutation.data.mapping_upserted} 条，事实表写入{' '}
            {syncMutation.data.fact_upserted} 条，解析失败 {syncMutation.data.failed_count} 条
          </div>
          {syncMutation.data.optimizer_sync && (
            syncMutation.data.optimizer_sync.error ? (
              <div className="text-amber-700">
                优化师同步失败：{syncMutation.data.optimizer_sync.error}
              </div>
            ) : (
              <div className="text-emerald-600/80">
                优化师同步：映射 {syncMutation.data.optimizer_sync.mapping_upserted ?? 0} 条 · 事实表{' '}
                {syncMutation.data.optimizer_sync.fact_upserted ?? 0} 条 · 未识别{' '}
                {syncMutation.data.optimizer_sync.failed_count ?? 0} 条
              </div>
            )
          )}
        </div>
      )}

      {/* KPI 卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="总花费" value={fmtUsd(totalSpend)} icon={DollarSign} />
        <StatCard label="总点击" value={fmtNum(totalClicks)} icon={MousePointerClick} />
        <StatCard label="总注册" value={fmtNum(totalRegistrations)} icon={UserPlus} />
        <StatCard label="总收入" value={fmtUsd(totalPurchase)} icon={Star} />
      </div>

      {/* 主表格 */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100">
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <Film className="w-4 h-4 text-gray-400" />
            <span className="font-medium">剧集列表</span>
            <span className="text-gray-400 text-xs">共 {total} 部剧</span>
            {isFetching && <span className="text-xs text-blue-400 animate-pulse">刷新中…</span>}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
                <th className="text-left px-4 py-3 min-w-[280px]">剧名</th>
                <th className="text-right px-4 py-3">花费</th>
                <th className="text-right px-4 py-3">展示</th>
                <th className="text-right px-4 py-3">点击</th>
                <th className="text-right px-4 py-3">注册</th>
                <th className="text-right px-4 py-3">收入</th>
                <th className="text-right px-4 py-3">ROAS</th>
                <th className="text-right px-4 py-3 min-w-[80px]">语言版本</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-gray-100">
              {isLoading && (
                <tr>
                  <td colSpan={COL_COUNT} className="px-4 py-8 text-center text-gray-400 text-sm">
                    加载中…
                  </td>
                </tr>
              )}

              {!isLoading && rows.length === 0 && (
                <tr>
                  <td colSpan={COL_COUNT} className="px-4 py-8 text-center text-gray-400 text-sm">
                    暂无数据，请尝试先同步或调整筛选条件
                  </td>
                </tr>
              )}

              {rows.map((row) => {
                const isOpen = expanded.has(row.content_key)
                return (
                  <React.Fragment key={row.content_key}>
                    {/* 剧级主行 */}
                    <tr
                      className="hover:bg-gray-50/60 cursor-pointer"
                      onClick={() => toggleExpand(row.content_key)}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-start gap-2">
                          {/* 展开箭头 */}
                          <button className="mt-0.5 shrink-0 text-gray-400 hover:text-gray-600">
                            {isOpen ? (
                              <ChevronDown className="w-4 h-4" />
                            ) : (
                              <ChevronRight className="w-4 h-4" />
                            )}
                          </button>
                          <div>
                            <div className="font-medium text-gray-800 line-clamp-2 break-words leading-snug">
                              {row.localized_drama_name || '(未知剧名)'}
                            </div>
                            <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                              {row.drama_id && (
                                <span className="text-xs text-gray-400">ID: {row.drama_id}</span>
                              )}
                              {row.drama_type && (
                                <span className="text-xs bg-gray-100 text-gray-500 rounded px-1.5 py-0.5">
                                  {row.drama_type}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right font-medium text-gray-800">
                        {fmtUsd(row.spend)}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-500">
                        {fmtNum(row.impressions)}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-700">
                        {fmtNum(row.clicks)}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-700">
                        {fmtNum(row.registrations)}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-700">
                        {fmtUsd(row.purchase_value)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span
                          className={`font-semibold ${
                            row.roas >= 1.2
                              ? 'text-emerald-600'
                              : row.roas >= 0.8
                              ? 'text-yellow-600'
                              : 'text-red-500'
                          }`}
                        >
                          {fmtRoas(row.roas)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className="inline-flex items-center gap-1 text-xs bg-blue-50 text-blue-600 rounded-full px-2 py-0.5">
                          <Languages className="w-3 h-3" />
                          {row.language_count}
                        </span>
                      </td>
                    </tr>

                    {/* 展开语言版本子行 */}
                    {isOpen && (
                      <LocaleRows
                        key={`locale-${row.content_key}`}
                        contentKey={row.content_key}
                        dateRange={dateRange}
                        colSpan={COL_COUNT}
                        optimizer={optimizer || undefined}
                      />
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-gray-100 text-sm text-gray-500">
            <span>第 {page} / {totalPages} 页，共 {total} 条</span>
            <div className="flex gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage(p => p - 1)}
                className="px-3 py-1 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40"
              >
                上一页
              </button>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(p => p + 1)}
                className="px-3 py-1 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
