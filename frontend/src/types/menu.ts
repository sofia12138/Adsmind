import type { LucideIcon } from 'lucide-react'

export interface MenuItem {
  id: string
  label: string
  icon?: LucideIcon
  path?: string
  /** 独立工具入口，在新标签页打开。 */
  externalUrl?: string
  children?: MenuItem[]
  panelKey?: string
  /** 平台内部管理入口，不向客户团队展示。 */
  internalOnly?: boolean
  /**
   * 阶段 3：业务插件 key。
   * 若提供，则该菜单项还要求当前租户启用该插件（AuthContext.hasPlugin）。
   * 与 panelKey 是 AND 关系：两者都通过才显示。
   */
  pluginKey?: string
}

export const ROLE_LABELS: Record<string, string> = {
  super_admin: '超级管理员',
  admin: '管理员',
  optimizer: '投放人员',
  designer: '设计师',
  analyst: '分析人员',
  viewer: '访客',
}
