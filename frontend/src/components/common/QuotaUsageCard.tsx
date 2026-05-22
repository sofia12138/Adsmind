/**
 * 阶段 7 配额限流卡片：展示当前租户的套餐 + 已用 / 上限 + 进度条。
 *
 * 使用场景：
 *  - ApplicationsListPage 顶部：让用户实时看到自己的应用 / 账号配额
 *  - 后续也可以放到 Settings 页 / Topbar 下拉里
 *
 * Internal tenant：不展示（is_internal=true 时直接返回 null，避免内部员工看到"无限"卡）
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Crown, AlertCircle, Sparkles } from 'lucide-react'
import { getMyQuota, type QuotaUsage } from '@/services/quota'
import { UpgradePlanDialog } from '@/components/common/UpgradePlanDialog'
import { cn } from '@/utils/cn'

interface MetricRowProps {
  label: string
  used: number
  limit: number
  exhausted: boolean
}

function MetricRow({ label, used, limit, exhausted }: MetricRowProps) {
  const ratio = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0
  const barColor = exhausted
    ? 'bg-red-500'
    : ratio > 80
    ? 'bg-amber-500'
    : 'bg-blue-500'
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-xs text-gray-500">{label}</span>
        <span className={cn(
          'text-xs font-medium tabular-nums',
          exhausted ? 'text-red-600' : 'text-gray-700',
        )}>
          {used} / {limit}
        </span>
      </div>
      <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={cn('h-full transition-all', barColor)}
             style={{ width: `${ratio}%` }} />
      </div>
    </div>
  )
}

export function QuotaUsageCard({ compact = false }: { compact?: boolean } = {}) {
  const [upgradeOpen, setUpgradeOpen] = useState(false)
  const { data, isLoading, isError } = useQuery<QuotaUsage>({
    queryKey: ['quota', 'me'],
    queryFn: getMyQuota,
    staleTime: 30_000,
  })

  if (isLoading) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white px-5 py-4 text-xs text-gray-400">
        加载配额信息…
      </div>
    )
  }
  if (isError || !data) return null
  if (data.is_internal) return null  // 内部租户不展示

  const anyExhausted =
    data.exhausted.applications || data.exhausted.accounts

  return (
    <div className={cn(
      'rounded-xl border bg-gradient-to-br shadow-sm',
      anyExhausted
        ? 'from-amber-50 to-orange-50 border-amber-200'
        : 'from-blue-50 to-indigo-50 border-blue-100',
      compact ? 'px-4 py-3' : 'px-5 py-4',
    )}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2 shrink-0">
          <div className={cn(
            'w-9 h-9 rounded-lg flex items-center justify-center',
            anyExhausted ? 'bg-amber-500/15 text-amber-600' : 'bg-blue-500/15 text-blue-600',
          )}>
            <Crown className="w-4.5 h-4.5" />
          </div>
          <div>
            <div className="text-[11px] text-gray-500 uppercase tracking-wider">当前套餐</div>
            <div className="text-base font-semibold text-gray-900">{data.plan_name}</div>
          </div>
        </div>

        <div className="flex-1 min-w-0 grid grid-cols-1 md:grid-cols-3 gap-x-6 gap-y-2">
          <MetricRow
            label="应用数"
            used={data.usage.applications}
            limit={data.limits.applications}
            exhausted={data.exhausted.applications}
          />
          <MetricRow
            label="广告账号"
            used={data.usage.accounts}
            limit={data.limits.accounts}
            exhausted={data.exhausted.accounts}
          />
          <MetricRow
            label="团队成员"
            used={data.usage.members}
            limit={data.limits.members}
            exhausted={data.exhausted.members}
          />
        </div>

        <button
          type="button"
          onClick={() => setUpgradeOpen(true)}
          className={cn(
            'shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 text-white text-xs font-medium rounded-lg shadow-sm transition',
            anyExhausted
              ? 'bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600'
              : 'bg-blue-600 hover:bg-blue-700',
          )}
        >
          <Sparkles className="w-3.5 h-3.5" />
          升级套餐
        </button>
      </div>

      {anyExhausted && (
        <div className="mt-3 flex items-start gap-1.5 text-[11px] text-amber-700">
          <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>
            当前套餐已达上限。继续创建应用 / 绑定账号会被拒绝，升级后立即解锁。
          </span>
        </div>
      )}

      {upgradeOpen && data && (
        <UpgradePlanDialog
          currentPlanId={data.plan_id}
          defaultEmail={localStorage.getItem('auth_user') ?? ''}
          onClose={() => setUpgradeOpen(false)}
        />
      )}
    </div>
  )
}
