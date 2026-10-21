import { describe, expect, it } from 'vitest'
import { menuConfig } from './menu-config'
import type { MenuItem } from '@/types/menu'

function flatten(items: MenuItem[]): MenuItem[] {
  return items.flatMap(item => [item, ...(item.children ? flatten(item.children) : [])])
}

describe('confirmed navigation structure', () => {
  const all = flatten(menuConfig)

  it('keeps the confirmed 10 roots and 49 nodes in order', () => {
    expect(menuConfig.map(item => item.id)).toEqual([
      'dashboard', 'ops-dashboard', 'ads-mgmt', 'content-library', 'media',
      'distribution', 'analytics', 'compare-group', 'asset-library', 'system-group',
    ])
    expect(all).toHaveLength(49)
  })

  it('moves account groups and naming rules into the asset library exactly once', () => {
    const assetLibrary = menuConfig.find(item => item.id === 'asset-library')
    const system = menuConfig.find(item => item.id === 'system-group')
    expect(assetLibrary?.children?.map(item => item.id)).toEqual([
      'asset-landing-pages', 'asset-copy-packs', 'asset-region-groups', 'account-groups', 'naming-rules',
    ])
    expect(system?.children?.map(item => item.id)).not.toContain('account-groups')
    expect(system?.children?.map(item => item.id)).not.toContain('naming-rules')
    expect(all.filter(item => item.id === 'account-groups')).toHaveLength(1)
    expect(all.filter(item => item.id === 'naming-rules')).toHaveLength(1)
  })

  it('hides legacy entries without changing their routes elsewhere', () => {
    const paths = all.map(item => item.path)
    expect(paths).not.toContain('/ads/drafts')
    expect(paths).not.toContain('/ads/platform-preflight')
    expect(paths).not.toContain('/templates')
    expect(paths).not.toContain('/tiktok-materials')
  })

  it('preserves visibility metadata and external links', () => {
    expect(all.find(item => item.id === 'upgrade-requests')?.internalOnly).toBe(true)
    expect(all.find(item => item.id === 'designer-performance')?.pluginKey).toBe('designer_performance')
    expect(all.find(item => item.id === 'drama-analysis')?.pluginKey).toBe('drama')
    expect(all.find(item => item.id === 'optimizer-performance')?.pluginKey).toBe('optimizer')
    expect(all.find(item => item.id === 'auto-edit')).toHaveProperty('externalUrl')
  })
})
