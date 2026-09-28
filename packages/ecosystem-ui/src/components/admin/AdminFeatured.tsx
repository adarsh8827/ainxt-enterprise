// SPDX-License-Identifier: MIT
// Task F-13: PUT/DELETE /ecosystem/featured/{item_id} -- an org can pin or
// unpin an item as featured for its own Discover page independent of the
// platform-level ecosystem_items.is_featured flag (CONFIG_AND_PRODUCTS.md
// §7 item 6).
import { useState } from "react";
import { useEcosystemClient } from "../../context/HostContext";

export function AdminFeatured() {
  const client = useEcosystemClient();
  const [itemId, setItemId] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const run = (action: "feature" | "clear") => {
    if (!itemId.trim()) return;
    setSubmitting(true);
    setError(null);
    const call = action === "feature" ? client.setFeatured(itemId, true) : client.clearFeaturedOverride(itemId);
    call
      .then(() => setStatus(action === "feature" ? "Featured for your org." : "Override removed -- reverted to the platform default."))
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't update the featured override."))
      .finally(() => setSubmitting(false));
  };

  return (
    <div data-testid="admin-featured">
      <h2 style={{ fontSize: "var(--eco-font-sizeXl)", color: "var(--eco-color-textPrimary)" }}>Featured overrides</h2>
      <input
        data-testid="admin-featured-item-id" value={itemId} onChange={(e) => setItemId(e.target.value)}
        placeholder="item id"
        style={{ width: "100%", padding: "8px", borderRadius: "var(--eco-radius-sm)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", color: "var(--eco-color-textPrimary)", marginBottom: "var(--eco-space-sm)" }}
      />
      <div style={{ display: "flex", gap: "var(--eco-space-sm)" }}>
        <button type="button" data-testid="admin-featured-set" disabled={submitting} onClick={() => run("feature")} style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}>
          Feature for org
        </button>
        <button type="button" data-testid="admin-featured-clear" disabled={submitting} onClick={() => run("clear")} style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", cursor: "pointer" }}>
          Remove override
        </button>
      </div>
      {status && <p data-testid="admin-featured-status" style={{ color: "var(--eco-color-success)" }}>{status}</p>}
      {error && <p role="alert" style={{ color: "var(--eco-color-danger)" }}>{error}</p>}
    </div>
  );
}
