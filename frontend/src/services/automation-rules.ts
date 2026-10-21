import { apiFetch } from './api'

export type RuleSource = 'material' | 'creative_group' | 'ad_draft' | 'platform_preflight'
export type RuleOutcome = 'review_required' | 'blocking_reason'

export interface RuleCondition {
  source: RuleSource
  field: string
  operator: 'equals' | 'not_equals' | 'in' | 'not_in' | 'contains' | 'exists'
  value: unknown
  quantifier: 'any' | 'all'
  outcome: RuleOutcome
  code: string
  message: string
}

export interface AutomationRule {
  id: string
  name: string
  description: string
  status: 'ACTIVE' | 'DISABLED'
  current_version: number
  rule_version_id: number
  definition: { conditions: RuleCondition[] }
  definition_hash: string
  updated_at: string
}

export interface RuleRecommendation {
  id: number
  outcome: 'review_required'
  reason_code: string
  reason_message: string
  evidence: Record<string, unknown>
}

export interface RuleEvaluation {
  id: string
  rule_id: string
  rule_version_id: number
  status: 'CLEAR' | 'REVIEW_REQUIRED' | 'BLOCKED'
  input_snapshot: Record<string, unknown>
  input_snapshot_hash: string
  evaluation_key: string
  blocking_reasons: Array<{ code: string; message: string; evidence?: Record<string, unknown> }>
  recommendations: RuleRecommendation[]
  dry_run: true
  external_write_authorized: false
  created_at: string
}

export interface RuleWriteInput {
  name: string
  description: string
  status: 'ACTIVE' | 'DISABLED'
  definition: { conditions: RuleCondition[] }
}

export async function listAutomationRules() {
  return (await apiFetch<{ data: AutomationRule[] }>('/api/automation-rules')).data
}

export async function createAutomationRule(input: RuleWriteInput) {
  return (await apiFetch<{ data: AutomationRule }>('/api/automation-rules', {
    method: 'POST', body: JSON.stringify(input),
  })).data
}

export async function updateAutomationRule(ruleId: string, input: RuleWriteInput, expectedVersion: number) {
  return (await apiFetch<{ data: AutomationRule }>(`/api/automation-rules/${ruleId}`, {
    method: 'PUT', body: JSON.stringify({ ...input, expected_version: expectedVersion }),
  })).data
}

export async function listRuleEvaluations(ruleId: string) {
  return (await apiFetch<{ data: RuleEvaluation[] }>(`/api/automation-rules/${ruleId}/evaluations`)).data
}

export async function runRuleEvaluation(ruleId: string, input: {
  material_ids: number[]
  creative_group_ids: number[]
  ad_draft_ids: string[]
  platform_preflight_run_ids: string[]
}) {
  return (await apiFetch<{ data: RuleEvaluation }>(`/api/automation-rules/${ruleId}/evaluations`, {
    method: 'POST', body: JSON.stringify({ ...input, external_write_authorized: false }),
  })).data
}
