import { describe, expect, it } from 'vitest'
import { readConsoleState, statusLabel } from './console-state'
const fallback = { startDate: '2026-10-01', endDate: '2026-10-03' }
describe('shared console links', () => {
  it('restores account, search, dates and pagination from a copied link', () => {
    expect(readConsoleState(new URLSearchParams('account_id=act_123&q=日本&start_date=2026-09-01&end_date=2026-09-30&sort=roas&dir=asc&page=3'), fallback)).toEqual({ dateRange: { startDate: '2026-09-01', endDate: '2026-09-30' }, accountId: 'act_123', search: '日本', sortKey: 'roas', sortDir: 'asc', page: 3 })
  })
  it('rejects impossible dates, reversed ranges and invalid pagination', () => {
    for (const query of ['start_date=2026-02-30&end_date=2026-03-01', 'start_date=2026-10-05&end_date=2026-10-03']) {
      expect(readConsoleState(new URLSearchParams(query), fallback).dateRange).toEqual(fallback)
    }
    for (const page of ['-1', 'NaN', '1.5', 'Infinity', '9007199254740992']) {
      expect(readConsoleState(new URLSearchParams(`page=${page}&sort=invalid&dir=invalid`), fallback)).toMatchObject({ page: 1, sortKey: 'total_spend', sortDir: 'desc' })
    }
  })
})
describe('platform states', () => {
  it('distinguishes review, parent pause and unknown status from a manual pause', () => {
    expect(statusLabel('meta', 'PENDING_REVIEW')).toMatchObject({ text: '审核中', canToggle: false })
    expect(statusLabel('meta', 'CAMPAIGN_PAUSED')).toMatchObject({ text: '系列暂停', canToggle: false })
    expect(statusLabel('tiktok', 'UNKNOWN')).toMatchObject({ text: '状态未知', canToggle: false })
    expect(statusLabel('meta', 'NEW_PLATFORM_STATE').text).toContain('NEW_PLATFORM_STATE')
    expect(statusLabel('tiktok', 'DISABLE')).toMatchObject({ text: '已暂停', canToggle: true })
    expect(statusLabel('meta', 'ACTIVE')).toMatchObject({ text: '投放中', active: true })
  })
})
