// SPDX-License-Identifier: MIT
// Task F-13: admin nav + fail-closed rendering. Gated by the product
// profile's feature flags AND the caller's own real RBAC permission
// (admin-tabs regression round, 2026-10-06, real user report: "what are
// we achieving for admin, i don't know any single thing" -- every tab
// here used to render for ANY logged-in caller regardless of permission,
// only the product feature flag gated them -- the exact same bug class
// can_provision/can_admin_surfaces elsewhere in this config response
// already exist to fix, just never applied to this nav). Hiding the nav
// here is still only a convenience, not the enforcement -- every
// underlying call is independently permission-checked server-side
// regardless of whether this screen rendered the button (CONTRACTS.md's
// own allowed_actions philosophy, extended to whole screens here).
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
// permission: the exact caller_permissions key matching this screen's own
// real backend requirement (routers/ecosystem_router.py's own
// require_permission(...) on each underlying endpoint) -- not a new,
// separately-invented mapping.
const SCREENS = [{
  key: "policies",
  label: "Policies",
  feature: "admin_policies",
  permission: "can_admin_policy",
  Component: AdminPolicies
}, {
  key: "provisioning",
  label: "Provisioning",
  feature: "provisioning",
  permission: "can_provision",
  Component: AdminProvisioning
}, {
  key: "force-disable",
  label: "Force disable",
  feature: "admin_policies",
  permission: "can_admin_sources",
  Component: AdminForceDisable
}, {
  key: "gate-findings",
  label: "Gate findings",
  feature: "gate_dashboard",
  permission: "can_admin_sources",
  Component: AdminGateFindings
}, {
  key: "featured",
  label: "Featured",
  feature: "admin_policies",
  permission: "can_admin_policy",
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
  permission: "can_admin_sources",
  Component: AdminSources
},
// OAuth Apps' own endpoints require marketplace:admin_policy, same as
// Policies/Featured above (confirmed against routers/
// ecosystem_connectors_router.py's require_permission call).
{
  key: "oauth-apps",
  label: "OAuth Apps",
  feature: "admin_policies",
  permission: "can_admin_policy",
  Component: AdminOAuthApps
}];
export function AdminScreen({
  screen,
  onBack
}) {
  const config = useConfig();
  const { router } = useHost();
  const available = SCREENS.filter(s => config.features[s.feature] && config.caller_permissions[s.permission]);
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
      {/* Admin-polish pass (2026-10-05, explicit product ask: "extend the
          same polish pass to admin screens"): same pill-style active tab
          as Detail.jsx's own tab bar (that round's "detail page has so
          much tabs... need better design" fix) -- was plain underline-
          only, the one pattern this package used before that round.
          overflow-x-auto/overflow-y-hidden pairing for the same reason as
          there: this nav can carry 7 tabs (Sources is the widest-landing
          feature set so far), and the explicit y-hidden avoids the same
          spurious scrollbar CSS's own overflow-computation rule would
          otherwise introduce. */}
      <nav className="flex gap-1 mb-6 border-b border-gray-200 overflow-x-auto overflow-y-hidden">
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
        {available.map(s => <button key={s.key} type="button" data-testid={`admin-nav-${s.key}`} onClick={() => router.navigate(adminPath(s.key))} className={["bg-none border-none cursor-pointer px-3 py-1.5 -mb-px rounded-t-md text-sm font-medium transition-colors whitespace-nowrap", current.key === s.key ? "bg-indigo-50 text-indigo-700" : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"].join(" ")}>
            {s.label}
          </button>)}
      </nav>
      <current.Component />
    </div>;
}