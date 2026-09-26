// SPDX-License-Identifier: MIT
// Wires Discover/Yours together for one available item type. Default view
// (CONTRACTS.md §7, Review fix 8): Yours if GET /ecosystem/installs?item_type=X
// has_any is true, else the product profile's default_view -- determined
// from that one field, no separate call.
import { useEffect, useState } from "react";
import type { ItemSummary, ItemType } from "../types";
import { useConfig } from "../hooks/useEcosystemConfig";
import { useEcosystemClient } from "../context/HostContext";
import { Discover } from "./Discover";
import { Yours } from "./Yours";

export function CatalogScreen({ itemType, onOpen, onCreate }: {
  itemType: ItemType; onOpen: (item: ItemSummary) => void; onCreate: () => void;
}) {
  const client = useEcosystemClient();
  const config = useConfig();
  const [view, setView] = useState<"discover" | "yours" | null>(null);

  useEffect(() => {
    let cancelled = false;
    client.getInstalls(itemType).then((res) => {
      if (!cancelled) setView(res.has_any ? "yours" : config.default_view);
    });
    return () => { cancelled = true; };
  }, [client, itemType, config.default_view]);

  if (view === null) return <div data-testid="catalog-screen-loading">Loading…</div>;

  return (
    <div data-testid="catalog-screen">
      <div role="tablist" style={{ display: "flex", gap: "var(--eco-space-md)", marginBottom: "var(--eco-space-md)" }}>
        <ViewToggle label="Discover" active={view === "discover"} onClick={() => setView("discover")} testId="view-toggle-discover" />
        <ViewToggle label="Yours" active={view === "yours"} onClick={() => setView("yours")} testId="view-toggle-yours" />
      </div>
      {view === "discover"
        ? <Discover itemType={itemType} onOpen={onOpen} />
        : <Yours itemType={itemType} onOpen={onOpen} onCreate={onCreate} onDiscover={() => setView("discover")} />}
    </div>
  );
}

function ViewToggle({ label, active, onClick, testId }: { label: string; active: boolean; onClick: () => void; testId: string }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      data-testid={testId}
      onClick={onClick}
      style={{
        background: "none", border: "none", cursor: "pointer", padding: "4px 0",
        fontWeight: active ? 600 : 400, color: active ? "var(--eco-color-textPrimary)" : "var(--eco-color-textSecondary)",
      }}
    >
      {label}
    </button>
  );
}
