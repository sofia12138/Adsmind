export const preservedDirectRoutes = [
  { path: 'ads/drafts', panelKey: 'ad_create' },
  { path: 'ads/platform-preflight', panelKey: 'platform_preflight' },
  { path: 'templates', panelKey: 'template_mgmt' },
  { path: 'tiktok-materials', panelKey: 'tiktok_materials' },
  { path: 'asset-analysis', panelKey: 'creatives' },
] as const

export type PreservedDirectRoutePath = typeof preservedDirectRoutes[number]['path']

export function redirectWithSearch(to: string, search: string): string {
  return `${to}${search}`
}
