/**
 * 阶段 7 配额限流 — 前端 service。
 *
 * 配套：
 *  - 后端 GET /api/quota/me 返回当前租户的套餐 + 已用 + 上限
 *  - api.ts::QuotaExceededError 用于业务侧捕获 422 + QUOTA_EXCEEDED_* 友好展示
 */
import { apiFetch } from './api'

export interface QuotaUsage {
  tenant_id: number
  is_internal: boolean
  plan_id: string
  plan_name: string
  limits: {
    applications: number
    accounts: number
    members: number
    api_calls_monthly: number
    ai_calls_monthly: number
  }
  usage: {
    applications: number
    accounts: number
    members: number
  }
  exhausted: {
    applications: boolean
    accounts: boolean
    members: boolean
  }
}

export async function getMyQuota(): Promise<QuotaUsage> {
  return apiFetch<QuotaUsage>('/api/quota/me')
}
