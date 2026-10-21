import { useState, useRef, useMemo, useCallback } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { DateRangeFilter, getDefaultDateRange, type DateRange } from '@/components/common/DateRangeFilter'
import {
  Loader2, AlertCircle, Film, ImageIcon, ChevronLeft, ChevronRight,
  Upload, Eye, MoreHorizontal, Copy, Download, Pencil, Play,
  FileVideo, FileImage, TrendingUp,
} from 'lucide-react'
import { useVideos, useImages } from '@/hooks/use-creatives'
import type { VideoItem, ImageItem } from '@/services/creatives'

const PAGE_SIZE = 20
type Tab = 'videos' | 'images'
const PAGE_SIZE_OPTIONS = [10, 20, 50]

function inRange(createTime: string | undefined, range: DateRange): boolean {
  if (!createTime) return true
  const d = createTime.slice(0, 10)
  return d >= range.startDate && d <= range.endDate
}

function isThisWeek(createTime: string | undefined): boolean {
  if (!createTime) return false
  const now = new Date()
  const dayOfWeek = now.getDay() || 7
  const monday = new Date(now)
  monday.setDate(now.getDate() - dayOfWeek + 1)
  monday.setHours(0, 0, 0, 0)
  return new Date(createTime) >= monday
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).then(
    () => { /* success */ },
    () => { /* fallback: do nothing */ },
  )
}

// ── Thumbnail ──
function MaterialThumbnail({ url, type, alt }: { url?: string; type: 'video' | 'image'; alt?: string }) {
  const [err, setErr] = useState(false)
  const Icon = type === 'video' ? Film : ImageIcon

  if (!url || err) {
    return (
      <div className="w-16 h-16 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0">
        <Icon className="w-6 h-6 text-gray-300" />
      </div>
    )
  }

  return type === 'image' ? (
    <img src={url} alt={alt ?? ''} onError={() => setErr(true)}
      className="w-16 h-16 rounded-lg object-cover flex-shrink-0 bg-gray-100" />
  ) : (
    <div className="relative w-16 h-16 rounded-lg overflow-hidden bg-gray-900 flex items-center justify-center flex-shrink-0">
      <video src={url} className="absolute inset-0 w-full h-full object-cover" muted preload="metadata"
        onError={() => setErr(true)} />
      <Play className="w-5 h-5 text-white/80 relative z-10 drop-shadow" />
    </div>
  )
}

// ── Action dropdown ──
function ActionMenu({ previewUrl, itemId, onPreview }: {
  previewUrl?: string; itemId: string; onPreview?: () => void
}) {
  const [open, setOpen] = useState(false)
  const closeTimer = useRef<ReturnType<typeof setTimeout>>(null)

  const enter = () => { if (closeTimer.current) clearTimeout(closeTimer.current); setOpen(true) }
  const leave = () => { closeTimer.current = setTimeout(() => setOpen(false), 150) }

  return (
    <div className="flex items-center gap-1">
      {previewUrl ? (
        <a href={previewUrl} target="_blank" rel="noreferrer" onClick={onPreview}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-blue-600 bg-blue-50 rounded-md hover:bg-blue-100 transition">
          <Eye className="w-3.5 h-3.5" /> 预览
        </a>
      ) : (
        <span className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs text-gray-300 bg-gray-50 rounded-md cursor-not-allowed">
          <Eye className="w-3.5 h-3.5" /> 预览
        </span>
      )}

      <div className="relative" onMouseEnter={enter} onMouseLeave={leave}>
        <button onClick={() => setOpen(v => !v)}
          className="p-1.5 rounded-md text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition">
          <MoreHorizontal className="w-4 h-4" />
        </button>
        {open && (
          <div className="absolute right-0 top-full mt-1 w-36 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-50">
            <button onClick={() => { copyToClipboard(itemId); setOpen(false) }}
              className="flex items-center gap-2 w-full px-3 py-2 text-xs text-gray-600 hover:bg-gray-50 transition">
              <Copy className="w-3.5 h-3.5" /> 复制素材 ID
            </button>
            {previewUrl && (
              <a href={previewUrl} download className="flex items-center gap-2 w-full px-3 py-2 text-xs text-gray-600 hover:bg-gray-50 transition"
                onClick={() => setOpen(false)}>
                <Download className="w-3.5 h-3.5" /> 下载
              </a>
            )}
            <button onClick={() => { setOpen(false) }}
              className="flex items-center gap-2 w-full px-3 py-2 text-xs text-gray-400 hover:bg-gray-50 transition cursor-not-allowed">
              <Pencil className="w-3.5 h-3.5" /> 重命名
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Stats cards ──
function StatsCards({ totalVideos, totalImages, thisWeekCount }: {
  totalVideos: number; totalImages: number; thisWeekCount: number
}) {
  const cards = [
    { label: '素材总数', value: totalVideos + totalImages, icon: FileVideo, color: 'text-blue-600 bg-blue-50' },
    { label: '视频', value: totalVideos, icon: Film, color: 'text-violet-600 bg-violet-50' },
    { label: '图片', value: totalImages, icon: FileImage, color: 'text-emerald-600 bg-emerald-50' },
    { label: '本周新增', value: thisWeekCount, icon: TrendingUp, color: 'text-amber-600 bg-amber-50' },
  ]
  return (
    <div className="grid grid-cols-4 gap-3 mb-5">
      {cards.map(c => (
        <div key={c.label} className="flex items-center gap-3 px-4 py-3 bg-white rounded-xl border border-gray-100">
          <div className={`p-2 rounded-lg ${c.color}`}><c.icon className="w-4 h-4" /></div>
          <div>
            <div className="text-lg font-semibold text-gray-800 leading-tight">{c.value}</div>
            <div className="text-xs text-gray-400">{c.label}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ══════════════════════════════════ Main ══════════════════════════════════

export default function CreativesPage() {
  const [searchParams] = useSearchParams()
  const adFilter = searchParams.get('ad')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [tab, setTab] = useState<Tab>('videos')
  const [vPage, setVPage] = useState(1)
  const [iPage, setIPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE)
  const [dateRange, setDateRange] = useState<DateRange>(() => getDefaultDateRange('30d'))

  const { data: vData, isLoading: vLoading, isError: vError } = useVideos(vPage, pageSize)
  const { data: iData, isLoading: iLoading, isError: iError } = useImages(iPage, pageSize)

  const filteredVideos = useMemo(() =>
    (vData?.list ?? []).filter(v => inRange(v.create_time, dateRange)),
  [vData, dateRange])

  const filteredImages = useMemo(() =>
    (iData?.list ?? []).filter(v => inRange(v.create_time, dateRange)),
  [iData, dateRange])

  const thisWeekCount = useMemo(() => {
    const vw = (vData?.list ?? []).filter(v => isThisWeek(v.create_time)).length
    const iw = (iData?.list ?? []).filter(v => isThisWeek(v.create_time)).length
    return vw + iw
  }, [vData, iData])

  function handleUploadClick() { fileInputRef.current?.click() }
  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      alert(`已选择 ${e.target.files.length} 个文件，上传功能即将上线`)
      e.target.value = ''
    }
  }

  const handlePageSizeChange = useCallback((newSize: number) => {
    setPageSize(newSize)
    setVPage(1)
    setIPage(1)
  }, [])

  const isLoading = tab === 'videos' ? vLoading : iLoading
  const isError = tab === 'videos' ? vError : iError
  const currentList = tab === 'videos' ? filteredVideos : filteredImages
  const currentPage = tab === 'videos' ? vPage : iPage
  const total = tab === 'videos' ? (vData?.total ?? 0) : (iData?.total ?? 0)
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const setPage = tab === 'videos' ? setVPage : setIPage

  // ── Table columns (unified for both video & image) ──
  const COLS = [
    { key: 'thumb', label: '缩略图', w: 'w-20' },
    { key: 'info', label: '素材信息', w: '' },
    { key: 'spec', label: '规格信息', w: 'w-36' },
    { key: 'time', label: '上传时间', w: 'w-28' },
    { key: 'action', label: '操作', w: 'w-36' },
  ] as const

  function renderVideoRow(r: VideoItem) {
    const id = r.video_id
    const url = r.preview_url
    const spec = [r.width && r.height ? `${r.width}×${r.height}` : null, r.format].filter(Boolean).join(' · ')
    return (
      <tr key={id} className="group border-b border-gray-50 last:border-0 hover:bg-blue-50/40 transition-colors">
        <td className="px-4 py-3">
          <MaterialThumbnail url={url} type="video" alt={r.file_name} />
        </td>
        <td className="px-4 py-3">
          <div className="font-medium text-sm text-gray-800 truncate max-w-xs" title={r.file_name ?? id}>
            {r.file_name || id}
          </div>
          <div className="text-[11px] text-gray-400 font-mono mt-0.5 truncate" title={id}>{id}</div>
        </td>
        <td className="px-4 py-3">
          <span className="text-xs text-gray-500">{spec || '-'}</span>
        </td>
        <td className="px-4 py-3">
          <span className="text-xs text-gray-500">{r.create_time ? r.create_time.slice(0, 10) : '-'}</span>
        </td>
        <td className="px-4 py-3">
          <ActionMenu previewUrl={url} itemId={id} />
          <Link to={`/distribution/youtube?${new URLSearchParams({ material_id: id, file_name: r.file_name || '' })}`} className="inline-block mt-2 text-xs text-blue-600">去发行</Link>
        </td>
      </tr>
    )
  }

  function renderImageRow(r: ImageItem) {
    const id = r.image_id || r.id || '-'
    const url = r.url || r.preview_url
    const spec = [r.width && r.height ? `${r.width}×${r.height}` : null, r.format].filter(Boolean).join(' · ')
    return (
      <tr key={id} className="group border-b border-gray-50 last:border-0 hover:bg-blue-50/40 transition-colors">
        <td className="px-4 py-3">
          <MaterialThumbnail url={url} type="image" alt={r.file_name} />
        </td>
        <td className="px-4 py-3">
          <div className="font-medium text-sm text-gray-800 truncate max-w-xs" title={r.file_name ?? id}>
            {r.file_name || id}
          </div>
          <div className="text-[11px] text-gray-400 font-mono mt-0.5 truncate" title={id}>{id}</div>
        </td>
        <td className="px-4 py-3">
          <span className="text-xs text-gray-500">{spec || '-'}</span>
        </td>
        <td className="px-4 py-3">
          <span className="text-xs text-gray-500">{r.create_time ? r.create_time.slice(0, 10) : '-'}</span>
        </td>
        <td className="px-4 py-3">
          <ActionMenu previewUrl={url} itemId={id} />
        </td>
      </tr>
    )
  }

  return (
    <div className="max-w-7xl mx-auto">
      <PageHeader title="素材库" description={adFilter ? `Ad: ${adFilter}` : '管理和查看广告素材'} />

      {/* ── 时间筛选 + Tab 切换（同行, 时间筛选不动） ── */}
      <div className="flex flex-wrap items-center gap-4 mb-5">
        <DateRangeFilter value={dateRange} onChange={setDateRange} />

        <div className="ml-auto flex items-center gap-3">
          <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
            <button onClick={() => setTab('videos')}
              className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-sm transition-all ${
                tab === 'videos'
                  ? 'bg-white text-gray-800 font-medium shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}>
              <Film className="w-4 h-4" /> 视频素材
            </button>
            <button onClick={() => setTab('images')}
              className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-sm transition-all ${
                tab === 'images'
                  ? 'bg-white text-gray-800 font-medium shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}>
              <ImageIcon className="w-4 h-4" /> 图片素材
            </button>
          </div>

          <input ref={fileInputRef} type="file" multiple accept="video/*,image/*" className="hidden" onChange={handleFileChange} />
          <button onClick={handleUploadClick}
            className="flex items-center gap-1.5 px-4 py-2 bg-blue-500 text-white text-sm font-medium rounded-lg hover:bg-blue-600 shadow-sm hover:shadow transition-all">
            <Upload className="w-4 h-4" /> 上传素材
          </button>
        </div>
      </div>

      {/* ── 统计卡片 ── */}
      <StatsCards
        totalVideos={vData?.total ?? filteredVideos.length}
        totalImages={iData?.total ?? filteredImages.length}
        thisWeekCount={thisWeekCount}
      />

      {/* ── Loading / Error ── */}
      {isLoading && (
        <div className="flex items-center justify-center py-32 text-gray-400">
          <Loader2 className="w-6 h-6 animate-spin mr-2" /><span className="text-sm">加载中...</span>
        </div>
      )}
      {isError && (
        <div className="flex flex-col items-center justify-center py-24 text-red-400">
          <AlertCircle className="w-8 h-8 mb-2" />
          <p className="text-sm font-medium">素材加载失败</p>
          <p className="text-xs mt-1 text-gray-400">请检查 API 配置</p>
        </div>
      )}

      {/* ── 列表区 ── */}
      {!isLoading && !isError && (
        <>
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50/60">
                    {COLS.map(c => (
                      <th key={c.key}
                        className={`px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider ${c.w}`}>
                        {c.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {currentList.length === 0 ? (
                    <tr>
                      <td colSpan={COLS.length} className="px-4 py-16 text-center text-gray-300 text-sm">
                        暂无{tab === 'videos' ? '视频' : '图片'}素材
                      </td>
                    </tr>
                  ) : (
                    tab === 'videos'
                      ? filteredVideos.map(renderVideoRow)
                      : filteredImages.map(renderImageRow)
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* ── 分页 ── */}
          <div className="flex items-center justify-between mt-4 px-1 pb-6">
            <div className="flex items-center gap-3 text-xs text-gray-400">
              <span>共 <span className="font-medium text-gray-600">{total}</span> 条</span>
              <span className="text-gray-200">|</span>
              <span>第 {currentPage}/{totalPages} 页</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1 text-xs text-gray-400">
                <span>每页</span>
                <select value={pageSize} onChange={e => handlePageSizeChange(Number(e.target.value))}
                  className="border border-gray-200 rounded-md px-2 py-1 text-xs text-gray-600 bg-white focus:outline-none focus:ring-1 focus:ring-blue-300">
                  {PAGE_SIZE_OPTIONS.map(n => <option key={n} value={n}>{n}</option>)}
                </select>
                <span>条</span>
              </div>
              <div className="flex items-center gap-1">
                <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={currentPage <= 1}
                  className="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-30 transition">
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <span className="text-xs text-gray-500 min-w-[40px] text-center font-medium">{currentPage}</span>
                <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={currentPage >= totalPages}
                  className="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-30 transition">
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
