import { describe, expect, it } from 'vitest'
import { buildReadinessDetailsPath } from '../readiness-analytics'

describe('readiness analytics query contract', () => {
  it('omits defaults and encodes filters', () => {
    expect(buildReadinessDetailsPath()).toBe('/api/readiness-analytics/details')
    expect(buildReadinessDetailsPath({
      entityType: 'preflight', status: 'blocked', reasonCode: 'credential_missing',
      query: ' Draft A ', page: 2, pageSize: 25,
    })).toBe('/api/readiness-analytics/details?entity_type=preflight&status=blocked&reason_code=credential_missing&query=Draft+A&page=2&page_size=25')
  })
})
