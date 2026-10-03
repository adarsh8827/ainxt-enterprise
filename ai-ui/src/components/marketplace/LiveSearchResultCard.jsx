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
import { useEcosystemClient } from "./lib/context/HostContext";
import { ItemIcon } from "./ItemIcon";
import { LicenseBadge } from "./Badges";
export function LiveSearchResultCard({
  result,
  itemType,
  onInstalled
}) {
  const client = useEcosystemClient();
  const [state, setState] = useState("idle");
  const [errorMessage, setErrorMessage] = useState(null);
  const handleAdd = e => {
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
    const payload = {
      create_via: "import",
      item_type: itemType,
      namespace: result.namespace,
      category: "general",
      kind: result.source_kind,
      ref: result.ref
    };
    client.createItem(payload, `live-search-add-${result.ref}-${Date.now()}`).then(() => {
      setState("added");
      onInstalled?.();
    }).catch(err => {
      const code = err?.code;
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
  return <div data-testid="live-search-card" data-namespace={result.namespace} className="flex flex-col gap-2 p-4 rounded-xl border border-gray-200 bg-white text-left w-full">
      <div className="flex items-start gap-2">
        <ItemIcon iconUrl={null} namespace={result.namespace} displayName={result.display_name} />
        <div className="flex-1 min-w-0">
          <span title={result.display_name} className="block font-semibold text-sm text-gray-900 overflow-hidden text-ellipsis whitespace-nowrap">
            {result.display_name}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-1.5 flex-nowrap overflow-hidden">
        <LicenseBadge spdx={result.license_spdx} />
        <span data-testid="live-search-source-label" className="text-xs text-gray-400">
          From the web
        </span>
      </div>
      <p className="m-0 text-sm text-gray-500 overflow-hidden text-ellipsis" style={{
      display: "-webkit-box",
      WebkitLineClamp: 2,
      WebkitBoxOrient: "vertical"
    }}>
        {result.description}
      </p>
      <div className="flex items-center justify-end mt-auto">
        {state === "added" ? <span data-testid="live-search-added" className="inline-flex items-center gap-1 text-xs text-green-700">
            <CheckIcon width={14} height={14} aria-hidden="true" /> Added
          </span> : <button type="button" data-testid="live-search-add" disabled={state === "adding"} onClick={handleAdd} title={errorMessage ?? undefined} className={["inline-flex items-center gap-1 px-3 py-2 rounded text-xs font-medium border border-transparent transition-colors cursor-pointer", state === "error" ? "bg-red-50 text-red-600 hover:opacity-70" : "text-white brand-grad hover:opacity-70"].join(" ")}>
            <PlusIcon width={14} height={14} aria-hidden="true" /> {state === "adding" ? "Adding…" : state === "error" ? "Retry" : "Add"}
          </button>}
      </div>
      {errorMessage && <p role="alert" data-testid="live-search-error" className="m-0 text-xs text-red-600">
          {errorMessage}
        </p>}
    </div>;
}