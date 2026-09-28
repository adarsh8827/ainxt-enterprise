// SPDX-License-Identifier: MIT
// Task F-13: default-on/required install scope. Real backend surface
// (CONTRACTS.md §17): POST /ecosystem/items/{id}/require|/unrequire --
// promotes/demotes every existing origin='provisioned' install for that
// item, org-wide, to/from 'required' (CONFIG_AND_PRODUCTS.md §12 point 3).
// There is no separate "make an arbitrary published item org-default"
// endpoint distinct from this -- that provisioning happens at creation
// time via provision_scope (CreateForm.tsx's own picker); this screen's
// real job is the require/unrequire promotion, not group targeting (no
// group concept exists anywhere in this backend surface -- disclosed, not
// faked with a fake selector).
import { useState } from "react";
import { useEcosystemClient } from "../../context/HostContext";

export function AdminProvisioning() {
  const client = useEcosystemClient();
  const [itemId, setItemId] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const run = (action: "require" | "unrequire") => {
    if (!itemId.trim()) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    const call = action === "require" ? client.requireItem(itemId) : client.unrequireItem(itemId);
    call
      .then(() => setResult(action === "require" ? "Promoted to Required for this org." : "Demoted back to Org provisioned."))
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't update this item's provisioning."))
      .finally(() => setSubmitting(false));
  };

  return (
    <div data-testid="admin-provisioning">
      <h2 style={{ fontSize: "var(--eco-font-sizeXl)", color: "var(--eco-color-textPrimary)" }}>Provisioning</h2>
      <p style={{ color: "var(--eco-color-textSecondary)", fontSize: "var(--eco-font-sizeSm)" }}>
        Promote an already org-provisioned item to Required (no user in this org may disable it), or demote it back.
      </p>
      <input
        data-testid="admin-provisioning-item-id" value={itemId} onChange={(e) => setItemId(e.target.value)}
        placeholder="item id"
        style={{ width: "100%", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)", marginBottom: "var(--eco-space-sm)" }}
      />
      <div style={{ display: "flex", gap: "var(--eco-space-sm)" }}>
        <button type="button" data-testid="admin-provisioning-require" disabled={submitting} onClick={() => run("require")} style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}>
          Make required
        </button>
        <button type="button" data-testid="admin-provisioning-unrequire" disabled={submitting} onClick={() => run("unrequire")} style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", cursor: "pointer" }}>
          Make optional
        </button>
      </div>
      {result && <p data-testid="admin-provisioning-result" style={{ color: "var(--eco-color-success)" }}>{result}</p>}
      {error && <p role="alert" style={{ color: "var(--eco-color-danger)" }}>{error}</p>}
    </div>
  );
}
