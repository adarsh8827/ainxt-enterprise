// SPDX-License-Identifier: MIT
// Task F-5: the catalog card. Renders only from server-computed fields --
// no install_count anywhere (CONTRACTS.md §7's own closed-off schema).
import { useState } from "react";
import { CheckIcon, PlusIcon } from "@heroicons/react/24/outline";
import type { ItemSummary } from "../types";
import { ItemIcon } from "./ItemIcon";
import { CompatibilityBadge, NewBadge, TrustBadge, VerdictBadge } from "./Badges";
import { useEcosystemClient } from "../context/HostContext";
import { useConfig } from "../hooks/useEcosystemConfig";

export interface CardProps {
  item: ItemSummary;
  onOpen: (item: ItemSummary) => void;
  /** Called after a successful quick-add so the caller can refetch its
   * own list (Discover doesn't otherwise know an install just happened). */
  onInstalled?: () => void;
}

/** Real bug found live: Discover cards had no state indicator at all --
 * every card looked identical to Yours' rows, whether installed or not.
 * A quick "+ Add" button (mirrors Detail.tsx's own one-click doQuickInstall
 * -- private scope, chat surface, no dialog) when `install_id` is null;
 * "Added" once it's set. `allowed_actions.includes("install")` is the
 * server's own signal for whether Add is even offered at all (a blocked
 * or already-installed item has it removed -- items_service.compute_
 * allowed_actions()), so this button never has to re-derive that itself. */
function QuickAddButton({ item, onInstalled }: { item: ItemSummary; onInstalled?: () => void }) {
  const client = useEcosystemClient();
  const config = useConfig();
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (item.install_id) {
    return (
      <span
        data-testid="card-installed-badge"
        style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-success)" }}
      >
        <CheckIcon width={14} height={14} aria-hidden="true" /> Added
      </span>
    );
  }
  if (!item.allowed_actions.includes("install")) return null;

  const handleAdd = (e: React.MouseEvent) => {
    e.stopPropagation(); // never also trigger the card's own onOpen
    setInstalling(true);
    setError(null);
    client
      .getVersions(item.id)
      .then((versions) => {
        const versionId = versions.find((v) => v.is_current)?.id ?? versions[0]?.id;
        if (!versionId) throw new Error("No version to install.");
        // Real bug found live: this hardcoded ["chat"] regardless of what
        // other surfaces the caller's own product profile allows (e.g.
        // agent_studio/desktop for enterprise) -- default to every surface
        // config.surfaces lists, not just chat.
        const allSurfaces = config.surfaces.map((s) => s.key);
        return client.install(item.id, { version_id: versionId, surfaces: allSurfaces, scope: "private", origin: "added" }, `card-add-${item.id}-${Date.now()}`);
      })
      .then(() => onInstalled?.())
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Couldn't add this item."))
      .finally(() => setInstalling(false));
  };

  return (
    <button
      type="button"
      data-testid="card-quick-add"
      disabled={installing}
      onClick={handleAdd}
      title={error ?? undefined}
      style={{
        display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "var(--eco-font-sizeXs)",
        padding: "2px 8px", borderRadius: "var(--eco-radius-full)", border: "none", cursor: "pointer",
        background: error ? "var(--eco-color-dangerBg)" : "var(--eco-color-accentSkill)",
        color: error ? "var(--eco-color-danger)" : "var(--eco-color-accentSkillText)",
      }}
    >
      <PlusIcon width={12} height={12} aria-hidden="true" /> {installing ? "Adding…" : error ? "Retry" : "Add"}
    </button>
  );
}

export function Card({ item, onOpen, onInstalled }: CardProps) {
  const blocked = item.latest_verdict === "fail";
  return (
    // A real <button data-testid="card-quick-add"> now lives inside this
    // card (a nested <button> is invalid HTML) -- the card itself is a
    // div with role="button" instead, same click/keyboard behavior.
    <div
      role="button"
      tabIndex={0}
      data-testid="item-card"
      data-item-id={item.id}
      onClick={() => onOpen(item)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(item); } }}
      style={{
        display: "flex", flexDirection: "column", gap: "var(--eco-space-sm)",
        padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-lg)",
        border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)",
        textAlign: "left", cursor: "pointer", width: "100%",
        opacity: blocked ? 0.7 : 1,
      }}
    >
      {/* UI alignment spec (M5 UI-parity review, 2026-09-28): header =
          fixed-size icon + name on ONE line, truncating (not wrapping)
          with a tooltip on overflow -- real bug found live, the name used
          to sit in a `flexWrap: "wrap"` row with no truncation/title at
          all, so a long name just wrapped the card taller instead. */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: "var(--eco-space-sm)" }}>
        <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <span
            title={item.display_name}
            style={{
              display: "block", fontWeight: 600, fontSize: "var(--eco-font-sizeMd)", color: "var(--eco-color-textPrimary)",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}
          >
            {item.display_name}
          </span>
        </div>
      </div>
      {/* Badges row -- directly under the name, single line, never wraps
          or reflows (spec: trust/license/status/New). Moved up from the
          footer, where a real bug found live had these mixed in with the
          Add button instead of sitting under the name at all. */}
      <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "nowrap", overflow: "hidden" }}>
        <TrustBadge tier={item.trust_tier} />
        <VerdictBadge verdict={item.latest_verdict} />
        {item.is_new && <NewBadge />}
        <CompatibilityBadge compatibility={item.compatibility} />
      </div>
      <p style={{ margin: 0, fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", overflow: "hidden", textOverflow: "ellipsis", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
        {item.description}
      </p>
      {/* Footer -- pinned to the card's bottom edge regardless of
          description length (flex column on the card root + marginTop:
          "auto" here), matching every card in the row sitting at equal
          height via the parent CSS grid's own default align-items:
          stretch. Discover has no installed surfaces to show on the left
          (nothing's been added yet) -- footer-right ("+ Add"/"Added ✓")
          is the only content, same as before this fix, just no longer
          sharing a row with the badges. */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", marginTop: "auto" }}>
        <QuickAddButton item={item} onInstalled={onInstalled} />
      </div>
    </div>
  );
}
