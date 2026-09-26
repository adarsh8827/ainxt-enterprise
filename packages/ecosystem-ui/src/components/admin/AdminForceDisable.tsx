// SPDX-License-Identifier: MIT
// Task F-13: calling B-19's force-disable/unyank. UI hiding is a
// convenience, not the enforcement -- the server independently re-checks
// marketplace:admin_sources on every call regardless of what this screen
// renders (require_permission dependency, routers/ecosystem_router.py).
import { useState } from "react";
import { useEcosystemClient } from "../../context/HostContext";

export function AdminForceDisable() {
  const client = useEcosystemClient();
  const [itemId, setItemId] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const run = (action: "force-disable" | "unyank") => {
    if (!itemId.trim()) return;
    setSubmitting(true);
    setError(null);
    const call = action === "force-disable" ? client.forceDisable(itemId) : client.unyank(itemId);
    call
      .then(() => setStatus(action === "force-disable" ? "Disabled (yanked)." : "Re-enabled (active)."))
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't update this item."))
      .finally(() => setSubmitting(false));
  };

  return (
    <div data-testid="admin-force-disable">
      <h2 style={{ color: "var(--eco-color-textPrimary)" }}>Force disable / re-enable</h2>
      <input
        data-testid="admin-force-disable-item-id" value={itemId} onChange={(e) => setItemId(e.target.value)}
        placeholder="item id"
        style={{ width: "100%", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)", marginBottom: "var(--eco-space-sm)" }}
      />
      <div style={{ display: "flex", gap: "var(--eco-space-sm)" }}>
        <button type="button" data-testid="admin-force-disable-run" disabled={submitting} onClick={() => run("force-disable")} style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-danger)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}>
          Force disable
        </button>
        <button type="button" data-testid="admin-force-disable-unyank" disabled={submitting} onClick={() => run("unyank")} style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", cursor: "pointer" }}>
          Unyank
        </button>
      </div>
      {status && <p data-testid="admin-force-disable-status" style={{ color: "var(--eco-color-success)" }}>{status}</p>}
      {error && <p role="alert" style={{ color: "var(--eco-color-danger)" }}>{error}</p>}
    </div>
  );
}
