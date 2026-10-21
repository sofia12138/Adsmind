import type { MenuItem } from '@/types/menu'

export function filterMenu(
  items: MenuItem[],
  hasPanel: (key: string) => boolean,
  hasPlugin: (key: string) => boolean,
  isInternal: boolean,
): MenuItem[] {
  return items.reduce<MenuItem[]>((acc, item) => {
    if (item.internalOnly && !isInternal) return acc
    if (item.children) {
      const filtered = filterMenu(item.children, hasPanel, hasPlugin, isInternal)
      if (filtered.length > 0) acc.push({ ...item, children: filtered })
      return acc
    }
    if (item.pluginKey && !hasPlugin(item.pluginKey)) return acc
    if (!item.panelKey || hasPanel(item.panelKey)) acc.push(item)
    return acc
  }, [])
}

/**
 * A leaf is selected only for its exact route. Detail routes can opt into a
 * prefix explicitly, preventing `/ads` from also selecting `/ads/create`.
 */
export function isMenuItemSelected(item: MenuItem, pathname: string): boolean {
  if (!item.path) return false
  if (pathname === item.path) return true
  return Boolean(item.matchSubpaths && pathname.startsWith(`${item.path}/`))
}

export function isMenuBranchSelected(item: MenuItem, pathname: string): boolean {
  if (isMenuItemSelected(item, pathname)) return true
  return item.children?.some(child => isMenuBranchSelected(child, pathname)) ?? false
}
