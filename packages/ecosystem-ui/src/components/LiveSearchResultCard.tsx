// SPDX-License-Identifier: MIT
// Discover "From the web" section (docs/ecosystem/design/CHANGELOG.md's
// live-search round; docs/ecosystem/TESTING_GUIDE.md §6o). A live-search
// result (LiveSearchResult) has no `id`/`item_id` yet -- it doesn't exist
// in the DB until installed -- no gate verdict, no installed state.
// Deliberately a SEPARATE, minimal component rather than forcing this
// pointer-only shape through Card.tsx/QuickAddButton: that component's
// "+ Add" logic (installTracking.ts's shared store, useInstallStatus's
// job polling, getVersions() lookups, allowed_actions gating) is all
// built around an ItemSummary that already has a real id/verdict/install
// state to poll against, none of which a live-search result has. Visually
// consistent with Card.tsx (same tokens, same layout shape, same
// ItemIcon/badge row/footer structure) without requiring fields this
// result genuinely doesn't have.
import { useState } from "react";
import { PlusIcon, CheckIcon } from "@heroicons/react/24/outline";
import type { CreateImportPayload, ItemType, LiveSearchResult } from "../types";
import { useEcosystemClient } from "../context/HostContext";
import { ItemIcon } from "./ItemIcon";
import { LicenseBadge } from "./Badges";

export function LiveSearchResultCard({ result, itemType, onInstalled }: {
  result: LiveSearchResult;
  /** The Discover tab's own active item type (skill/plugin/connector/
   * mcp_server) -- a live-search result carries no item_type of its own
   * (GET /ecosystem/search/live's pointer shape never returns one), so
   * the import payload uses whichever tab the caller found it under,
   * same as ImportFlow.tsx's own manual "Import from URL" form does. */
  itemType: ItemType;
  onInstalled?: () => void;
}) {
  const client = useEcosystemClient();
  const [state, setState] = useState<"idle" | "adding" | "added" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleAdd = (e: React.MouseEvent) => {
    e.stopPropagation();
    setState("adding");
    setErrorMessage(null);
    // The EXACT create_via="import" path a manual "Import from URL"
    // (ImportFlow.tsx) already uses -- `ref` is the result's own `ref`
    // verbatim (services/ecosystem/live_search_service.py's own contract:
    // "the exact ref create_via_import(kind='github_repo', ref=...)
    // expects"). No `license` field sent -- the server re-derives it
    // fresh from the real content at import time (materialize/license
    // stage), same as ImportFlow.tsx's own payload; this component's own
    // license_spdx is a pre-filter display value, not something to feed
    // back in as if it were authoritative.
    const payload: CreateImportPayload = {
      create_via: "import",
      item_type: itemType,
      namespace: result.namespace,
      category: "general",
      kind: result.source_kind,
      ref: result.ref,
    };
    client.createItem(payload, `live-search-add-${result.ref}-${Date.now()}`)
      .then(() => {
        setState("added");
        onInstalled?.();
      })
      .catch((err: unknown) => {
        const code = (err as { code?: string })?.code;
        if (code === "LICENSE_NOT_ALLOWED") {
          setErrorMessage("The source's declared license isn't MIT/Apache-2.0-compatible after all -- rejected before importing anything.");
        } else if (code === "NEUTRALITY_VIOLATION") {
          setErrorMessage("This result's real content isn't vendor-neutral and can't be added.");
        } else {
          setErrorMessage(err instanceof Error ? err.message : "Couldn't add this item.");
        }
        setState("error");
      });
  };

  return (
    <div
      data-testid="live-search-card"
      data-namespace={result.namespace}
      style={{
        display: "flex", flexDirection: "column", gap: "var(--eco-space-sm)",
        padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-lg)",
        border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)",
        textAlign: "left", width: "100%",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: "var(--eco-space-sm)" }}>
        <ItemIcon iconUrl={null} namespace={result.namespace} displayName={result.display_name} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <span
            title={result.display_name}
            style={{
              display: "block", fontWeight: 600, fontSize: "var(--eco-font-sizeMd)", color: "var(--eco-color-textPrimary)",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}
          >
            {result.display_name}
          </span>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "nowrap", overflow: "hidden" }}>
        <LicenseBadge spdx={result.license_spdx} />
        <span
          data-testid="live-search-source-label"
          style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)" }}
        >
          From the web
        </span>
      </div>
      <p style={{ margin: 0, fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", overflow: "hidden", textOverflow: "ellipsis", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
        {result.description}
      </p>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", marginTop: "auto" }}>
        {state === "added" ? (
          <span
            data-testid="live-search-added"
            style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-success)" }}
          >
            <CheckIcon width={14} height={14} aria-hidden="true" /> Added
          </span>
        ) : (
          <button
            type="button"
            data-testid="live-search-add"
            disabled={state === "adding"}
            onClick={handleAdd}
            title={errorMessage ?? undefined}
            style={{
              boxSizing: "border-box",
              display: "inline-flex", alignItems: "center", gap: "4px",
              padding: "8px 12px", borderRadius: "var(--eco-radius-md)",
              border: "1px solid transparent", cursor: "pointer",
              background: state === "error" ? "var(--eco-color-dangerBg)" : "var(--eco-color-accentSkill)",
              color: state === "error" ? "var(--eco-color-danger)" : "var(--eco-color-accentSkillText)",
            }}
          >
            <PlusIcon width={14} height={14} aria-hidden="true" /> {state === "adding" ? "Adding…" : state === "error" ? "Retry" : "Add"}
          </button>
        )}
      </div>
      {errorMessage && (
        <p role="alert" data-testid="live-search-error" style={{ margin: 0, fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-danger)" }}>
          {errorMessage}
        </p>
      )}
    </div>
  );
}
