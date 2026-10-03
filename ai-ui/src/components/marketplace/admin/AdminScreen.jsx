// SPDX-License-Identifier: MIT
// Task F-13: admin nav + fail-closed rendering. Gated by the product
// profile's feature flags (never a separate ECOSYSTEM_* flag) -- hiding
// the nav here is a convenience, not the enforcement; every underlying
// call is independently permission-checked server-side regardless of
// whether this screen rendered the button (CONTRACTS.md's own
// allowed_actions philosophy, extended to whole screens for the admin
// surface).
import { useState } from "react";
import { useConfig } from "../lib/hooks/useEcosystemConfig";
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
  screen
}) {
  const config = useConfig();
  const available = SCREENS.filter(s => config.features[s.feature]);
  const [active, setActive] = useState(screen);
  if (available.length === 0) {
    return <div data-testid="admin-not-available">Admin screens aren't available for this product.</div>;
  }
  const current = available.find(s => s.key === active) ?? available[0];
  return <div data-testid="admin-screen">
      {config.build_info &&
    // Real incident, 2026-09-27: a full day of testing ran against a
    // 15-hour-stale image with no way to tell from the running app.
    // Admin-only (config.build_info is null/absent for a non-admin
    // caller server-side, not just hidden here).
    <div data-testid="admin-build-info" title={`Built ${config.build_info.built_at}`} className="text-xs text-gray-400 mb-2">
          Build {config.build_info.commit.slice(0, 8)} · {config.build_info.built_at}
        </div>}
      <nav className="flex gap-4 mb-6 border-b border-gray-200">
        {available.map(s => <button key={s.key} type="button" data-testid={`admin-nav-${s.key}`} onClick={() => setActive(s.key)} className={["bg-none border-none cursor-pointer px-0 py-2 -mb-px text-sm font-medium transition", current.key === s.key ? "border-b-2 border-indigo-600 text-indigo-700" : "border-b-2 border-transparent text-gray-400 hover:text-gray-600"].join(" ")}>
            {s.label}
          </button>)}
      </nav>
      <current.Component />
    </div>;
}