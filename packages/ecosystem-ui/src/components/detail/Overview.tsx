// SPDX-License-Identifier: MIT
import type { ItemDetail } from "../../types";

export function Overview({ item }: { item: ItemDetail }) {
  return (
    <div data-testid="detail-tab-overview">
      <p style={{ color: "var(--eco-color-textPrimary)" }}>{item.description}</p>
      <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
        <dt>Namespace</dt><dd>{item.namespace}</dd>
        <dt>Publisher</dt><dd>{item.publisher.slug} ({item.publisher.type})</dd>
        <dt>License</dt><dd>{item.license}</dd>
        <dt>Category</dt><dd style={{ textTransform: "capitalize" }}>{item.category.replace(/-/g, " ")}</dd>
        <dt>Latest version</dt><dd>{item.latest_version ?? "—"}</dd>
      </dl>
    </div>
  );
}
