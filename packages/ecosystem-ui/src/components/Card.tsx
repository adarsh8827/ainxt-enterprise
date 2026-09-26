// SPDX-License-Identifier: MIT
// Task F-5: the catalog card. Renders only from server-computed fields --
// no install_count anywhere (CONTRACTS.md §7's own closed-off schema).
import type { ItemSummary } from "../types";
import { ItemIcon } from "./ItemIcon";
import { NewBadge, TrustBadge, VerdictBadge } from "./Badges";

export interface CardProps {
  item: ItemSummary;
  onOpen: (item: ItemSummary) => void;
}

export function Card({ item, onOpen }: CardProps) {
  const blocked = item.latest_verdict === "fail";
  return (
    <button
      type="button"
      data-testid="item-card"
      data-item-id={item.id}
      onClick={() => onOpen(item)}
      style={{
        display: "flex", flexDirection: "column", gap: "var(--eco-space-sm)",
        padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-lg)",
        border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)",
        textAlign: "left", cursor: "pointer", width: "100%",
        opacity: blocked ? 0.7 : 1,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: "var(--eco-space-sm)" }}>
        <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
            <span style={{ fontWeight: 600, fontSize: "var(--eco-font-sizeMd)", color: "var(--eco-color-textPrimary)" }}>
              {item.display_name}
            </span>
            {item.is_new && <NewBadge />}
          </div>
          <p style={{ margin: "2px 0 0", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", overflow: "hidden", textOverflow: "ellipsis", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
            {item.description}
          </p>
        </div>
      </div>
      <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
        <TrustBadge tier={item.trust_tier} />
        <VerdictBadge verdict={item.latest_verdict} />
      </div>
    </button>
  );
}
