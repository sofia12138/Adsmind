/**
 * ApplicationsListPage — 应用管理（阶段 4 X1）
 *
 * 功能：
 *  - 列表展示当前租户下所有应用（含归档过滤切换）
 *  - 创建 / 编辑 / 归档 / 恢复
 *  - 点击行 → 进入 ApplicationDetailPage 配置广告账号、归因、成员（X3~X5）
 */
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Loader2, AlertCircle, Plus, Archive, RotateCcw, Pencil, Layers, Check, X,
} from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { QuotaUsageCard } from '@/components/common/QuotaUsageCard'
import {
  listApplications,
  createApplication,
  updateApplication,
  archiveApplication,
  restoreApplication,
  type Application,
  type ApplicationCreateInput,
} from '@/services/application'
import { useAuth } from '@/contexts/AuthContext'
import { QuotaExceededError } from '@/services/api'
import { cn } from '@/utils/cn'

const PLATFORM_LABEL: Record<string, string> = {
  ios: 'iOS',
  android: 'Android',
  web: 'Web',
  mini_program: '小程序',
  multi: '全平台',
}

// ─────────────────────────────────────────────────────────────
// 表单弹窗
// ─────────────────────────────────────────────────────────────

interface FormProps {
  initial?: Application | null
  onClose: () => void
  onSubmit: (data: ApplicationCreateInput) => void
  saving: boolean
}

function ApplicationFormDialog({ initial, onClose, onSubmit, saving }: FormProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [slug, setSlug] = useState(initial?.slug ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [platformType, setPlatformType] = useState<Application['platform_type']>(
    initial?.platform_type ?? 'multi',
  )
  const [industry, setIndustry] = useState(initial?.industry ?? '')
  const [bundleId, setBundleId] = useState(initial?.bundle_id ?? '')
  const [storeUrlIos, setStoreUrlIos] = useState(initial?.store_url_ios ?? '')
  const [storeUrlAndroid, setStoreUrlAndroid] = useState(initial?.store_url_android ?? '')

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    onSubmit({
      name: name.trim(),
      slug: slug.trim() || undefined,
      description: description.trim() || undefined,
      platform_type: platformType,
      industry: industry.trim() || undefined,
      bundle_id: bundleId.trim() || undefined,
      store_url_ios: storeUrlIos.trim() || undefined,
      store_url_android: storeUrlAndroid.trim() || undefined,
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-xl w-full max-w-xl mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-800">
            {initial ? '编辑应用' : '新建应用'}
          </h3>
          <button onClick={onClose} className="p-1.5 rounded text-gray-400 hover:text-gray-700">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={submit} className="px-6 py-5 space-y-4 max-h-[70vh] overflow-y-auto">
          <Field label="应用名称" required>
            <input
              type="text"
              required
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="例如：星辰短剧 App"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="slug" hint={initial ? '修改 slug 会变更 URL' : '留空自动生成'}>
              <input
                type="text"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
                value={slug}
                onChange={e => setSlug(e.target.value)}
                placeholder="留空自动生成"
              />
            </Field>
            <Field label="平台类型">
              <select
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
                value={platformType}
                onChange={e => setPlatformType(e.target.value as Application['platform_type'])}
              >
                <option value="multi">全平台</option>
                <option value="ios">iOS</option>
                <option value="android">Android</option>
                <option value="web">Web</option>
                <option value="mini_program">小程序</option>
              </select>
            </Field>
          </div>

          <Field label="所属行业" hint="可选，用于行业模板和默认 KPI">
            <input
              type="text"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
              value={industry}
              onChange={e => setIndustry(e.target.value)}
              placeholder="例如：短剧 / 游戏 / 电商 / 教育"
            />
          </Field>

          <Field label="Bundle ID / Package Name">
            <input
              type="text"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
              value={bundleId}
              onChange={e => setBundleId(e.target.value)}
              placeholder="例如：com.example.app"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="App Store URL">
              <input
                type="url"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
                value={storeUrlIos}
                onChange={e => setStoreUrlIos(e.target.value)}
                placeholder="https://apps.apple.com/..."
              />
            </Field>
            <Field label="Google Play URL">
              <input
                type="url"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
                value={storeUrlAndroid}
                onChange={e => setStoreUrlAndroid(e.target.value)}
                placeholder="https://play.google.com/..."
              />
            </Field>
          </div>

          <Field label="应用描述">
            <textarea
              rows={3}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none"
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="给团队一个简单介绍"
            />
          </Field>
        </form>

        <div className="px-6 py-3 border-t border-gray-100 flex justify-end gap-2 bg-gray-50">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 rounded-md text-sm text-gray-600 hover:bg-gray-100"
            disabled={saving}
          >
            取消
          </button>
          <button
            type="submit"
            onClick={submit}
            disabled={saving || !name.trim()}
            className="px-4 py-1.5 rounded-md bg-blue-600 text-white text-sm hover:bg-blue-700 disabled:bg-gray-300 flex items-center gap-1"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {initial ? '保存' : '创建应用'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, required, hint, children }: {
  label: string; required?: boolean; hint?: string; children: React.ReactNode
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-600 mb-1">
        {label}
        {required && <span className="text-red-400 ml-0.5">*</span>}
      </label>
      {children}
      {hint && <p className="text-xs text-gray-400 mt-1">{hint}</p>}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// 主页面
// ─────────────────────────────────────────────────────────────

export default function ApplicationsListPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { refreshApplications, currentApplication } = useAuth()
  const [includeArchived, setIncludeArchived] = useState(false)
  const [editing, setEditing] = useState<Application | null>(null)
  const [creating, setCreating] = useState(false)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['applications', includeArchived],
    queryFn: () => listApplications(includeArchived),
  })

  const createMutation = useMutation({
    mutationFn: createApplication,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['applications'] })
      await queryClient.invalidateQueries({ queryKey: ['quota', 'me'] })
      await refreshApplications()
      setCreating(false)
    },
    onError: (err: unknown) => {
      if (err instanceof QuotaExceededError) {
        alert(
          `${err.message}\n\n${err.upgradeHint ?? '请升级套餐解锁更多额度。'}`,
        )
        setCreating(false)
      } else {
        alert('创建应用失败，请稍后重试')
      }
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: ApplicationCreateInput }) =>
      updateApplication(id, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['applications'] })
      await refreshApplications()
      setEditing(null)
    },
  })

  const archiveMutation = useMutation({
    mutationFn: archiveApplication,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['applications'] })
      await refreshApplications()
    },
  })

  const restoreMutation = useMutation({
    mutationFn: restoreApplication,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['applications'] })
      await refreshApplications()
    },
  })

  const rows = useMemo(() => data ?? [], [data])
  const saving = createMutation.isPending || updateMutation.isPending

  return (
    <div className="p-6">
      <PageHeader
        title={<span className="flex items-center gap-2"><Layers className="w-5 h-5 text-blue-500" />应用管理</span>}
        description="管理租户下的所有投放对象。每个应用独立绑定广告账号、归因配置、成员权限。"
        action={
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={includeArchived}
                onChange={e => setIncludeArchived(e.target.checked)}
                className="rounded border-gray-300"
              />
              显示归档
            </label>
            <button
              onClick={() => setCreating(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700"
            >
              <Plus className="w-4 h-4" />
              新建应用
            </button>
          </div>
        }
      />

      <div className="mb-4">
        <QuotaUsageCard />
      </div>

      <SectionCard title={`应用列表（${rows.length}）`} noPadding>
        {isLoading && (
          <div className="flex items-center justify-center py-10 text-gray-400 text-sm">
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            加载中…
          </div>
        )}
        {isError && (
          <div className="flex items-center justify-center py-10 text-sm text-red-500">
            <AlertCircle className="w-4 h-4 mr-2" />
            加载失败
            <button onClick={() => refetch()} className="ml-2 underline">重试</button>
          </div>
        )}
        {!isLoading && !isError && rows.length === 0 && (
          <div className="text-center py-12 text-sm text-gray-400">
            尚未创建任何应用，点击右上角"新建应用"开始。
          </div>
        )}
        {!isLoading && !isError && rows.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-gray-50/60">
              <tr className="text-left text-xs text-gray-500">
                <th className="px-5 py-3 font-medium">应用</th>
                <th className="px-3 py-3 font-medium">slug</th>
                <th className="px-3 py-3 font-medium">平台</th>
                <th className="px-3 py-3 font-medium">行业</th>
                <th className="px-3 py-3 font-medium">状态</th>
                <th className="px-3 py-3 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(app => {
                const isCurrent = currentApplication?.id === app.id
                return (
                  <tr key={app.id} className="border-t border-gray-100 hover:bg-blue-50/30">
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          className="font-medium text-gray-900 hover:text-blue-600"
                          onClick={() => navigate(`/applications/${app.id}`)}
                        >
                          {app.name}
                        </button>
                        {app.is_default && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">默认</span>
                        )}
                        {isCurrent && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 flex items-center gap-0.5">
                            <Check className="w-2.5 h-2.5" />
                            当前
                          </span>
                        )}
                      </div>
                      {app.description && (
                        <div className="text-xs text-gray-400 mt-0.5 max-w-md truncate">
                          {app.description}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-3 text-gray-500 font-mono text-xs">{app.slug}</td>
                    <td className="px-3 py-3 text-gray-600">{PLATFORM_LABEL[app.platform_type] ?? app.platform_type}</td>
                    <td className="px-3 py-3 text-gray-600">{app.industry || '—'}</td>
                    <td className="px-3 py-3">
                      <span className={cn(
                        'text-xs px-2 py-0.5 rounded-full',
                        app.status === 'active'
                          ? 'bg-green-100 text-green-700'
                          : 'bg-gray-100 text-gray-500',
                      )}>
                        {app.status === 'active' ? '正常' : '已归档'}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right">
                      <div className="inline-flex items-center gap-1">
                        <button
                          onClick={() => setEditing(app)}
                          className="p-1.5 rounded text-gray-400 hover:bg-gray-100 hover:text-blue-600"
                          title="编辑"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        {app.status === 'active' ? (
                          <button
                            onClick={() => {
                              if (app.is_default) {
                                alert('默认应用不能归档。如需调整默认归属，请联系平台管理员。')
                                return
                              }
                              if (confirm(`确定要归档应用 "${app.name}" 吗？归档后不会被删除，可在"显示归档"中恢复。`)) {
                                archiveMutation.mutate(app.id)
                              }
                            }}
                            className="p-1.5 rounded text-gray-400 hover:bg-amber-50 hover:text-amber-600"
                            title="归档"
                            disabled={app.is_default}
                          >
                            <Archive className="w-3.5 h-3.5" />
                          </button>
                        ) : (
                          <button
                            onClick={() => restoreMutation.mutate(app.id)}
                            className="p-1.5 rounded text-gray-400 hover:bg-green-50 hover:text-green-600"
                            title="恢复"
                          >
                            <RotateCcw className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </SectionCard>

      {creating && (
        <ApplicationFormDialog
          onClose={() => setCreating(false)}
          onSubmit={data => createMutation.mutate(data)}
          saving={saving}
        />
      )}
      {editing && (
        <ApplicationFormDialog
          initial={editing}
          onClose={() => setEditing(null)}
          onSubmit={payload => updateMutation.mutate({ id: editing.id, payload })}
          saving={saving}
        />
      )}
    </div>
  )
}
