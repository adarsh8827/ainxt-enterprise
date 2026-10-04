// SPDX-License-Identifier: MIT
// Task F-13: admin nav + fail-closed rendering. Gated by the product
// profile's feature flags (never a separate ECOSYSTEM_* flag) -- hiding
// the nav here is a convenience, not the enforcement; every underlying
// call is independently permission-checked server-side regardless of
// whether this screen rendered the button (CONTRACTS.md's own
// allowed_actions philosophy, extended to whole screens for the admin
// surface).
import { ArrowLeftIcon } from "@heroicons/react/24/outline";
import { useHost } from "../lib/context/HostContext";
import { useConfig } from "../lib/hooks/useEcosystemConfig";
import { adminPath } from "../lib/routing";
import { AdminPolicies } from "./AdminPolicies";
import { AdminProvisioning } from "./AdminProvisioning";
import { AdminForceDisable } from "./AdminForceDisable";
import { AdminGateFindings } from "./AdminGateFindings";
import { AdminFeatured } from "./AdminFeatured";
import { AdminSources } from "./AdminSources";
import { AdminOAuthApps } from "./AdminOAuthApps";
const SCREENS = [{
  key: "policies",
  label: "Policies",
  feature: "admin_policies",
  Component: AdminPolicies
}, {
  key: "provisioning",
  label: "Provisioning",
  feature: "provisioning",
  Component: AdminProvisioning
}, {
  key: "force-disable",
  label: "Force disable",
  feature: "admin_policies",
  Component: AdminForceDisable
}, {
  key: "gate-findings",
  label: "Gate findings",
  feature: "gate_dashboard",
  Component: AdminGateFindings
}, {
  key: "featured",
  label: "Featured",
  feature: "admin_policies",
  Component: AdminFeatured
},
// Task 3a: same feature-flag gate as the other admin_sources-permission
// screens above (force-disable/featured) -- no dedicated "sources"
// product feature flag exists, and adding one would need a DB seed
// change on every existing profile for no real benefit over reusing the
// flag every other org-admin screen on this nav already shares.
{
  key: "sources",
  label: "Sources",
  feature: "admin_policies",
  Component: AdminSources
},
// Same reasoning: the backend already independently enforces
// marketplace:admin_policy on every /ecosystem/admin/oauth-apps route
// regardless of whether this tab is visible.
{
  key: "oauth-apps",
  label: "OAuth Apps",
  feature: "admin_policies",
  Component: AdminOAuthApps
}];
export function AdminScreen({
  screen,
  onBack
}) {
  const config = useConfig();
  const { router } = useHost();
  const available = SCREENS.filter(s => config.features[s.feature]);
  if (available.length === 0) {
    return <div data-testid="admin-not-available">Admin screens aren't available for this product.</div>;
  }
  const current = available.find(s => s.key === screen) ?? available[0];
  return <div data-testid="admin-screen">
      {/* UX-06 fix: no way back to the Marketplace catalog from here
          before this -- only the browser's own native Back (which
          happened to work, since every tab click below pushes a real
          history entry) or re-clicking "Marketplace" in the host
          sidebar. A user opening this screen from a bookmark, shared
          link, or new tab had no way back at all. */}
      {onBack && <button type="button" data-testid="admin-back-to-marketplace" onClick={onBack} className="inline-flex items-center gap-1.5 bg-none border-none cursor-pointer text-gray-500 hover:text-gray-700 mb-4 transition-colors">
          <ArrowLeftIcon width={16} height={16} aria-hidden="true" /> Marketplace
        </button>}
      {config.build_info &&
    // Real incident, 2026-09-27: a full day of testing ran against a
    // 15-hour-stale image with no way to tell from the running app.
    // Admin-only (config.build_info is null/absent for a non-admin
    // caller server-side, not just hidden here).
    <div data-testid="admin-build-info" title={`Built ${config.build_info.built_at}`} className="text-xs text-gray-400 mb-2">
          Build {config.build_info.commit.slice(0, 8)} · {config.build_info.built_at}
        </div>}
      <nav className="flex gap-4 mb-6 border-b border-gray-200">
        {/* UX-06 fix: tab clicks now push a real navigate() instead of
            only ever being local state -- previously the URL never
            changed when switching tabs, so refreshing mid-session always
            silently snapped back to whichever tab the URL was last
            navigated to (e.g. "Provisioning"), discarding the tab the
            admin was actually looking at, with no warning. Now the URL
            always matches the visible tab, both ways, so a refresh (or a
            bookmark/shared link to a specific tab) lands exactly where
            expected -- the same real-navigation pattern every other
            top-level screen in this package already uses. */}
        {available.map(s => <button key={s.key} type="button" data-testid={`admin-nav-${s.key}`} onClick={() => router.navigate(adminPath(s.key))} className={["bg-none border-none cursor-pointer px-0 py-2 -mb-px text-sm font-medium transition", current.key === s.key ? "border-b-2 border-indigo-600 text-indigo-700" : "border-b-2 border-transparent text-gray-400 hover:text-gray-600"].join(" ")}>
            {s.label}
          </button>)}
      </nav>
      <current.Component />
    </div>;
}