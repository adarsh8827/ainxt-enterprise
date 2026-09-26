// SPDX-License-Identifier: MIT
// Task F-13: who-can-add/allowed-sources/auto-update, calling B-19's
// GET/PUT /ecosystem/policy (task M4 backend prerequisites -- these
// endpoints didn't exist until this same milestone added them).
import { useEffect, useState } from "react";
import type { OrgPolicy } from "../../types";
import { useEcosystemClient } from "../../context/HostContext";

export function AdminPolicies() {
  const client = useEcosystemClient();
  const [policy, setPolicy] = useState<OrgPolicy | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    client.getPolicy().then((p) => { if (!cancelled) setPolicy(p); }).catch((e) => setError(String(e)));
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
    </div>
  );
}
