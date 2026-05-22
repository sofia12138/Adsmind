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

  if (!token && location.pathname !== '/login') {
    return <Navigate to="/login" replace />
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
