// SPDX-License-Identifier: MIT
// Task F-7: Skills-only, deliberately trivial -- a skill has no execution
// footprint beyond the model's own context window (unlike a future
// plugin/connector/MCP server, which will need a real risk model here).
import type { ItemType } from "../../types";

export function RiskSidePanel({ itemType }: { itemType: ItemType }) {
  if (itemType !== "skill") return null;
  return (
    <aside
      data-testid="risk-side-panel"
      style={{ padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-md)", background: "var(--eco-color-surface)", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}
    >
      <h4 style={{ marginTop: 0, color: "var(--eco-color-textPrimary)" }}>What this can do</h4>
      <p>Only adds instructions for the model. It has no network access, no file access beyond its own bundled files, and no ability to run code outside a hardened sandbox during verification.</p>
    </aside>
  );
}
