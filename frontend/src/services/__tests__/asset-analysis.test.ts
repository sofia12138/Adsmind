import { describe, expect, it } from 'vitest'
import { buildAssetAnalysisPath } from '../asset-analysis'

describe('asset analysis API', () => {
  it('builds an explicit scoped report query without empty filters', () => {
    expect(buildAssetAnalysisPath({
      dimension: 'drama', dateFrom: '2026-10-01', dateTo: '2026-10-20',
      platform: 'tiktok', accountId: '123', coverageStatus: 'unmapped', query: ' 剧目 A ', page: 2,
    })).toBe('/api/asset-analysis/report?dimension=drama&date_from=2026-10-01&date_to=2026-10-20&platform=tiktok&account_id=123&coverage_status=unmapped&query=%E5%89%A7%E7%9B%AE+A&page=2')
  })

  it('always includes the date range and dimension', () => {
    expect(buildAssetAnalysisPath({ dimension: 'material', dateFrom: '2026-10-20', dateTo: '2026-10-20' }))
      .toBe('/api/asset-analysis/report?dimension=material&date_from=2026-10-20&date_to=2026-10-20')
  })
})
