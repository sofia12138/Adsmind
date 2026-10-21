import { ExternalLink, Film } from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { cutflowUrl } from '@/services/cutflow'

export default function AutoEditPage() {
  return <div className="max-w-3xl mx-auto">
    <PageHeader title="自动剪辑" description="使用 CutFlow 剪流制作短剧推广素材" />
    <div className="bg-white border rounded-xl p-8 space-y-5">
      <Film className="w-9 h-9 text-blue-600" />
      <div><h2 className="text-lg font-semibold">CutFlow 剪流</h2>
        <p className="text-sm text-gray-500 mt-2">导入剧集，选择剪辑模板，生成方案并审核导出成片。</p></div>
      {cutflowUrl ? <a href={cutflowUrl} target="_blank" rel="noopener noreferrer"
        className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
        打开 CutFlow<ExternalLink className="w-4 h-4" />
      </a> : <p role="status" className="text-sm text-amber-700">自动剪辑入口尚未配置，请联系管理员设置 CutFlow 访问地址。</p>}
      <p className="text-xs text-gray-500">成片导出后，可在 AdsMind 上传素材并创建广告。</p>
    </div>
  </div>
}
