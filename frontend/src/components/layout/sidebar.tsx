import { useEffect, useId, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ChevronRight, ExternalLink, LogOut } from 'lucide-react'
import { cn } from '@/utils/cn'
import { menuConfig } from '@/app/menu-config'
import type { MenuItem } from '@/types/menu'
import { useAuth } from '@/contexts/AuthContext'
import { ApplicationSelector } from './ApplicationSelector'
import { filterMenu, isMenuBranchSelected, isMenuItemSelected } from './sidebar-menu'

function SidebarItem({ item, depth = 0 }: { item: MenuItem; depth?: number }) {
  const location = useLocation()
  const hasChildren = item.children && item.children.length > 0
  const isChildActive = hasChildren ? isMenuBranchSelected(item, location.pathname) : false
  const isSelected = isMenuItemSelected(item, location.pathname)
  const [open, setOpen] = useState(isChildActive)
  const submenuId = useId()
  const linkRef = useRef<HTMLAnchorElement>(null)

  useEffect(() => {
    if (isSelected) linkRef.current?.scrollIntoView({ block: 'nearest' })
  }, [isSelected])

  if (hasChildren) {
    return (
      <div>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-controls={submenuId}
          className={cn(
            'w-[calc(100%-1rem)] min-w-0 flex items-center gap-2.5 px-5 py-2 text-[13px] text-sidebar-foreground',
            'hover:bg-sidebar-hover hover:text-white transition-colors rounded-md mx-2',
            isChildActive && 'text-white',
          )}
        >
          {item.icon && <item.icon className="w-4 h-4 shrink-0 opacity-70" />}
          <span className="flex-1 min-w-0 truncate text-left">{item.label}</span>
          <ChevronRight className={cn('w-3.5 h-3.5 transition-transform opacity-50', open && 'rotate-90')} />
        </button>
        {open && (
          <div id={submenuId} className="mt-0.5 space-y-0.5">
            {item.children!.map(child => (
              <SidebarItem key={child.id} item={child} depth={depth + 1} />
            ))}
          </div>
        )}
      </div>
    )
  }

  if (item.externalUrl) {
    return <a href={item.externalUrl} target="_blank" rel="noopener noreferrer"
      title={`${item.label}（新标签页打开）`}
      className={cn('flex min-w-0 max-w-[calc(100%-1rem)] items-center gap-2.5 py-2 text-[13px] transition-colors rounded-md mx-2 text-sidebar-foreground hover:bg-sidebar-hover hover:text-white', depth > 0 ? 'pl-11 pr-4' : 'px-5')}>
      {item.icon && depth === 0 && <item.icon className="w-4 h-4 shrink-0 opacity-70" />}
      <span className="min-w-0 truncate">{item.label}</span><ExternalLink className="w-3 h-3 shrink-0 opacity-60" />
    </a>
  }

  if (!item.path) return null

  return (
    <Link
      ref={linkRef}
      to={item.path}
      aria-current={isSelected ? 'page' : undefined}
      className={cn(
        'flex min-w-0 max-w-[calc(100%-1rem)] items-center gap-2.5 py-2 text-[13px] transition-colors rounded-md mx-2',
        depth > 0 ? 'pl-11 pr-4' : 'px-5',
        isSelected
          ? 'bg-primary/15 text-blue-400 font-medium'
          : 'text-sidebar-foreground hover:bg-sidebar-hover hover:text-white',
      )}
    >
      {item.icon && depth === 0 && <item.icon className="w-4 h-4 shrink-0 opacity-70" />}
      <span className="min-w-0 truncate">{item.label}</span>
    </Link>
  )
}

export function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { hasPanel, hasPlugin, logout, username, tenant } = useAuth()

  const visibleMenu = filterMenu(menuConfig, hasPanel, hasPlugin, tenant.isInternal)

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  const displayUser = username || localStorage.getItem('auth_user') || '用户'

  return (
    <aside className="fixed left-0 top-0 bottom-0 w-[220px] overflow-hidden bg-sidebar flex flex-col z-40">
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="w-9 h-9 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center text-white text-sm font-bold shadow-lg shadow-blue-500/20">
          A
        </div>
        <span className="text-white font-semibold text-base tracking-tight">AdsMind</span>
      </div>

      {/* 阶段 4 X1：当前应用切换器 */}
      <ApplicationSelector />

      <nav aria-label="主导航" className="flex-1 min-h-0 overflow-x-hidden overflow-y-auto py-2 mt-2 space-y-0.5">
        {visibleMenu.map(item => (
          <SidebarItem
            key={`${item.id}:${isMenuBranchSelected(item, location.pathname)}`}
            item={item}
          />
        ))}
      </nav>

      <div className="border-t border-white/5 px-4 py-3 space-y-2">
        <div className="px-2 py-1.5 text-xs text-slate-400">
          <div className="text-[10px] text-slate-500">当前团队</div>
          <div className="mt-1 truncate" title={tenant.name}>{tenant.name}</div>
        </div>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-7 h-7 rounded-full bg-slate-600 flex items-center justify-center text-white text-xs font-medium shrink-0">
              {displayUser.charAt(0).toUpperCase()}
            </div>
            <span className="text-xs text-slate-400 truncate">{displayUser}</span>
          </div>
          <button onClick={handleLogout} className="p-1.5 rounded-md text-slate-500 hover:text-white hover:bg-slate-700 transition" title="退出登录">
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </aside>
  )
}
