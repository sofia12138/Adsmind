/**
 * 阶段 4 Onboarding：新客户 / 空应用首次进入数据看板时的 3 步引导卡片。
 *
 * 触发条件：当前应用没有任何绑定账号（biz_overview 返回 `_hint` 或 spend=0 且无任何已绑账号）。
 * 视觉风格与其它 SectionCard 一致；3 步状态条 + 行动按钮。
 */
import { Link } from 'react-router-dom'
import { CheckCircle2, Circle, AppWindow, Plug, BarChart3 } from 'lucide-react'

interface Step {
  key: string
  icon: typeof AppWindow
  title: string
  description: string
  done: boolean
  action?: { label: string; to: string }
}

interface OnboardingChecklistProps {
  applicationId?: number
  applicationName?: string
  hint?: string
}

export function OnboardingChecklist({
  applicationId,
  applicationName,
  hint,
}: OnboardingChecklistProps) {
  const appPath = applicationId ? `/applications/${applicationId}` : '/applications'

  const steps: Step[] = [
    {
      key: 'create',
      icon: AppWindow,
      title: '创建应用',
      description: `当前应用「${applicationName ?? '未选择'}」已就绪`,
      done: !!applicationId,
    },
    {
      key: 'bind',
      icon: Plug,
      title: '绑定广告账号',
      description: '在应用配置页绑定 TikTok / Meta 账号，授权访问广告数据',
      done: false,
      action: { label: '去绑定 →', to: appPath },
    },
    {
      key: 'view',
      icon: BarChart3,
      title: '查看实时数据',
      description: '账号绑定 + 数据同步后，所有数据看板会自动按当前应用过滤',
      done: false,
    },
  ]

  return (
    <section className="rounded-2xl border border-amber-200/40 bg-gradient-to-br from-amber-50/40 to-orange-50/20 p-6">
      <header className="flex items-start gap-3 mb-5">
        <div className="rounded-full p-2 bg-amber-100/60">
          <AppWindow className="w-5 h-5 text-amber-600" />
        </div>
        <div>
          <h2 className="text-base font-semibold text-amber-900">
            欢迎使用 AdsMind 通用版
          </h2>
          <p className="text-sm text-amber-700/90 mt-1">
            {hint ??
              '当前应用还没有数据。按以下三步完成接入，即可看到广告投放的完整指标。'}
          </p>
        </div>
      </header>

      <ol className="space-y-3">
        {steps.map((s, idx) => (
          <li
            key={s.key}
            className={`flex items-center gap-4 rounded-xl border px-4 py-3 transition ${
              s.done
                ? 'border-emerald-200/60 bg-emerald-50/30'
                : 'border-amber-200/40 bg-white/60'
            }`}
          >
            <div className="shrink-0">
              {s.done ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-500" />
              ) : (
                <Circle className="w-5 h-5 text-amber-400" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-amber-600/80">
                  第 {idx + 1} 步
                </span>
                <s.icon className="w-3.5 h-3.5 text-amber-500/80" />
                <span className="text-sm font-medium text-gray-900">
                  {s.title}
                </span>
              </div>
              <p className="text-xs text-gray-500 mt-1 truncate">
                {s.description}
              </p>
            </div>
            {s.action && !s.done && (
              <Link
                to={s.action.to}
                className="shrink-0 inline-flex items-center px-3.5 py-1.5 rounded-lg bg-amber-500 text-white text-xs font-medium hover:bg-amber-600 transition"
              >
                {s.action.label}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </section>
  )
}
