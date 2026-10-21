import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CheckCircle2, Clock3, FileLock2, Loader2, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { useAuth } from '@/contexts/AuthContext'
import { listAdCreationDrafts } from '@/services/ad-creation-drafts'

export default function AdCreationDraftsPage() {
  const { currentApplication } = useAuth()
  const drafts = useQuery({
    queryKey: ['ad-creation-drafts', currentApplication?.id],
    queryFn: listAdCreationDrafts,
  })
  return <div className="mx-auto max-w-6xl">
    <PageHeader title="应用广告草稿" description="组合当前应用的账户组、命名规则与创意组；这里只生成内部准备快照，不会连接平台创建、上传或预审核。" action={<Link to="/ads/app-drafts/new" className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white"><Plus className="h-4 w-4" />新建草稿</Link>} />
    <SectionCard title={`草稿（${drafts.data?.length ?? 0}）`} noPadding>
      {drafts.isLoading && <div className="py-16 text-center text-gray-400"><Loader2 className="mx-auto h-5 w-5 animate-spin" /></div>}
      {!drafts.isLoading && !drafts.data?.length && <div className="py-16 text-center text-sm text-gray-400">当前应用还没有广告创建草稿</div>}
      {drafts.data?.map(draft => <Link key={draft.id} to={`/ads/app-drafts/${draft.id}`} className="flex items-center gap-4 border-b border-gray-100 px-5 py-4 last:border-0 hover:bg-gray-50">
        <div className={`rounded-xl p-2.5 ${draft.status === 'READY' ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'}`}>{draft.status === 'READY' ? <FileLock2 className="h-5 w-5" /> : <Clock3 className="h-5 w-5" />}</div>
        <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><span className="font-medium text-gray-900">{draft.title}</span>{draft.status === 'READY' && <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700"><CheckCircle2 className="h-3 w-3" />准备就绪</span>}</div><p className="mt-1 text-xs text-gray-400">{draft.resolved_accounts.length} 个账户 · {draft.creative_snapshot.materials.length} 条素材 · revision {draft.revision}</p>{draft.blocking_reasons.length > 0 && <p className="mt-1 text-xs text-amber-700">阻断：{draft.blocking_reasons.map(item => item.message).join('；')}</p>}</div>
        <ArrowRight className="h-4 w-4 text-gray-300" />
      </Link>)}
    </SectionCard>
  </div>
}
