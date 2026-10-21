import { apiFetch } from './api'

export interface AccountRef {
  platform: string
  account_id: string
}

export interface AccountGroup {
  id: number
  name: string
  account_refs: AccountRef[]
  created_by: string
  created_at?: string
  updated_at?: string
}

export interface NamingRuleValue {
  pattern: string
  description: string
  fields?: string[]
}

export interface NamingRule {
  id: number
  name: string
  rule: NamingRuleValue
  created_by: string
  created_at?: string
  updated_at?: string
}

export function fetchApplicationSettingsAccess() {
  return apiFetch<{ role: string | null; can_write: boolean }>('/api/application-settings/access')
}

export async function fetchAccountGroups() {
  return (await apiFetch<{ data: AccountGroup[] }>('/api/account-groups')).data
}

export function createAccountGroup(body: { name: string; account_refs: AccountRef[] }) {
  return apiFetch<{ data: AccountGroup }>('/api/account-groups', {
    method: 'POST', body: JSON.stringify(body),
  })
}

export function updateAccountGroup(id: number, body: { name: string; account_refs: AccountRef[] }) {
  return apiFetch<{ data: AccountGroup }>(`/api/account-groups/${id}`, {
    method: 'PUT', body: JSON.stringify(body),
  })
}

export function deleteAccountGroup(id: number) {
  return apiFetch<{ ok: boolean }>(`/api/account-groups/${id}`, { method: 'DELETE' })
}

export async function fetchNamingRules() {
  return (await apiFetch<{ data: NamingRule[]; allowed_fields: string[] }>('/api/naming-rules')).data
}

export function createNamingRule(body: { name: string; rule: NamingRuleValue }) {
  return apiFetch<{ data: NamingRule }>('/api/naming-rules', {
    method: 'POST', body: JSON.stringify(body),
  })
}

export function updateNamingRule(id: number, body: { name: string; rule: NamingRuleValue }) {
  return apiFetch<{ data: NamingRule }>(`/api/naming-rules/${id}`, {
    method: 'PUT', body: JSON.stringify(body),
  })
}

export function deleteNamingRule(id: number) {
  return apiFetch<{ ok: boolean }>(`/api/naming-rules/${id}`, { method: 'DELETE' })
}
