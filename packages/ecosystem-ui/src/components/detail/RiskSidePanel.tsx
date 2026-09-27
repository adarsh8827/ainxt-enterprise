// SPDX-License-Identifier: MIT
// UI-polish round: absorbed the item-metadata list (namespace/publisher/
// license/version/category) that used to live in both Detail.tsx's own
// header AND Overview.tsx's <dl> -- one place now, the side panel, no
// duplication. The plain-language risk copy below it stays skill-only
// (task F-7's own reasoning: a skill has no execution footprint beyond
// the model's own context window, unlike a future plugin/connector/MCP
// server, which will need a real risk model here) -- non-skill types get
// the metadata list with no risk copy underneath rather than a caveat
// that isn't true for them.
import type { ItemDetail } from "../../types";

export function RiskSidePanel({ item }: { item: ItemDetail }) {
  return (
    <aside data-testid="risk-side-panel" style={{ display: "flex", flexDirection: "column", gap: "var(--eco-space-md)" }}>
      <div style={{ padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-md)", background: "var(--eco-color-surface)", fontSize: "var(--eco-font-sizeSm)" }}>
        <h4 style={{ margin: "0 0 8px", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)" }}>Item details</h4>
        <dl data-testid="detail-metadata" style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px", margin: 0, color: "var(--eco-color-textSecondary)" }}>
          <dt>Namespace</dt><dd>{item.namespace}</dd>
          <dt>Publisher</dt><dd>{item.publisher.slug} ({item.publisher.type})</dd>
          <dt>License</dt><dd>{item.license}</dd>
          <dt>Category</dt><dd style={{ textTransform: "capitalize" }}>{item.category.replace(/-/g, " ")}</dd>
          <dt>Version</dt><dd>{item.latest_version ?? "—"}</dd>
        </dl>
      </div>

      {item.item_type === "skill" && (
        <div style={{ padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-md)", background: "var(--eco-color-surface)", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
          <h4 style={{ margin: "0 0 8px", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)" }}>What this can do</h4>
          <p style={{ margin: 0 }}>Only gives the assistant instructions. It can't access the internet or your files.</p>
        </div>
      )}
    </aside>
  );
}
