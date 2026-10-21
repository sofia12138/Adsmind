import { describe, expect, it } from 'vitest'
import { menuConfig } from '@/app/menu-config'
import type { MenuItem } from '@/types/menu'
import { filterMenu, isMenuBranchSelected, isMenuItemSelected } from './sidebar-menu'

function flatten(items: MenuItem[]): MenuItem[] {
  return items.flatMap(item => [item, ...(item.children ? flatten(item.children) : [])])
}

describe('sidebar visibility', () => {
  it('requires both panel and plugin visibility', () => {
    const visible = flatten(filterMenu(menuConfig, () => true, key => key !== 'optimizer', true))
    expect(visible.map(item => item.id)).not.toContain('optimizer-performance')
    expect(visible.map(item => item.id)).not.toContain('optimizer-directory')
    expect(visible.map(item => item.id)).toContain('designer-performance')
  })

  it('filters internal and unauthorized leaves and empty groups', () => {
    const visible = flatten(filterMenu(menuConfig, key => key === 'dashboard', () => true, false))
    expect(visible.map(item => item.id)).toEqual(['dashboard'])
    expect(visible.map(item => item.id)).not.toContain('upgrade-requests')
  })
})

describe('sidebar selected state', () => {
  const ads = menuConfig.find(item => item.id === 'ads-mgmt')!
  const adsData = ads.children!.find(item => item.id === 'ads')!
  const adsCreate = ads.children!.find(item => item.id === 'ads-create')!
  const appDrafts = ads.children!.find(item => item.id === 'app-ad-drafts')!

  it('selects only the correct leaf for /ads/create', () => {
    expect(isMenuItemSelected(adsData, '/ads/create')).toBe(false)
    expect(isMenuItemSelected(adsCreate, '/ads/create')).toBe(true)
    expect(isMenuBranchSelected(ads, '/ads/create')).toBe(true)
  })

  it('supports declared detail routes without selecting broad index routes', () => {
    expect(isMenuItemSelected(appDrafts, '/ads/app-drafts/draft-1')).toBe(true)
    expect(isMenuItemSelected(adsData, '/ads/app-drafts/draft-1')).toBe(false)
    expect(isMenuItemSelected(adsData, '/ads/drafts')).toBe(false)
  })
})
