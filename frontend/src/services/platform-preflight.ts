import { apiFetch } from './api'

export interface PreflightReason {
  code: string
  message: string
  platform?: string
  account_id?: string
  material_id?: number
  version_id?: number
  field?: string
}

export interface PreflightRun {
  id: string
  draft_id: string
  request_key: string
  snapshot_hash: string
  status: 'PASSED' | 'BLOCKED'
  blocking_reasons: PreflightReason[]
  dry_run_plan: {
    contract: 'ad_platform_dry_run_plan.v1'
    dry_run: true
    external_write_authorized: false
    executable: false
    preflight_passed: boolean
    operations: Array<Record<string, unknown>>
    notice: string
  }
  plan_hash: string
  execution_key: string
  dry_run: true
  external_write_authorized: false
  created_by: string
  created_at: string
}

export async function listPreflightRuns(draftId?: string) {
  const query = draftId ? `?draft_id=${encodeURIComponent(draftId)}` : ''
  return (await apiFetch<{ data: PreflightRun[] }>(`/api/platform-preflight/runs${query}`)).data
}

export async function runPlatformPreflight(draftId: string, requestKey: string) {
  return (await apiFetch<{ data: PreflightRun }>(`/api/platform-preflight/drafts/${draftId}/runs`, {
    method: 'POST',
    body: JSON.stringify({ request_key: requestKey, external_write_authorized: false }),
  })).data
}
