import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './sidebar'
import { ApplicationHintBanner } from './ApplicationHintBanner'
import { EmailVerifyBanner } from './EmailVerifyBanner'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'

function PreviewBanner() {
  const { isPreviewMode, togglePreviewMode } = useAuth()
  if (!isPreviewMode) return null
  return (
    <div className="bg-amber-500/10 border-b border-amber-500/20 px-6 py-2 flex items-center justify-between text-[12px] text-amber-200">
      <span>
        🧪 你正在以「通用版试用」视角浏览。菜单按外部租户表现（仅核心广告管理），
        后端数据仍是内部租户的；真实数据隔离将在阶段 4 完成。
      </span>
      <button
        onClick={togglePreviewMode}
        className="ml-4 underline underline-offset-2 hover:text-amber-100 transition"
      >
        返回内部视图
      </button>
    </div>
  )
}

function InnerLayout() {
  const location = useLocation()
  const token = localStorage.getItem('auth_token')
  const { applicationsLoaded, currentApplication } = useAuth()

  if (!token && location.pathname !== '/login') {
    return <Navigate to="/login" replace />
  }

  if (token && applicationsLoaded && !currentApplication) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
        <div className="max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <h1 className="text-lg font-semibold text-slate-900">尚未分配应用</h1>
          <p className="mt-2 text-sm leading-6 text-slate-500">你的账号已加入当前团队，但还没有可访问的应用。请联系团队管理员完成应用分配后再试。</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <Sidebar />
      <main className="ml-[220px]">
        <PreviewBanner />
        <EmailVerifyBanner />
        <ApplicationHintBanner />
        <div className="px-8 py-7">
          <Outlet />
        </div>
      </main>
    </div>
  )
}

export function MainLayout() {
  return (
    <AuthProvider>
      <InnerLayout />
    </AuthProvider>
  )
}
