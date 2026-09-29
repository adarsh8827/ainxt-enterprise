// SPDX-License-Identifier: MIT
// Task F-13: admin nav + fail-closed rendering. Gated by the product
// profile's feature flags (never a separate ECOSYSTEM_* flag) -- hiding
// the nav here is a convenience, not the enforcement; every underlying
// call is independently permission-checked server-side regardless of
// whether this screen rendered the button (CONTRACTS.md's own
// allowed_actions philosophy, extended to whole screens for the admin
// surface).
import { useState } from "react";
import { useConfig } from "../../hooks/useEcosystemConfig";
import { AdminPolicies } from "./AdminPolicies";
import { AdminProvisioning } from "./AdminProvisioning";
import { AdminForceDisable } from "./AdminForceDisable";
import { AdminGateFindings } from "./AdminGateFindings";
import { AdminFeatured } from "./AdminFeatured";
import { AdminSources } from "./AdminSources";

const SCREENS = [
  { key: "policies", label: "Policies", feature: "admin_policies" as const, Component: AdminPolicies },
  { key: "provisioning", label: "Provisioning", feature: "provisioning" as const, Component: AdminProvisioning },
  { key: "force-disable", label: "Force disable", feature: "admin_policies" as const, Component: AdminForceDisable },
  { key: "gate-findings", label: "Gate findings", feature: "gate_dashboard" as const, Component: AdminGateFindings },
  { key: "featured", label: "Featured", feature: "admin_policies" as const, Component: AdminFeatured },
  // Task 3a: same feature-flag gate as the other admin_sources-permission
  // screens above (force-disable/featured) -- no dedicated "sources"
  // product feature flag exists, and adding one would need a DB seed
  // change on every existing profile for no real benefit over reusing the
  // flag every other org-admin screen on this nav already shares.
  { key: "sources", label: "Sources", feature: "admin_policies" as const, Component: AdminSources },
];

export function AdminScreen({ screen }: { screen: string }) {
  const config = useConfig();
  const available = SCREENS.filter((s) => config.features[s.feature]);
  const [active, setActive] = useState(screen);

  if (available.length === 0) {
    return <div data-testid="admin-not-available">Admin screens aren't available for this product.</div>;
  }

  const current = available.find((s) => s.key === active) ?? available[0]!;

  return (
    <div data-testid="admin-screen">
      {config.build_info && (
        // Real incident, 2026-09-27: a full day of testing ran against a
        // 15-hour-stale image with no way to tell from the running app.
        // Admin-only (config.build_info is null/absent for a non-admin
        // caller server-side, not just hidden here).
        <div
          data-testid="admin-build-info"
          title={`Built ${config.build_info.built_at}`}
          style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)", marginBottom: "var(--eco-space-sm)" }}
        >
          Build {config.build_info.commit.slice(0, 8)} · {config.build_info.built_at}
        </div>
      )}
      <nav style={{ display: "flex", gap: "var(--eco-space-md)", marginBottom: "var(--eco-space-lg)", borderBottom: "1px solid var(--eco-color-border)" }}>
        {available.map((s) => (
          <button
            key={s.key}
            type="button"
            data-testid={`admin-nav-${s.key}`}
            onClick={() => setActive(s.key)}
            style={{
              background: "none", border: "none", cursor: "pointer", padding: "8px 0",
              color: current.key === s.key ? "var(--eco-color-accentSkill)" : "var(--eco-color-textSecondary)",
              borderBottom: current.key === s.key ? "2px solid var(--eco-color-accentSkill)" : "2px solid transparent",
              fontWeight: current.key === s.key ? 600 : 400,
            }}
          >
            {s.label}
          </button>
        ))}
      </nav>
      <current.Component />
    </div>
  );
}
