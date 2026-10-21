import { describe, expect, it } from 'vitest'
import { preservedDirectRoutes, redirectWithSearch } from './navigation-contract'

describe('navigation route compatibility', () => {
  it('keeps hidden and converged entries on their original guarded routes', () => {
    expect(preservedDirectRoutes).toEqual([
    ['ads/drafts', 'ad_create'],
    ['ads/platform-preflight', 'platform_preflight'],
    ['templates', 'template_mgmt'],
    ['tiktok-materials', 'tiktok_materials'],
    ['asset-analysis', 'creatives'],
    ].map(([path, panelKey]) => ({ path, panelKey })))
  })

  it('keeps the TikTok Minis legacy redirect and query string', () => {
    expect(redirectWithSearch('/ads/create', '?template_id=42&source=minis')).toBe(
      '/ads/create?template_id=42&source=minis',
    )
  })
})
