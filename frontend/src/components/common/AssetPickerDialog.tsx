import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, X, Loader2, CheckCircle, Link2, FileText, Globe } from 'lucide-react'
import {
  fetchLandingPages, fetchCopyPacks, fetchRegionGroups,
  type LandingPageAsset, type CopyPackAsset, type RegionGroupAsset,
} from '@/services/ad-assets'

interface BaseProps {
  open: boolean
  onClose: () => void
}

/* ═══ Landing Page Picker ═══ */

interface LandingPagePickerProps extends BaseProps {
  onSelect: (item: LandingPageAsset) => void
}

export function LandingPagePickerDialog({ open, onClose, onSelect }: LandingPagePickerProps) {
  const [kw, setKw] = useState('')
  const { data: list = [], isLoading } = useQuery({
    queryKey: ['asset-landing-pages-picker', kw],
    queryFn: () => fetchLandingPages({ status: 'active', keyword: kw || undefined }),
    enabled: open,
    staleTime: 30_000,
  })

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl mx-4 overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-800">从推广链接选择</h3>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-400" /></button>
        </div>
        <div className="px-6 py-3 border-b border-gray-50">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input type="text" placeholder="搜索名称、URL、产品..." className="w-full pl-10 pr-4 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-100" value={kw} onChange={e => setKw(e.target.value)} />
          </div>
        </div>
        <div className="max-h-[50vh] overflow-y-auto">
          {isLoading && (
            <div className="flex items-center justify-center py-12 text-gray-400"><Loader2 className="w-5 h-5 animate-spin mr-2" /><span className="text-sm">加载中...</span></div>
          )}
          {!isLoading && list.length === 0 && (
            <div className="py-12 text-center text-sm text-gray-300">暂无可用推广链接</div>
          )}
          {!isLoading && list.map(item => (
            <button key={item.id} onClick={() => { onSelect(item); onClose() }}
              className="w-full text-left px-6 py-3 border-b border-gray-50 hover:bg-blue-50/30 transition-colors flex items-start gap-3 group">
              <Link2 className="w-4 h-4 text-gray-300 mt-0.5 flex-shrink-0 group-hover:text-blue-400" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-gray-800">{item.name}</div>
                <div className="text-xs text-gray-400 truncate mt-0.5">{item.landing_page_url}</div>
                <div className="flex gap-3 mt-1 text-xs text-gray-400">
                  {item.product_name && <span>产品: {item.product_name}</span>}
                  {item.channel && <span>渠道: {item.channel}</span>}
                  {item.language && <span>语言: {item.language}</span>}
                </div>
              </div>
              <CheckCircle className="w-4 h-4 text-transparent group-hover:text-blue-400 flex-shrink-0 mt-1" />
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ═══ Copy Pack Picker ═══ */

interface CopyPackPickerProps extends BaseProps {
  onSelect: (item: CopyPackAsset, mode: 'all' | 'empty') => void
}

export function CopyPackPickerDialog({ open, onClose, onSelect }: CopyPackPickerProps) {
  const [kw, setKw] = useState('')
  const [selected, setSelected] = useState<CopyPackAsset | null>(null)
  const { data: list = [], isLoading } = useQuery({
    queryKey: ['asset-copy-packs-picker', kw],
    queryFn: () => fetchCopyPacks({ status: 'active', keyword: kw || undefined }),
    enabled: open,
    staleTime: 30_000,
  })

  if (!open) return null

  if (selected) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
        <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 overflow-hidden" onClick={e => e.stopPropagation()}>
          <div className="px-6 py-4 border-b border-gray-100">
            <h3 className="text-lg font-semibold text-gray-800">选择填充方式</h3>
            <p className="text-sm text-gray-400 mt-1">文案包: {selected.name}</p>
          </div>
          <div className="px-6 py-3 space-y-3 text-sm">
            <div className="bg-gray-50 rounded-lg p-3 space-y-1">
              {selected.headline && <div><span className="text-gray-400">Headline: </span><span className="text-gray-700">{selected.headline}</span></div>}
              {selected.primary_text && <div><span className="text-gray-400">Primary Text: </span><span className="text-gray-700 line-clamp-2">{selected.primary_text}</span></div>}
              {selected.description && <div><span className="text-gray-400">Description: </span><span className="text-gray-700">{selected.description}</span></div>}
            </div>
          </div>
          <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-3">
            <button className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50" onClick={() => setSelected(null)}>返回</button>
            <button className="px-4 py-2 text-sm text-white bg-amber-500 rounded-lg hover:bg-amber-600" onClick={() => { onSelect(selected, 'empty'); onClose(); setSelected(null) }}>
              仅填充空白字段
            </button>
            <button className="px-4 py-2 text-sm text-white bg-blue-500 rounded-lg hover:bg-blue-600" onClick={() => { onSelect(selected, 'all'); onClose(); setSelected(null) }}>
              填充全部字段
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl mx-4 overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-800">从文案库选择</h3>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-400" /></button>
        </div>
        <div className="px-6 py-3 border-b border-gray-50">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input type="text" placeholder="搜索名称、文案、标题、产品..." className="w-full pl-10 pr-4 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-100" value={kw} onChange={e => setKw(e.target.value)} />
          </div>
        </div>
        <div className="max-h-[50vh] overflow-y-auto">
          {isLoading && (
            <div className="flex items-center justify-center py-12 text-gray-400"><Loader2 className="w-5 h-5 animate-spin mr-2" /><span className="text-sm">加载中...</span></div>
          )}
          {!isLoading && list.length === 0 && (
            <div className="py-12 text-center text-sm text-gray-300">暂无可用文案包</div>
          )}
          {!isLoading && list.map(item => (
            <button key={item.id} onClick={() => setSelected(item)}
              className="w-full text-left px-6 py-3 border-b border-gray-50 hover:bg-blue-50/30 transition-colors flex items-start gap-3 group">
              <FileText className="w-4 h-4 text-gray-300 mt-0.5 flex-shrink-0 group-hover:text-blue-400" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-gray-800">{item.name}</div>
                {item.headline && <div className="text-xs text-gray-500 mt-0.5 truncate">Headline: {item.headline}</div>}
                {item.primary_text && <div className="text-xs text-gray-400 mt-0.5 line-clamp-1">Text: {item.primary_text}</div>}
                <div className="flex gap-3 mt-1 text-xs text-gray-400">
                  {item.product_name && <span>产品: {item.product_name}</span>}
                  {item.channel && <span>渠道: {item.channel}</span>}
                </div>
              </div>
              <CheckCircle className="w-4 h-4 text-transparent group-hover:text-blue-400 flex-shrink-0 mt-1" />
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ═══ Region Group Picker ═══ */

interface RegionGroupPickerProps extends BaseProps {
  onSelect: (item: RegionGroupAsset) => void
}

export function RegionGroupPickerDialog({ open, onClose, onSelect }: RegionGroupPickerProps) {
  const [kw, setKw] = useState('')
  const { data: list = [], isLoading } = useQuery({
    queryKey: ['asset-region-groups-picker', kw],
    queryFn: () => fetchRegionGroups({ status: 'active', keyword: kw || undefined }),
    enabled: open,
    staleTime: 30_000,
  })

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl mx-4 overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-800">选择地区组</h3>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-400" /></button>
        </div>
        <div className="px-6 py-3 border-b border-gray-50">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input type="text" placeholder="搜索名称..." className="w-full pl-10 pr-4 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-100" value={kw} onChange={e => setKw(e.target.value)} />
          </div>
        </div>
        <div className="max-h-[50vh] overflow-y-auto">
          {isLoading && (
            <div className="flex items-center justify-center py-12 text-gray-400"><Loader2 className="w-5 h-5 animate-spin mr-2" /><span className="text-sm">加载中...</span></div>
          )}
          {!isLoading && list.length === 0 && (
            <div className="py-12 text-center text-sm text-gray-300">暂无可用地区组</div>
          )}
          {!isLoading && list.map(item => (
            <button key={item.id} onClick={() => { onSelect(item); onClose() }}
              className="w-full text-left px-6 py-3 border-b border-gray-50 hover:bg-blue-50/30 transition-colors flex items-start gap-3 group">
              <Globe className="w-4 h-4 text-gray-300 mt-0.5 flex-shrink-0 group-hover:text-blue-400" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-gray-800">{item.name}</div>
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {item.country_codes.slice(0, 15).map(c => (
                    <span key={c} className="inline-block px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 font-mono text-[10px]">{c}</span>
                  ))}
                  {item.country_codes.length > 15 && (
                    <span className="inline-block px-1.5 py-0.5 rounded bg-gray-50 text-gray-400 text-[10px]">+{item.country_codes.length - 15}</span>
                  )}
                </div>
                <div className="flex gap-3 mt-1 text-xs text-gray-400">
                  <span>{item.country_count} 个国家</span>
                  {item.language_hint && <span>语言: {item.language_hint}</span>}
                </div>
              </div>
              <CheckCircle className="w-4 h-4 text-transparent group-hover:text-blue-400 flex-shrink-0 mt-1" />
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
