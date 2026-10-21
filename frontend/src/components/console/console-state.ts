import type { DateRange } from '@/components/common/DateRangeFilter'

export const SORT_KEYS = ['total_spend', 'total_revenue', 'roas', 'ctr', 'cpc', 'total_registrations', 'total_installs', 'total_clicks', 'total_impressions', 'total_conversions', 'cpi', 'cpa', 'cpm'] as const
export type ConsoleSort = typeof SORT_KEYS[number]

function validDate(value: string | null): value is string {
  return !!value && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
}

export function readConsoleState(params: URLSearchParams, fallback: DateRange) {
  const start = params.get('start_date')
  const end = params.get('end_date')
  const range = validDate(start) && validDate(end) && start <= end ? { startDate: start, endDate: end } : fallback
  const requestedPage = Number(params.get('page'))
  return {
    dateRange: range,
    accountId: params.get('account_id') ?? '',
    search: (params.get('q') ?? '').slice(0, 200),
    sortKey: SORT_KEYS.includes(params.get('sort') as ConsoleSort) ? params.get('sort') as ConsoleSort : 'total_spend' as ConsoleSort,
    sortDir: params.get('dir') === 'asc' ? 'asc' as const : 'desc' as const,
    page: Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1,
  }
}

export function statusLabel(platform: string, status: string): { text: string; active: boolean; canToggle: boolean } {
  const active = platform === 'tiktok' ? ['ENABLE', 'ENABLED', 'ACTIVE'].includes(status) : status === 'ACTIVE'
  if (active) return { text: '投放中', active: true, canToggle: true }
  if (['DISABLE', 'DISABLED', 'PAUSED'].includes(status)) return { text: '已暂停', active: false, canToggle: true }
  const labels: Record<string, string> = {
    CAMPAIGN_PAUSED: '系列暂停', ADSET_PAUSED: '广告组暂停',
    PENDING_REVIEW: '审核中', IN_PROCESS: '处理中', AD_STATUS_REVIEW: '审核中',
    DISAPPROVED: '审核未通过', REJECTED: '审核未通过',
    DELETED: '已删除', ARCHIVED: '已归档', WITH_ISSUES: '存在问题',
    UNKNOWN: '状态未知', NOT_DELIVERING: '未投放',
  }
  return { text: labels[status] ?? (status ? `其他状态：${status}` : '状态未知'), active: false, canToggle: false }
}
