// SPDX-License-Identifier: MIT
import type { ItemDetail } from "../../types";

export function License({ item }: { item: ItemDetail }) {
  return (
    <div data-testid="detail-tab-license">
      <p style={{ color: "var(--eco-color-textPrimary)" }}><strong>{item.license}</strong></p>
      <pre style={{ whiteSpace: "pre-wrap", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
        {item.attribution || "No attribution text recorded."}
      </pre>
    </div>
  );
}
