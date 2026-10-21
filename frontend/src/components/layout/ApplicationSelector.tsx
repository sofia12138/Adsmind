/**
 * ApplicationSelector — 顶部应用切换器（阶段 4 X1）。
 *
 * 显示当前激活的应用名，点击展开 dropdown 列出当前租户全部 active 应用，
 * 提供切换、跳到"应用管理"入口的能力。
 */
import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, Check, Plus, Layers, Archive } from 'lucide-react'
import { cn } from '@/utils/cn'
import { useAuth } from '@/contexts/AuthContext'

export function ApplicationSelector() {
  const { applications, currentApplication, switchApplication } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open])

  const showName = currentApplication?.name ?? '未分配应用'
  const showIndustry = currentApplication?.industry || ''

  return (
    <div ref={ref} className="relative px-3">
      <button
        onClick={() => setOpen(o => !o)}
        className={cn(
          'w-full flex items-center gap-2 px-3 py-2 rounded-md transition-colors',
          'bg-white/5 hover:bg-white/10 text-left',
        )}
      >
        <Layers className="w-4 h-4 text-blue-400 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-[12px] text-slate-400 leading-none mb-0.5">当前应用</div>
          <div className="text-[13px] text-white font-medium truncate">{showName}</div>
        </div>
        <ChevronDown className={cn('w-4 h-4 text-slate-400 transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute left-3 right-3 top-full mt-1 z-50 bg-[#1a2233] border border-white/10 rounded-md shadow-xl overflow-hidden">
          <div className="max-h-64 overflow-y-auto">
            {applications.length === 0 && (
              <div className="px-4 py-3 text-xs text-slate-500">暂无应用</div>
            )}
            {applications.map(app => {
              const active = currentApplication?.id === app.id
              return (
                <button
                  key={app.id}
                  onClick={() => {
                    setOpen(false)
                    if (!active) switchApplication(app.id)
                  }}
                  className={cn(
                    'w-full flex items-center gap-2 px-4 py-2 text-left text-[13px] transition-colors',
                    active
                      ? 'bg-blue-500/15 text-blue-300'
                      : 'text-slate-300 hover:bg-white/5 hover:text-white',
                  )}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate">{app.name}</span>
                      {app.is_default && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">
                          默认
                        </span>
                      )}
                      {app.status === 'archived' && (
                        <Archive className="w-3 h-3 text-slate-500" />
                      )}
                    </div>
                    {app.industry && (
                      <div className="text-[11px] text-slate-500 mt-0.5">{app.industry}</div>
                    )}
                  </div>
                  {active && <Check className="w-3.5 h-3.5 text-blue-400" />}
                </button>
              )
            })}
          </div>

          <div className="border-t border-white/5">
            <button
              onClick={() => {
                setOpen(false)
                navigate('/applications')
              }}
              className="w-full flex items-center gap-2 px-4 py-2 text-[12px] text-slate-400 hover:bg-white/5 hover:text-white transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>管理应用</span>
            </button>
          </div>
        </div>
      )}
      <span className="sr-only">{showIndustry}</span>
    </div>
  )
}
