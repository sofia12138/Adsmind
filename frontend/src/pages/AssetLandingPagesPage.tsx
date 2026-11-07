import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Loader2, AlertCircle, Search, X, Plus, Pencil, Trash2,
  CheckCircle, XCircle, Link2, ExternalLink,
} from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import {
  fetchLandingPages, createLandingPage, updateLandingPage,
  deleteLandingPage, toggleLandingPage,
  type LandingPageAsset,
} from '@/services/ad-assets'

/* ── 表单弹窗 ── */

interface FormDialogProps {
  item?: LandingPageAsset | null
  onClose: () => void
  onSave: (data: Partial<LandingPageAsset>) => void
  saving: boolean
}

function FormDialog({ item, onClose, onSave, saving }: FormDialogProps) {
  const [name, setName] = useState(item?.name || '')
  const [url, setUrl] = useState(item?.landing_page_url || '')
  const [productName, setProductName] = useState(item?.product_name || '')
  const [channel, setChannel] = useState(item?.channel || '')
  const [language, setLanguage] = useState(item?.language || '')
  const [regionTags, setRegionTags] = useState(item?.region_tags?.join(', ') || '')
  const [remark, setRemark] = useState(item?.remark || '')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSave({
      ...(item ? { id: item.id } : {}),
      name: name.trim(),
      landing_page_url: url.trim(),
      product_name: productName.trim(),
      channel: channel.trim(),
      language: language.trim(),
      region_tags: regionTags ? regionTags.split(',').map(s => s.trim()).filter(Boolean) : [],
      remark: remark.trim(),
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="px-6 py-4 border-b border-gray-100">
          <h3 className="text-lg font-semibold text-gray-800">{item ? '编辑推广链接' : '新建推广链接'}</h3>
        </div>
        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4 max-h-[70vh] overflow-y-auto">
          <div>
            <label className="block text-sm font-medium text-gray-600 mb-1">名称 <span className="text-red-400">*</span></label>
            <input type="text" required className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none" value={name} onChange={e => setName(e.target.value)} placeholder="推广链接名称" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-600 mb-1">URL <span className="text-red-400">*</span></label>
            <input type="url" required className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://..." />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-600 mb-1">产品名称</label>
              <input type="text" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none" value={productName} onChange={e => setProductName(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-600 mb-1">渠道</label>
              <input type="text" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none" value={channel} onChange={e => setChannel(e.target.value)} placeholder="meta / tiktok" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-600 mb-1">语言</label>
              <input type="text" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none" value={language} onChange={e => setLanguage(e.target.value)} placeholder="en / zh / ja" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-600 mb-1">地区标签</label>
              <input type="text" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none" value={regionTags} onChange={e => setRegionTags(e.target.value)} placeholder="US, JP, KR" />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-600 mb-1">备注</label>
            <textarea className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 focus:outline-none" rows={2} value={remark} onChange={e => setRemark(e.target.value)} />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50" onClick={onClose}>取消</button>
            <button type="submit" disabled={saving} className="px-4 py-2 text-sm text-white bg-blue-500 rounded-lg hover:bg-blue-600 disabled:opacity-50 flex items-center gap-1.5">
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {item ? '保存' : '创建'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

/* ── 主页面 ── */

export default function AssetLandingPagesPage() {
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [editItem, setEditItem] = useState<LandingPageAsset | null | undefined>(undefined)
  const queryClient = useQueryClient()

  const { data: list = [], isLoading, isError } = useQuery({
    queryKey: ['asset-landing-pages', keyword, statusFilter],
    queryFn: () => fetchLandingPages({ keyword: keyword || undefined, status: statusFilter || undefined }),
    staleTime: 30_000,
  })

  const createMut = useMutation({
    mutationFn: (d: Partial<LandingPageAsset>) => createLandingPage(d),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['asset-landing-pages'] }); setEditItem(undefined) },
  })

  const updateMut = useMutation({
    mutationFn: (d: Partial<LandingPageAsset> & { id: number }) => updateLandingPage(d.id, d),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['asset-landing-pages'] }); setEditItem(undefined) },
  })

  const toggleMut = useMutation({
    mutationFn: (id: number) => toggleLandingPage(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['asset-landing-pages'] }),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteLandingPage(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['asset-landing-pages'] }),
  })

  const handleSave = useCallback((data: Partial<LandingPageAsset>) => {
    if (data.id) {
      updateMut.mutate(data as Partial<LandingPageAsset> & { id: number })
    } else {
      createMut.mutate(data)
    }
  }, [createMut, updateMut])

  return (
    <div className="max-w-7xl mx-auto">
      <PageHeader title="推广链接" description="管理广告投放推广链接 URL，支持在广告创建时快速选择" />

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <button className="text-sm px-3 py-1.5 bg-blue-500 text-white rounded-lg hover:bg-blue-600 flex items-center gap-1.5" onClick={() => setEditItem(null)}>
          <Plus className="w-3.5 h-3.5" />新建推广链接
        </button>
        <div className="relative flex items-center">
          <Search className="absolute left-2.5 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
          <input type="text" placeholder="搜索名称/URL/产品..." className="text-sm border border-gray-200 rounded-lg pl-8 pr-8 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-100 w-56" value={keyword} onChange={e => setKeyword(e.target.value)} />
          {keyword && <button className="absolute right-2 text-gray-300 hover:text-gray-500" onClick={() => setKeyword('')}><X className="w-3.5 h-3.5" /></button>}
        </div>
        <select className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-100" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="">全部状态</option>
          <option value="active">启用</option>
          <option value="inactive">停用</option>
        </select>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-20 text-gray-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /><span className="text-sm">加载中...</span>
        </div>
      )}

      {isError && (
        <div className="flex flex-col items-center justify-center py-16 text-red-400">
          <AlertCircle className="w-8 h-8 mb-2" /><p className="text-sm">数据加载失败</p>
        </div>
      )}

      {!isLoading && !isError && (
        <SectionCard title={`推广链接（${list.length}）`} noPadding>
          {list.length === 0 ? (
            <div className="px-5 py-12 text-center text-sm text-gray-300">暂无推广链接，请点击"新建推广链接"</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">名称</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">URL</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">产品</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">渠道</th>
                    <th className="px-4 py-3 text-center text-xs font-medium text-gray-400">状态</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">创建者</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">更新时间</th>
                    <th className="px-4 py-3 text-center text-xs font-medium text-gray-400">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map(item => (
                    <tr key={item.id} className="border-b border-gray-50 hover:bg-blue-50/20 transition-colors">
                      <td className="px-4 py-3 font-medium text-gray-800 flex items-center gap-1.5">
                        <Link2 className="w-3.5 h-3.5 text-gray-300 flex-shrink-0" />
                        {item.name}
                      </td>
                      <td className="px-4 py-3 text-gray-500 text-xs max-w-[280px] truncate" title={item.landing_page_url}>
                        <a href={item.landing_page_url} target="_blank" rel="noopener noreferrer" className="hover:text-blue-500 inline-flex items-center gap-1">
                          {item.landing_page_url}
                          <ExternalLink className="w-3 h-3 flex-shrink-0" />
                        </a>
                      </td>
                      <td className="px-4 py-3 text-gray-600 text-xs">{item.product_name || '-'}</td>
                      <td className="px-4 py-3 text-gray-600 text-xs">{item.channel || '-'}</td>
                      <td className="px-4 py-3 text-center">
                        {item.status === 'active' ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-green-50 text-green-600"><CheckCircle className="w-3 h-3" />启用</span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-400"><XCircle className="w-3 h-3" />停用</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs">{item.created_by || '-'}</td>
                      <td className="px-4 py-3 text-gray-400 text-xs whitespace-nowrap">{item.updated_at?.slice(0, 16)}</td>
                      <td className="px-4 py-3 text-center">
                        <div className="flex items-center justify-center gap-1">
                          <button className="p-1.5 text-gray-400 hover:text-blue-500 hover:bg-blue-50 rounded-lg transition-colors" title="编辑" onClick={() => setEditItem(item)}><Pencil className="w-3.5 h-3.5" /></button>
                          <button className="p-1.5 text-gray-400 hover:text-amber-500 hover:bg-amber-50 rounded-lg transition-colors" title={item.status === 'active' ? '停用' : '启用'} onClick={() => toggleMut.mutate(item.id)}>
                            {item.status === 'active' ? <XCircle className="w-3.5 h-3.5" /> : <CheckCircle className="w-3.5 h-3.5" />}
                          </button>
                          <button className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors" title="删除" onClick={() => { if (confirm(`确认删除「${item.name}」？`)) deleteMut.mutate(item.id) }}>
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      )}

      {editItem !== undefined && (
        <FormDialog item={editItem} onClose={() => setEditItem(undefined)} onSave={handleSave} saving={createMut.isPending || updateMut.isPending} />
      )}
    </div>
  )
}
