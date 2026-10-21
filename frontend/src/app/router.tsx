/* eslint-disable react-refresh/only-export-components -- router config intentionally owns small route elements */
import { createBrowserRouter, Navigate, useLocation } from 'react-router-dom'
import { MainLayout } from '@/components/layout/main-layout'
import { AuthGuard } from '@/components/auth/AuthGuard'

import LoginPage from '@/pages/LoginPage'
import RegisterPage from '@/pages/RegisterPage'
import ResetPasswordPage from '@/pages/ResetPasswordPage'
import InvitationAcceptPage from '@/pages/InvitationAcceptPage'
import ForbiddenPage from '@/pages/ForbiddenPage'
import TeamPage from '@/pages/TeamPage'
import UpgradeRequestsPage from '@/pages/UpgradeRequestsPage'
import VerifyEmailPage from '@/pages/VerifyEmailPage'
import DashboardPage from '@/pages/DashboardPage'
import OpsDashboard from '@/pages/ops/OpsDashboard'
import AdsPage from '@/pages/AdsPage'
import TikTokConsolePage from '@/pages/TikTokConsolePage'
import MetaConsolePage from '@/pages/MetaConsolePage'
import AdsCreatePage from '@/pages/AdsCreatePage'
import LaunchDraftsPage from '@/pages/LaunchDraftsPage'
import TemplatesPage from '@/pages/TemplatesPage'
import DistributionPage from '@/pages/DistributionPage'
import MaterialCatalogPage from '@/features/material-catalog/MaterialCatalogPage'
import AutoEditPage from '@/pages/AutoEditPage'
import CreativeAnalysisPage from '@/pages/CreativeAnalysisPage'
import OverviewPage from '@/pages/OverviewPage'
import ChannelAnalysisPage from '@/pages/ChannelAnalysisPage'
import BizAnalysisPage from '@/pages/BizAnalysisPage'
import DataComparePage from '@/pages/DataComparePage'
import DataSourcePage from '@/pages/DataSourcePage'
import UserMgmtPage from '@/pages/UserMgmtPage'
import RolePermPage from '@/pages/RolePermPage'
import InsightConfigPage from '@/pages/InsightConfigPage'
import OplogPage from '@/pages/OplogPage'
import ReturnedConversionPage from '@/pages/ReturnedConversionPage'
import DramaOverviewPage from '@/pages/DramaOverviewPage'
import DesignerPerformancePage from '@/pages/DesignerPerformancePage'
import OptimizerPerformancePage from '@/pages/OptimizerPerformancePage'
import OptimizerDirectoryPage from '@/pages/OptimizerDirectoryPage'
import AssetLandingPagesPage from '@/pages/AssetLandingPagesPage'
import AssetCopyPacksPage from '@/pages/AssetCopyPacksPage'
import AssetRegionGroupsPage from '@/pages/AssetRegionGroupsPage'
import TikTokMaterialsPage from '@/pages/TikTokMaterialsPage'
import ApplicationsListPage from '@/pages/ApplicationsListPage'
import ApplicationDetailPage from '@/pages/ApplicationDetailPage'
import IntegrationsPage from '@/pages/IntegrationsPage'
import PlatformAuthorizationPage from '@/pages/PlatformAuthorizationPage'
import DramaCatalogPage from '@/features/drama-catalog/DramaCatalogPage'
import AccountGroupsPage from '@/pages/AccountGroupsPage'
import NamingRulesPage from '@/pages/NamingRulesPage'
import CreativeGroupsPage from '@/pages/CreativeGroupsPage'
import AdCreationDraftsPage from '@/pages/AdCreationDraftsPage'
import AdCreationDraftNewPage from '@/pages/AdCreationDraftNewPage'
import AdCreationDraftDetailPage from '@/pages/AdCreationDraftDetailPage'
import PlatformPreflightPage from '@/pages/PlatformPreflightPage'
import AutomationRulesPage from '@/pages/AutomationRulesPage'
import ReadinessAnalyticsPage from '@/pages/ReadinessAnalyticsPage'
import AssetAnalysisPage from '@/pages/AssetAnalysisPage'
import {
  preservedDirectRoutes,
  redirectWithSearch,
  type PreservedDirectRoutePath,
} from './navigation-contract'

function G({ panelKey, children }: { panelKey: string; children: React.ReactNode }) {
  return <AuthGuard panelKey={panelKey}>{children}</AuthGuard>
}

/** 保留 query string 的 redirect，用于旧链接兼容 */
function RedirectKeepQuery({ to }: { to: string }) {
  const loc = useLocation()
  return <Navigate to={redirectWithSearch(to, loc.search)} replace />
}

const preservedDirectRouteElements: Record<PreservedDirectRoutePath, React.ReactNode> = {
  'ads/drafts': <LaunchDraftsPage />,
  'ads/platform-preflight': <PlatformPreflightPage />,
  templates: <TemplatesPage />,
  'tiktok-materials': <TikTokMaterialsPage />,
  'asset-analysis': <AssetAnalysisPage />,
}

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/register', element: <RegisterPage /> },
  { path: '/reset-password', element: <ResetPasswordPage /> },
  { path: '/invitation/:token', element: <InvitationAcceptPage /> },
  { path: '/verify-email/:token', element: <VerifyEmailPage /> },
  {
    path: '/',
    element: <MainLayout />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'forbidden', element: <ForbiddenPage /> },
      { path: 'dashboard',          element: <G panelKey="dashboard"><DashboardPage /></G> },
      { path: 'dashboard/ops',      element: <G panelKey="ops_dashboard"><OpsDashboard /></G> },
      { path: 'ads',                element: <G panelKey="ads_data"><AdsPage /></G> },
      { path: 'console/tiktok',     element: <G panelKey="tiktok_console"><TikTokConsolePage /></G> },
      { path: 'console/meta',       element: <G panelKey="meta_console"><MetaConsolePage /></G> },
      { path: 'ads/app-drafts', element: <G panelKey="ad_creation_drafts"><AdCreationDraftsPage /></G> },
      { path: 'ads/app-drafts/new', element: <G panelKey="ad_creation_drafts"><AdCreationDraftNewPage /></G> },
      { path: 'ads/app-drafts/:id', element: <G panelKey="ad_creation_drafts"><AdCreationDraftDetailPage /></G> },
      { path: 'ads/automation-rules', element: <G panelKey="automation_rules"><AutomationRulesPage /></G> },
      { path: 'ads/readiness', element: <G panelKey="platform_preflight"><ReadinessAnalyticsPage /></G> },
      { path: 'ads/create',         element: <G panelKey="ad_create"><AdsCreatePage /></G> },
      // 旧链接兼容：保留 ?template_id= 透传，重定向到统一新建广告页
      { path: 'ads/create-tiktok-minis', element: <RedirectKeepQuery to="/ads/create" /> },
      ...preservedDirectRoutes.map(route => ({
        path: route.path,
        element: <G panelKey={route.panelKey}>{preservedDirectRouteElements[route.path]}</G>,
      })),
      { path: 'drama-catalog',      element: <G panelKey="creatives"><DramaCatalogPage /></G> },
      { path: 'creatives',          element: <G panelKey="creatives"><MaterialCatalogPage /></G> },
      { path: 'materials/upload',    element: <G panelKey="creatives"><MaterialCatalogPage openUpload /></G> },
      { path: 'creative-groups',     element: <G panelKey="creative_groups"><CreativeGroupsPage /></G> },
      { path: 'auto-edit',          element: <G panelKey="creatives"><AutoEditPage /></G> },
      { path: 'distribution/youtube', element: <G panelKey="creatives"><DistributionPage section="tasks" /></G> },
      { path: 'distribution/records', element: <G panelKey="creatives"><DistributionPage section="records" /></G> },
      { path: 'distribution/channels', element: <G panelKey="creatives"><DistributionPage section="channels" /></G> },
      { path: 'creative-analysis',  element: <G panelKey="creative_analysis"><CreativeAnalysisPage /></G> },
      { path: 'overview',           element: <G panelKey="overview"><OverviewPage /></G> },
      { path: 'channel-analysis',   element: <G panelKey="channel_analysis"><ChannelAnalysisPage /></G> },
      { path: 'biz-analysis',         element: <G panelKey="biz_analysis"><BizAnalysisPage /></G> },
      { path: 'returned-conversion', element: <G panelKey="returned_conversion"><ReturnedConversionPage /></G> },
      { path: 'drama-analysis',          element: <G panelKey="drama_analysis"><DramaOverviewPage /></G> },
      { path: 'designer-performance',    element: <G panelKey="designer_performance"><DesignerPerformancePage /></G> },
      { path: 'optimizer-performance',   element: <G panelKey="optimizer_performance"><OptimizerPerformancePage /></G> },
      { path: 'data-compare',        element: <G panelKey="data_compare"><DataComparePage /></G> },
      { path: 'data-source',        element: <G panelKey="data_source"><DataSourcePage /></G> },
      { path: 'user-mgmt',          element: <G panelKey="user_mgmt"><UserMgmtPage /></G> },
      { path: 'role-perm',          element: <G panelKey="role_perm"><RolePermPage /></G> },
      { path: 'insight-config',    element: <G panelKey="insight_config"><InsightConfigPage /></G> },
      { path: 'oplog',              element: <G panelKey="oplog"><OplogPage /></G> },
      { path: 'optimizer-directory', element: <G panelKey="optimizer_directory"><OptimizerDirectoryPage /></G> },
      { path: 'assets/landing-pages', element: <G panelKey="asset_landing_pages"><AssetLandingPagesPage /></G> },
      { path: 'assets/copy-packs',    element: <G panelKey="asset_copy_packs"><AssetCopyPacksPage /></G> },
      { path: 'assets/region-groups', element: <G panelKey="asset_region_groups"><AssetRegionGroupsPage /></G> },
      { path: 'applications',           element: <G panelKey="applications"><ApplicationsListPage /></G> },
      { path: 'applications/:id',       element: <G panelKey="applications"><ApplicationDetailPage /></G> },
      { path: 'settings/integrations',  element: <G panelKey="applications"><IntegrationsPage /></G> },
      { path: 'settings/integrations/tiktok/complete', element: <G panelKey="applications"><PlatformAuthorizationPage key="tiktok" platform="tiktok" /></G> },
      { path: 'settings/integrations/meta/complete', element: <G panelKey="applications"><PlatformAuthorizationPage key="meta" platform="meta" /></G> },
      { path: 'settings/account-groups', element: <G panelKey="account_groups"><AccountGroupsPage /></G> },
      { path: 'settings/naming-rules', element: <G panelKey="naming_rules"><NamingRulesPage /></G> },
      { path: 'team',                   element: <G panelKey="team"><TeamPage /></G> },
      { path: 'upgrade-requests',       element: <G panelKey="user_mgmt"><UpgradeRequestsPage /></G> },
    ],
  },
])
