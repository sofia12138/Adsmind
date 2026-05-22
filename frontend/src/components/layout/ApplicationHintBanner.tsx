/**
 * 阶段 4 Onboarding：把后端 X3-filter 返回的 `_hint` 提示展现给用户。
 *
 * 触发场景（举例）：
 *   - 切到非默认应用，但该应用未绑定任何广告账号
 *   - 切到非默认应用，绑定了多个账号但用户没在筛选条里指定 account_id
 *
 * 行为：
 *   - 顶部黄色横幅展示文案
 *   - 提供「去配置 →」按钮：直跳当前应用详情页 /applications/:id?tab=accounts
 *   - 可关闭；切换应用或 5 分钟后自动清除
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Lightbulb, X } from 'lucide-react'
import { APPLICATION_HINT_EVENT, type ApplicationHint } from '@/services/api'
import { useAuth } from '@/contexts/AuthContext'

export function ApplicationHintBanner() {
  const { currentApplication } = useAuth()
  const [hint, setHint] = useState<ApplicationHint | null>(null)
  const [dismissedAt, setDismissedAt] = useState<number>(0)

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<ApplicationHint>).detail
      // 5 分钟内已被用户关闭的同款 hint 不再显示
      if (detail.at - dismissedAt < 5 * 60 * 1000 && hint?.hint === detail.hint) {
        return
      }
      setHint(detail)
    }
    window.addEventListener(APPLICATION_HINT_EVENT, handler)
    return () => window.removeEventListener(APPLICATION_HINT_EVENT, handler)
  }, [hint, dismissedAt])

  // 应用切换时清掉旧 hint
  useEffect(() => {
    setHint(null)
  }, [currentApplication?.id])

  if (!hint) return null

  const appId = hint.applicationId ?? currentApplication?.id
  const detailLink = appId ? `/applications/${appId}` : '/applications'

  return (
    <div className="bg-amber-500/10 border-b border-amber-500/30 px-6 py-2.5 flex items-center justify-between text-[13px] text-amber-100">
      <div className="flex items-center gap-2 min-w-0">
        <Lightbulb className="w-4 h-4 shrink-0 text-amber-300" />
        <span className="truncate">{hint.hint}</span>
      </div>
      <div className="flex items-center gap-3 shrink-0 ml-4">
        <Link
          to={detailLink}
          className="text-amber-200 hover:text-white underline underline-offset-2 transition"
        >
          去配置 →
        </Link>
        <button
          onClick={() => {
            setDismissedAt(Date.now())
            setHint(null)
          }}
          className="text-amber-300/70 hover:text-amber-200 transition"
          aria-label="关闭提示"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )
}
