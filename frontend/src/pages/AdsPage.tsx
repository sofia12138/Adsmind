import { useState, useMemo } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { StatCard } from '@/components/common/StatCard'
import { FilterBar } from '@/components/common/FilterBar'
import { DataTable, type Column } from '@/components/common/DataTable'
import { DateRangeFilter, getDefaultDateRange, type DateRange } from '@/components/common/DateRangeFilter'
import { DollarSign, TrendingUp, BarChart3, Loader2, AlertCircle, PlusCircle, Monitor } from 'lucide-react'
import { useBizOverview, useBizTopCampaigns } from '@/hooks/use-biz'
import { useInsightConfig } from '@/hooks/use-insight'
import type { BizTopCampaign } from '@/services/biz'

const fmtUsd = (n: number | null | undefined) => `$${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const platformLabel: Record<string, string> = { tiktok: 'TikTok', meta: 'Meta' }

interface ChannelSummary {
  platform: string
  spend: number
  revenue: number
  roas: number
  campaigns: number
  topCampaigns: BizTopCampaign[]
}

export default function AdsPage() {
  const navigate = useNavigate()
  const [dateRange, setDateRange] = useState<DateRange>(() => getDefaultDateRange('all'))

  const { data: ovAll, isLoading: ovAllL } = useBizOverview(dateRange)
  const { data: ovTT } = useBizOverview({ ...dateRange, platform: 'tiktok' })
  const { data: ovMeta } = useBizOverview({ ...dateRange, platform: 'meta' })
  const { data: topTT } = useBizTopCampaigns({ ...dateRange, platform: 'tiktok', limit: 5 })
  const { data: topMeta } = useBizTopCampaigns({ ...dateRange, platform: 'meta', limit: 5 })
  const { data: insightCfg } = useInsightConfig()

  const roiThreshold = insightCfg?.roi?.low ?? 1.5

  const channels = useMemo<ChannelSummary[]>(() => {
    const list: ChannelSummary[] = []
    if (ovTT) list.push({
      platform: 'tiktok', spend: ovTT.total_spend ?? 0, revenue: ovTT.total_revenue ?? 0,
      roas: ovTT.avg_roas ?? 0, campaigns: topTT?.length ?? 0, topCampaigns: topTT ?? [],
    })
    if (ovMeta) list.push({
      platform: 'meta', spend: ovMeta.total_spend ?? 0, revenue: ovMeta.total_revenue ?? 0,
      roas: ovMeta.avg_roas ?? 0, campaigns: topMeta?.length ?? 0, topCampaigns: topMeta ?? [],
    })
    return list
  }, [ovTT, ovMeta, topTT, topMeta])

  const totalSpend = ovAll?.total_spend ?? 0
  const totalRevenue = ovAll?.total_revenue ?? 0
  const totalRoas = ovAll?.avg_roas ?? 0

  const topColumns: Column<BizTopCampaign>[] = [
    { key: 'campaign_name', title: 'Campaign', render: (r) => (
      <span className="font-medium text-gray-800 text-xs">{r.campaign_name || r.campaign_id}</span>
    )},
    { key: 'total_spend', title: '消耗', align: 'right', render: (r) => <span className="text-xs tabular-nums">{fmtUsd(r.total_spend)}</span> },
    { key: 'total_revenue', title: '收入', align: 'right', render: (r) => <span className="text-xs tabular-nums">{fmtUsd(r.total_revenue)}</span> },
    { key: 'avg_roas', title: 'ROAS', align: 'right', render: (r) => (
      <span className={`text-xs font-medium tabular-nums ${r.avg_roas != null && r.avg_roas < roiThreshold && r.avg_roas > 0 ? 'text-red-600' : ''}`}>
        {r.avg_roas != null ? r.avg_roas.toFixed(2) : '-'}
      </span>
    )},
  ]

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <PageHeader title="广告数据" description="跨渠道数据总览，快速对比 TikTok 与 Meta 整体表现"
        action={
          <button onClick={() => navigate('/ads/create')}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded-lg font-medium transition flex items-center gap-1.5 shadow-sm">
            <PlusCircle className="w-3.5 h-3.5" /> 新建广告
          </button>
        }
      />

      {/* ===== 筛选区 ===== */}
      <FilterBar>
        <DateRangeFilter value={dateRange} onChange={setDateRange} />
      </FilterBar>

      {ovAllL ? (
        <div className="flex items-center justify-center py-20 text-gray-400">
          <Loader2 className="w-6 h-6 animate-spin mr-2" /><span className="text-sm">加载中...</span>
        </div>
      ) : (
        <>
          {/* ===== 指标区 ===== */}
          <div className="grid grid-cols-3 gap-4">
            <StatCard label="总消耗" value={fmtUsd(totalSpend)} icon={DollarSign} />
            <StatCard label="总收入" value={fmtUsd(totalRevenue)} icon={TrendingUp} />
            <StatCard label="整体 ROAS" value={totalRoas > 0 ? totalRoas.toFixed(2) : '-'} icon={BarChart3}
              className={totalRoas > 0 && totalRoas < roiThreshold ? 'border-red-200 bg-red-50/40' : ''} />
          </div>

          {/* ===== 渠道卡片 ===== */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {channels.map(ch => {
              const pct = totalSpend > 0 ? ((ch.spend / totalSpend) * 100).toFixed(1) : '0'
              const consolePath = ch.platform === 'tiktok' ? '/console/tiktok' : '/console/meta'
              return (
                <div key={ch.platform} className="bg-white rounded-xl border border-[var(--color-card-border)] shadow-[var(--shadow-card)] p-5">
                  {/* 渠道头部 */}
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2.5">
                      <span className={`inline-block px-2.5 py-1 rounded-lg text-xs font-semibold ${
                        ch.platform === 'tiktok' ? 'bg-sky-50 text-sky-600' : 'bg-indigo-50 text-indigo-600'
                      }`}>{platformLabel[ch.platform]}</span>
                      <span className="text-xs text-gray-400">消耗占比 {pct}%</span>
                    </div>
                    <Link to={consolePath} className="flex items-center gap-1 text-xs text-blue-500 hover:text-blue-700 font-medium transition">
                      <Monitor className="w-3.5 h-3.5" /> 操作台
                    </Link>
                  </div>

                  {/* 指标 */}
                  <div className="grid grid-cols-3 gap-4 mb-4">
                    <div className="bg-gray-50/80 rounded-lg px-3 py-2.5">
                      <p className="text-[11px] text-gray-400 mb-1">消耗</p>
                      <p className="text-sm font-bold text-gray-800 tabular-nums">{fmtUsd(ch.spend)}</p>
                    </div>
                    <div className="bg-gray-50/80 rounded-lg px-3 py-2.5">
                      <p className="text-[11px] text-gray-400 mb-1">收入</p>
                      <p className="text-sm font-bold text-green-700 tabular-nums">{fmtUsd(ch.revenue)}</p>
                    </div>
                    <div className="bg-gray-50/80 rounded-lg px-3 py-2.5">
                      <p className="text-[11px] text-gray-400 mb-1">ROAS</p>
                      <p className={`text-sm font-bold tabular-nums ${ch.roas > 0 && ch.roas < roiThreshold ? 'text-red-600' : 'text-gray-800'}`}>
                        {ch.roas > 0 ? ch.roas.toFixed(2) : '-'}
                      </p>
                    </div>
                  </div>

                  {/* 占比条 */}
                  <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden mb-4">
                    <div className={`h-full rounded-full transition-all ${ch.platform === 'tiktok' ? 'bg-sky-400' : 'bg-indigo-400'}`} style={{ width: `${pct}%` }} />
                  </div>

                  {/* Top Campaign */}
                  {ch.topCampaigns.length > 0 && (
                    <div>
                      <p className="text-[11px] font-medium text-gray-400 uppercase tracking-wide mb-2">Top Campaign</p>
                      <DataTable columns={topColumns} data={ch.topCampaigns.slice(0, 3)} rowKey={r => r.campaign_id} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {channels.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-gray-400">
              <AlertCircle className="w-10 h-10 mb-2" strokeWidth={1.2} /><p className="text-sm">暂无渠道数据</p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
