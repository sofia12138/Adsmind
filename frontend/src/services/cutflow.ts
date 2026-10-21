/** CutFlow 独立运行；入口不携带 AdsMind 的登录凭据或应用信息。 */
const configuredUrl = String(import.meta.env.VITE_CUTFLOW_URL ?? '').trim()
const localHost = ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)
const candidate = configuredUrl || (import.meta.env.DEV && localHost ? 'http://localhost:5173/series' : '')

function resolveUrl(value: string): string | undefined {
  if (!value) return undefined
  try {
    const url = new URL(value)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return undefined
    return url.href
  } catch {
    return undefined
  }
}

export const cutflowUrl = resolveUrl(candidate)
