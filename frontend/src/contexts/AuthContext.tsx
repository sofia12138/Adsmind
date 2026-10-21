import { createContext, useContext, useState, useCallback, useEffect, useRef, type ReactNode } from 'react'
import { listApplications, type Application } from '@/services/application'
import { useQueryClient } from '@tanstack/react-query'

/**
 * 阶段 1：AuthContext 增加 tenant 上下文字段。
 * - 仅读取，不强制业务路由使用。
 * - 旧后端响应（无 tenant 字段）会自动降级为 internal tenant。
 * - 详见 docs/saas-transformation.md §8。
 *
 * 阶段 4 X1：在 tenant 之上叠加 application 上下文。
 * - applications：当前租户下所有 active 应用
 * - currentApplication：当前正在工作的应用（持久化到 localStorage.current_application_id）
 * - switchApplication：切换应用并刷新 react-query 缓存
 */
export interface TenantInfo {
  id: number
  slug: string
  name: string
  planId: string
  isInternal: boolean
  enabledPlugins: string[]
}

const DEFAULT_INTERNAL_TENANT: TenantInfo = {
  id: 1,
  slug: 'internal',
  name: 'AdsMind 内部',
  planId: 'internal',
  isInternal: true,
  enabledPlugins: [
    'core_ads',
    'drama',
    'optimizer',
    'attribution_metis',
    'returned_conversion',
    'ops_panel_polardb',
    'ai_studio',
  ],
}

/**
 * 阶段 3 批次 1 补丁：通用版预览视图。
 * 用于在不动后端业务逻辑的前提下，在前端体验"外部租户登录后"的菜单形态。
 * tenant.id 仍保持 1，所以现有 API 仍能拿到内部数据；
 * 仅 isInternal=false + enabledPlugins=['core_ads'] 让 hasPlugin() 把短剧专属菜单过滤掉。
 * 阶段 4 完成后会被真正的"外部租户注册流程"取代。
 */
const PREVIEW_TENANT_GENERIC: TenantInfo = {
  id: 1,
  slug: 'preview-generic',
  name: '通用版试用',
  planId: 'free',
  isInternal: false,
  enabledPlugins: ['core_ads'],
}

interface AuthState {
  allowedPanels: string[]
  role: string
  username: string
  tenant: TenantInfo
  applications: Application[]
  currentApplication: Application | null
  applicationsLoaded: boolean
  loaded: boolean
}

interface AuthContextValue extends AuthState {
  setAuth: (panels: string[], role: string, username: string, tenant?: TenantInfo | null) => void
  hasPanel: (panelKey: string) => boolean
  hasPlugin: (pluginKey: string) => boolean
  refreshPanels: () => Promise<void>
  logout: () => void
  /** 当前是否处于"通用版试用"预览视图（前端 demo 用，阶段 4 后由真实租户态接管）。 */
  isPreviewMode: boolean
  /** 切换内部 / 通用版试用视图。改 localStorage.auth_tenant 并刷新本地 state。 */
  togglePreviewMode: () => void
  /** 拉取当前租户的全部应用列表（阶段 4 X1）。 */
  refreshApplications: () => Promise<void>
  /** 切换当前活动应用，持久化到 localStorage 并通知页面刷新。 */
  switchApplication: (applicationId: number) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

// Hook and provider intentionally share the context module.
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

function normalizeTenant(raw: unknown): TenantInfo {
  if (!raw || typeof raw !== 'object') return DEFAULT_INTERNAL_TENANT
  const r = raw as Record<string, unknown>
  return {
    id: Number(r.id ?? 1),
    slug: String(r.slug ?? 'internal'),
    name: String(r.name ?? 'AdsMind 内部'),
    planId: String(r.plan_id ?? r.planId ?? 'internal'),
    isInternal: Boolean(r.is_internal ?? r.isInternal ?? true),
    enabledPlugins: Array.isArray(r.enabled_plugins ?? r.enabledPlugins)
      ? ((r.enabled_plugins ?? r.enabledPlugins) as string[])
      : DEFAULT_INTERNAL_TENANT.enabledPlugins,
  }
}

function loadFromStorage(): AuthState {
  try {
    const raw = localStorage.getItem('auth_panels')
    const panels = raw ? JSON.parse(raw) as string[] : []
    const role = localStorage.getItem('auth_role') || ''
    const username = localStorage.getItem('auth_user') || ''
    const token = localStorage.getItem('auth_token') || ''
    const tenantRaw = localStorage.getItem('auth_tenant')
    const tenant = tenantRaw ? normalizeTenant(JSON.parse(tenantRaw)) : DEFAULT_INTERNAL_TENANT
    return {
      allowedPanels: panels,
      role,
      username,
      tenant,
      applications: [],
      currentApplication: null,
      applicationsLoaded: false,
      loaded: !!token,
    }
  } catch {
    return {
      allowedPanels: [],
      role: '',
      username: '',
      tenant: DEFAULT_INTERNAL_TENANT,
      applications: [],
      currentApplication: null,
      applicationsLoaded: false,
      loaded: false,
    }
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<AuthState>(loadFromStorage)
  const identity = useRef({ username: state.username, tenantId: state.tenant.id })

  const setAuth = useCallback((
    panels: string[],
    role: string,
    username: string,
    tenant?: TenantInfo | null,
  ) => {
    if (identity.current.username !== username || identity.current.tenantId !== (tenant?.id ?? 1)) {
      queryClient.clear()
      localStorage.removeItem('current_application_id')
    }
    localStorage.setItem('auth_panels', JSON.stringify(panels))
    localStorage.setItem('auth_role', role)
    localStorage.setItem('auth_user', username)
    const finalTenant = tenant ?? DEFAULT_INTERNAL_TENANT
    identity.current = { username, tenantId: finalTenant.id }
    localStorage.setItem('auth_tenant', JSON.stringify(finalTenant))
    setState(s => ({
      ...s,
      allowedPanels: panels,
      role,
      username,
      tenant: finalTenant,
      loaded: true,
    }))
  }, [queryClient])

  const hasPanel = useCallback((panelKey: string) => {
    if (state.role === 'super_admin') return true
    return state.allowedPanels.includes(panelKey)
  }, [state.allowedPanels, state.role])

  const hasPlugin = useCallback((pluginKey: string) => {
    // 内部租户视为全开；外部租户按 enabledPlugins 判定。
    if (state.tenant.isInternal) return true
    return state.tenant.enabledPlugins.includes(pluginKey)
  }, [state.tenant])

  const refreshPanels = useCallback(async () => {
    const token = localStorage.getItem('auth_token')
    if (!token) return
    try {
      const res = await fetch('/api/panels/my', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        const data = await res.json()
        const tenant = data.tenant ? normalizeTenant(data.tenant) : state.tenant
        setAuth(data.allowed_panels ?? [], data.role ?? state.role, state.username, tenant)
      }
    } catch { /* silent */ }
  }, [setAuth, state.role, state.tenant, state.username])

  const isPreviewMode = !state.tenant.isInternal && state.tenant.slug === 'preview-generic'

  const togglePreviewMode = useCallback(() => {
    const next = isPreviewMode ? DEFAULT_INTERNAL_TENANT : PREVIEW_TENANT_GENERIC
    localStorage.setItem('auth_tenant', JSON.stringify(next))
    setState(s => ({ ...s, tenant: next }))
  }, [isPreviewMode])

  const refreshApplications = useCallback(async () => {
    const token = localStorage.getItem('auth_token')
    if (!token) return
    try {
      const apps = await listApplications(false)
      const storedId = localStorage.getItem('current_application_id')
      let current: Application | null = null
      if (storedId) {
        current = apps.find(a => String(a.id) === storedId) ?? null
      }
      // 兜底：未持久化或持久化的应用不在列表里 → 选默认应用，没有就第一个
      if (!current) {
        current = apps.find(a => a.is_default) ?? apps[0] ?? null
        if (current) {
          localStorage.setItem('current_application_id', String(current.id))
        }
      }
      setState(s => ({ ...s, applications: apps, currentApplication: current, applicationsLoaded: true }))
      if (current && !storedId) {
        window.location.reload()
      }
    } catch {
      // 未登录或后端不可用时保持加载态；不能把依赖故障误报为“未分配应用”。
    }
  }, [])

  const switchApplication = useCallback((applicationId: number) => {
    const target = state.applications.find(a => a.id === applicationId)
    if (!target) return
    localStorage.setItem('current_application_id', String(applicationId))
    setState(s => ({ ...s, currentApplication: target }))
    // 简单粗暴的方式：reload 让所有页面重新拉数据。
    // 阶段 4 X3 之后切换为 react-query.invalidateQueries 平滑刷新。
    window.location.reload()
  }, [state.applications])

  const logout = useCallback(() => {
    queryClient.clear()
    identity.current = { username: '', tenantId: 0 }
    localStorage.removeItem('auth_token')
    localStorage.removeItem('auth_user')
    localStorage.removeItem('auth_role')
    localStorage.removeItem('auth_panels')
    localStorage.removeItem('auth_tenant')
    localStorage.removeItem('current_application_id')
    setState({
      allowedPanels: [],
      role: '',
      username: '',
      tenant: DEFAULT_INTERNAL_TENANT,
      applications: [],
      currentApplication: null,
      applicationsLoaded: false,
      loaded: false,
    })
  }, [queryClient])

  useEffect(() => {
    const token = localStorage.getItem('auth_token')
    if (token && state.allowedPanels.length === 0) {
      refreshPanels()
    }
    if (token) {
      refreshApplications()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <AuthContext.Provider
      value={{
        ...state,
        setAuth,
        hasPanel,
        hasPlugin,
        refreshPanels,
        logout,
        isPreviewMode,
        togglePreviewMode,
        refreshApplications,
        switchApplication,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}
