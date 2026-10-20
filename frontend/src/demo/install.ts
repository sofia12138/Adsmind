/**
 * 演示预览引导。仅在 `vite build --mode demo`（或 VITE_DEMO_MODE=true）时启用。
 * 不连接任何后端、数据库或广告平台；所有 /api 请求在浏览器内返回虚构数据。
 */
import { DEMO_PANELS } from './constants'
import { installDemoFetch } from './mockApi'

export function isDemoBuild(): boolean {
  return import.meta.env.MODE === 'demo' || import.meta.env.VITE_DEMO_MODE === 'true'
}

const DEMO_TOKEN = 'demo-preview'
const DEMO_USER = 'demo.owner'

const DEMO_TENANT = {
  id: 1,
  slug: 'lumen-demo',
  name: 'Lumen Demo',
  plan_id: 'internal',
  is_internal: true,
  enabled_plugins: [
    'core_ads',
    'drama',
    'optimizer',
    'designer_performance',
    'attribution_metis',
    'returned_conversion',
    'ops_panel_polardb',
    'ai_studio',
  ],
}

function seedSession() {
  if (!localStorage.getItem('auth_token')) {
    localStorage.setItem('auth_token', DEMO_TOKEN)
    localStorage.setItem('auth_user', DEMO_USER)
    localStorage.setItem('auth_role', 'super_admin')
    localStorage.setItem('auth_panels', JSON.stringify(DEMO_PANELS))
    localStorage.setItem('auth_tenant', JSON.stringify(DEMO_TENANT))
    localStorage.setItem('current_application_id', '1')
    localStorage.setItem('email_verified', '1')
  }
}

function mountBanner() {
  if (document.getElementById('adsmind-demo-banner')) return
  const bar = document.createElement('div')
  bar.id = 'adsmind-demo-banner'
  bar.setAttribute('role', 'status')
  bar.textContent = '演示预览 · 广告账户、消耗与 ROAS 均为模拟数据 · 未连接 TikTok、Meta 或任何服务器'
  bar.style.cssText = [
    'position:fixed',
    'left:232px',
    'right:16px',
    'bottom:12px',
    'z-index:70',
    'padding:8px 12px',
    'border-radius:10px',
    'background:rgba(15,23,42,.92)',
    'color:#e2e8f0',
    'font:12px/1.4 ui-sans-serif,system-ui,sans-serif',
    'box-shadow:0 8px 24px rgba(0,0,0,.18)',
    'pointer-events:none',
  ].join(';')
  document.body.appendChild(bar)
}

export function installDemoPreview() {
  if (!isDemoBuild()) return
  seedSession()
  installDemoFetch()
  if (document.body) mountBanner()
  else document.addEventListener('DOMContentLoaded', mountBanner)
}
