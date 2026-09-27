// SPDX-License-Identifier: MIT
// Task F-13: who-can-add/allowed-sources/auto-update, calling B-19's
// GET/PUT /ecosystem/policy (task M4 backend prerequisites -- these
// endpoints didn't exist until this same milestone added them).
import { useEffect, useState } from "react";
import type { OrgPolicy } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";

/** Tier 2 of the tiered license policy (ECOSYSTEM_PLAN.md §11.2) is a
 * free-form comma-separated list here rather than a fixed checkbox set --
 * an admin can opt into any SPDX identifier, not just a pre-enumerated
 * handful. MIT/Apache-2.0 are always effectively allowed regardless
 * (Tier 1 is checked first, server-side), so removing them from this list
 * narrows nothing -- shown here as-is rather than silently re-added, so
 * the admin sees exactly what they saved. */
function parseLicenseList(text: string): string[] {
  return text.split(",").map((s) => s.trim()).filter(Boolean);
}

export function AdminPolicies() {
  const client = useEcosystemClient();
  const [policy, setPolicy] = useState<OrgPolicy | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [licenseListText, setLicenseListText] = useState("");

  useEffect(() => {
    let cancelled = false;
    client.getPolicy().then((p) => {
      if (cancelled) return;
      setPolicy(p);
      setLicenseListText(p.allowed_licenses_shared.join(", "));
    }).catch((e) => setError(String(e)));
    return () => { cancelled = true; };
  }, [client]);

  if (error) return <div role="alert" data-testid="admin-policies-error">{error}</div>;
  if (!policy) return <div data-testid="admin-policies-loading">Loading…</div>;

  const save = (patch: Partial<OrgPolicy>) => {
    setSaving(true);
    client.setPolicy(patch).then(setPolicy).finally(() => setSaving(false));
  };

  return (
    <div data-testid="admin-policies">
      <h2 style={{ color: "var(--eco-color-textPrimary)" }}>Marketplace policy</h2>

      <fieldset style={{ border: "none", padding: 0, marginBottom: "var(--eco-space-md)" }}>
        <legend style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>Who can add items</legend>
        {(["all_users", "admins_only"] as const).map((v) => (
          <label key={v} style={{ display: "flex", alignItems: "center", gap: "6px", color: "var(--eco-color-textPrimary)" }}>
            <input
              type="radio" name="who_can_add" value={v} checked={policy.who_can_add === v} disabled={saving}
              onChange={() => save({ who_can_add: v })}
            />
            {v === "all_users" ? "All authenticated users" : "Admins only"}
          </label>
        ))}
      </fieldset>

      <label style={{ display: "flex", alignItems: "center", gap: "6px", color: "var(--eco-color-textPrimary)" }}>
        <input
          type="checkbox" data-testid="admin-policies-auto-update" checked={policy.auto_update_default} disabled={saving}
          onChange={(e) => save({ auto_update_default: e.target.checked })}
        />
        Auto-update installs by default
      </label>

      <div style={{ marginTop: "var(--eco-space-md)" }}>
        <label style={{ display: "block", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", marginBottom: "4px" }}>
          Licenses allowed once shared/provisioned/required
        </label>
        <input
          data-testid="admin-policies-allowed-licenses-shared"
          value={licenseListText}
          disabled={saving}
          onChange={(e) => setLicenseListText(e.target.value)}
          onBlur={() => save({ allowed_licenses_shared: parseLicenseList(licenseListText) })}
          placeholder="MIT, Apache-2.0"
          style={{ width: "100%", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)" }}
        />
        <p style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textSecondary)", margin: "4px 0 0" }}>
          Comma-separated SPDX identifiers. MIT/Apache-2.0 are always allowed regardless of this list.
        </p>
      </div>
    </div>
  );
}
