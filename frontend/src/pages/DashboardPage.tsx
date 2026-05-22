import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { DollarSign, TrendingUp, BarChart3, MousePointerClick, UserPlus, Megaphone, Image as ImageIcon, Loader2, AlertCircle } from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { StatCard } from '@/components/common/StatCard'
import { SectionCard } from '@/components/common/SectionCard'
import { LinkCard } from '@/components/common/LinkCard'
import { FilterBar } from '@/components/common/FilterBar'
import { DateRangeFilter, getDefaultDateRange, type DateRange } from '@/components/common/DateRangeFilter'
import { OnboardingChecklist } from '@/components/common/OnboardingChecklist'
import { useBizOverview, useBizTopCampaigns, useCampaignDaily } from '@/hooks/use-biz'
import { SpendRevenueTrendChart } from '@/components/charts/SpendRevenueTrendChart'
import { useInsightConfig } from '@/hooks/use-insight'
import { useAuth } from '@/contexts/AuthContext'

const fmtUsd = (n: number) => `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export default function DashboardPage() {
  const [dateRange, setDateRange] = useState<DateRange>(() => getDefaultDateRange('all'))
  const { currentApplication } = useAuth()

  const { data: overview, isLoading: ovLoading, isError: ovError } = useBizOverview(dateRange)
  const { data: topCampaigns } = useBizTopCampaigns({ ...dateRange, limit: 50 })
  const { data: dailyData, isLoading: dailyLoading } = useCampaignDaily({ ...dateRange, page_size: 200 })
  const { data: insightCfg } = useInsightConfig()

  const roiThreshold = insightCfg?.roi?.low ?? 1.5

  const alerts = useMemo(() =>
    (topCampaigns ?? [])
      .filter(c => c.avg_roas !== null && c.avg_roas > 0 && c.avg_roas < roiThreshold)
      .slice(0, 5),
    [topCampaigns, roiThreshold],
  )

  const isLoading = ovLoading
  const hasData = overview && overview.total_spend > 0
  // 阶段 4 Onboarding：后端返回 _hint 表示当前应用未绑账号 / 多账号未指定；
  // 此时优先展示 3 步引导卡片，引导客户完成接入。
  const showOnboarding = !isLoading && !ovError && !!overview?._hint

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <PageHeader title="首页概览" description="10 秒判断今日投放状态" />

      {/* ===== 筛选区 ===== */}
      <FilterBar>
        <DateRangeFilter value={dateRange} onChange={setDateRange} />
      </FilterBar>

      {isLoading && (
        <div className="flex items-center justify-center py-32 text-gray-400">
          <Loader2 className="w-6 h-6 animate-spin mr-2" />
          <span className="text-sm">加载中...</span>
        </div>
      )}

      {ovError && (
        <div className="flex flex-col items-center justify-center py-24 text-red-400">
          <AlertCircle className="w-8 h-8 mb-2" />
          <p className="text-sm font-medium">数据加载失败</p>
        </div>
      )}

      {showOnboarding && (
        <OnboardingChecklist
          applicationId={currentApplication?.id}
          applicationName={currentApplication?.name}
          hint={overview?._hint}
        />
      )}

      {!isLoading && !ovError && !showOnboarding && (
        <>
          {/* ===== 指标区 ===== */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            <StatCard label="总消耗" value={hasData ? fmtUsd(overview.total_spend) : '-'} icon={DollarSign} href="/overview" />
            <StatCard label="总收入" value={hasData ? fmtUsd(overview.total_revenue) : '-'} icon={TrendingUp} href="/overview" />
            <StatCard
              label="ROAS"
              value={hasData && overview.avg_roas ? overview.avg_roas.toFixed(2) : '-'}
              icon={BarChart3}
              className={overview?.avg_roas != null && overview.avg_roas < roiThreshold ? 'border-red-200 bg-red-50/40' : ''}
              href="/overview"
            />
            <StatCard label="点击数" value={hasData ? overview.total_clicks.toLocaleString() : '-'} icon={MousePointerClick} href="/ads" />
            <StatCard label="注册数" value={hasData ? (overview.total_registrations ?? 0).toLocaleString() : '-'} icon={UserPlus} href="/ads" />
          </div>

          {/* ===== 图表 + 异常提醒 ===== */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <SectionCard title="消耗 & 收入趋势" className="lg:col-span-2">
              <SpendRevenueTrendChart data={dailyData?.list ?? []} loading={dailyLoading} />
            </SectionCard>

            <SectionCard
              title="异常提醒"
              extra={alerts.length > 0
                ? <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-red-50 text-red-500">{alerts.length} 条</span>
                : <span className="text-gray-400 text-xs">无异常</span>}
              noPadding
            >
              {alerts.length === 0 ? (
                <div className="px-5 py-10 text-center text-sm text-gray-300">
                  当前无低 ROAS 广告
                </div>
              ) : (
                <div className="divide-y divide-gray-100/80">
                  {alerts.map(a => (
                    <Link
                      key={a.campaign_id}
                      to={`/ads?platform=${a.platform}`}
                      className="px-5 py-3.5 flex items-center gap-3 hover:bg-gray-50/80 transition-colors"
                    >
                      <span className="w-2 h-2 rounded-full shrink-0 bg-red-400" />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-800 truncate">{a.campaign_name || a.campaign_id}</p>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {a.platform} · ROAS {a.avg_roas?.toFixed(2)}
                          <span className="text-gray-300 ml-1">| 阈值 &lt; {roiThreshold}</span>
                        </p>
                      </div>
                      <span className="shrink-0 inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold bg-red-50 text-red-600">
                        低 ROAS
                      </span>
                    </Link>
                  ))}
                </div>
              )}
            </SectionCard>
          </div>
        </>
      )}

      {/* ===== 快捷入口 ===== */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <LinkCard to="/ads" icon={Megaphone} title="广告数据" description="查看全渠道 Campaign 数据与异常" />
        <LinkCard to="/overview" icon={BarChart3} title="数据总览" description="查看消耗、收入与 ROI 趋势变化" />
        <LinkCard to="/creatives" icon={ImageIcon} title="素材中心" description="分析素材表现，发现爆款素材" />
      </div>
    </div>
  )
}
