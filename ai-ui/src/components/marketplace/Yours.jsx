// SPDX-License-Identifier: MIT
// Task F-6: 6 groups -- 5 client-side-grouped by Install.origin
// (CONTRACTS.md §9), plus a 6th, read-only "Available from existing
// skills" group rendered directly from legacy_items (never a synthesized
// Install row). Kebab menu contents are exactly allowed_actions -- no
// client-side inference of what a caller can do (F-6's own test rule).
import { useCallback, useEffect, useState } from "react";
import { useEcosystemClient, useI18n } from "./lib/context/HostContext";
import { useMediaQuery } from "./lib/hooks/useMediaQuery";
import { ItemIcon } from "./ItemIcon";
import { TrustBadge, TRUST_LABEL } from "./Badges";
import { RequiredLock } from "./RequiredLock";
import { KebabMenu, buildKebabActions } from "./KebabMenu";
import { InstalledMenu } from "./detail/InstalledMenu";
import { EmptyState } from "./EmptyState";
import { ConfirmDialog } from "./ConfirmDialog";
import { ReportDialog } from "./ReportDialog";
import { YoursSkeleton } from "./Skeleton";
import { getYoursCache, setYoursCache, yoursCacheKey } from "./lib/catalogCache";
import { removeInstallTracking, setInstallState } from "./lib/installStore";

// Item (d), part 1/2 (2026-09-29 live-test round): same "keep data in
// memory on tab switch" fix as Discover.tsx, see catalogCache.ts's own
// header comment for the full rationale. `GET /ecosystem/installs` has no
// ETag support today (unlike `GET /ecosystem/items`, confirmed directly
// against routers/ecosystem_router.py -- only list_items() computes one) --
// disclosed, out-of-scope-for-this-round gap; this screen's background
// refresh is a plain refetch, same request as before, just never nulling
// already-cached data while it's in flight.
const FOCUS_REFRESH_DEBOUNCE_MS = 1500;

/** Matches the list row's own `max-[1100px]:grid-cols-[...]` Tailwind
 * breakpoint below -- kept as one shared constant so the JS fold-into-kebab
 * logic below and the grid column collapse can never drift out of sync
 * with each other. */
const LIST_NARROW_QUERY = "(max-width: 1100px)";

/** Active/Disabled/Retired/Verifying/Blocked -- composed from
 * install.enabled + item.status/latest_verdict, since no single field
 * carries this today. Priority: a caller-disabled install always shows as
 * Disabled even if the underlying item would otherwise read as Active
 * (their own choice should read back to them first); Retired/Blocked/
 * Verifying only matter for an ENABLED install.
 *
 * BUG-U03 fix: "deprecated" used to fold into the same red "Blocked"
 * label as "yanked"/a failed gate verdict -- a user who voluntarily
 * retires their own perfectly-fine skill (via Retire/deprecate) saw the
 * exact same alarming badge as an admin-force-disabled or gate-failed
 * item. "Retired" now gets its own neutral/muted label, matching
 * "Disabled"'s own calm-but-inactive styling -- "Blocked" stays reserved
 * for the two cases that are genuinely someone/something else stopping
 * this item from working, not the caller's own choice to retire it. */
function statusChip(item, enabled) {
  if (!enabled) return {
    label: "Disabled",
    tone: "muted"
  };
  if (item.status === "deprecated") return {
    label: "Retired",
    tone: "muted"
  };
  if (item.status === "yanked" || item.latest_verdict === "fail") {
    return {
      label: "Blocked",
      tone: "danger"
    };
  }
  if (item.latest_verdict === "pending") return {
    label: "Verifying",
    tone: "warning"
  };
  return {
    label: "Active",
    tone: "success"
  };
}
function StatusChip({
  item,
  enabled
}) {
  const {
    label,
    tone
  } = statusChip(item, enabled);
  const toneClass = {
    success: "text-green-700 border-green-700",
    muted: "text-gray-400 border-gray-400",
    warning: "text-amber-700 border-amber-700",
    danger: "text-red-700 border-red-700"
  }[tone];
  return <span data-testid="yours-status-chip" data-status={label} className={["text-xs px-2 py-0.5 rounded-full border", toneClass].join(" ")}>
      {label}
    </span>;
}
const GROUP_ORDER = [{
  origin: "created",
  label: "Created by me"
}, {
  origin: "shared",
  label: "Shared with me"
}, {
  origin: "provisioned",
  label: "Org provisioned"
}, {
  origin: "required",
  label: "Required"
}, {
  origin: "added",
  label: "Added from Discover"
}];
export function Yours({
  itemType,
  onOpen,
  onCreate,
  onDiscover,
  query = "",
  layout = "grid"
}) {
  const client = useEcosystemClient();
  const strings = useI18n();
  const [installs, setInstalls] = useState(null);
  const [legacyItems, setLegacyItems] = useState([]);
  const [error, setError] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const cacheKey = yoursCacheKey(itemType);
  const refresh = useCallback(() => setRefreshKey(k => k + 1), []);
  useEffect(() => {
    let cancelled = false;
    let pollTimeout = null;
    setError(null);

    // Item (d), part 1: a previously-seen itemType shows its last-known
    // installs/legacy items INSTANTLY here -- no null-installs window, so
    // the skeleton branch below never renders for it. A genuinely new
    // itemType (no cache entry) has nothing to show yet, same as before
    // this fix.
    const cached = getYoursCache(cacheKey);
    if (cached) {
      setInstalls(cached.installs);
      setLegacyItems(cached.legacyItems);
    } else {
      setInstalls(null);
      setLegacyItems([]);
    }
    client.getInstalls(itemType).then(res => {
      if (cancelled) return;
      setInstalls(res.installs);
      setLegacyItems(res.legacy_items);
      setYoursCache(cacheKey, {
        installs: res.installs,
        legacyItems: res.legacy_items
      });
      // Same "still verifying" poll as Discover.tsx -- an install whose
      // item is still mid-gate (async path, worker not done yet) must
      // eventually pick up its resolved status without a manual reload.
      const stillVerifying = res.installs.some(i => i.item && i.item.latest_verdict === "pending");
      if (stillVerifying) {
        pollTimeout = setTimeout(() => {
          if (!cancelled) setRefreshKey(k => k + 1);
        }, 2000);
      }
    }).catch(e => {
      if (!cancelled) setError(e);
    });
    return () => {
      cancelled = true;
      if (pollTimeout) clearTimeout(pollTimeout);
    };
  }, [client, itemType, cacheKey, refreshKey]);

  // Item (d), part 2: "background refresh... on window focus" -- same
  // convention as Discover.tsx (itself reused from ai-ui/src/components/
  // Connectors.jsx's existing pattern), debounced and never nulling
  // `installs` itself -- just bumps refreshKey, which the effect above
  // already treats as "the cache/on-screen data stays, refetch again."
  useEffect(() => {
    let debounce = null;
    const onFocus = () => {
      if (debounce) return;
      debounce = setTimeout(() => {
        debounce = null;
        refresh();
      }, FOCUS_REFRESH_DEBOUNCE_MS);
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      if (debounce) clearTimeout(debounce);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [refresh]);

  // Install-state-consistency round (2026-09-29): the real, already-
  // existing per-org ecosystem.changed SSE stream -- covers a mutation
  // made in a DIFFERENT browser tab (this screen's own mutations already
  // call refresh() directly; installStore.ts's own in-memory overrides
  // only cover the SAME tab).
  useEffect(() => {
    return client.streamChanges?.(refresh);
  }, [client, refresh]);
  if (error) return <div data-testid="yours-error" role="alert">Couldn't load your items. Please try again.</div>;
  // Real bug found live, fixed in an earlier round: this used to render
  // `strings.verifying` here -- a page-level "hasn't loaded yet" state
  // must never read as a claim about any item's own verification status
  // (HostContext.tsx's own DEFAULT_STRINGS comment). Item (d), part 3
  // (this round): the fixed-but-still-textual `strings.loading` fallback
  // is itself replaced with real skeleton shapes -- reached only on a
  // genuine first load with no cached installs at all, same guarantee as
  // Discover.tsx's own skeleton branch.
  if (installs === null) {
    return <div data-testid="yours-loading" role="status" aria-label={strings.loading}>
        <YoursSkeleton layout={layout} />
      </div>;
  }
  if (installs.length === 0 && legacyItems.length === 0) {
    return <EmptyState message={strings.empty_yours} onDiscover={onDiscover} onCreate={onCreate} />;
  }

  // A row with no `item` (see the defensive check in InstallRow below) has
  // no name/description to match against -- it always stays visible rather
  // than silently disappearing behind a search that can't see it.
  const q = query.trim().toLowerCase();
  const matchesQuery = (name, description) => !q || `${name} ${description}`.toLowerCase().includes(q);
  const filteredInstalls = installs.filter(i => !i.item || matchesQuery(i.item.display_name, i.item.description));
  const filteredLegacy = legacyItems.filter(l => matchesQuery(l.item.display_name, l.item.description));
  if (q && filteredInstalls.length === 0 && filteredLegacy.length === 0) {
    return <p data-testid="yours-no-matches" className="text-gray-400">None of your {itemType}s match &ldquo;{query}&rdquo;.</p>;
  }
  return <div data-testid="yours-screen">
      {GROUP_ORDER.map(({
      origin,
      label
    }) => {
      const rows = filteredInstalls.filter(i => i.origin === origin);
      // "Created by me" is the one group with a friendly, actionable
      // empty hint -- every other empty group just renders nothing
      // (unchanged behavior), since "share/provision/require something"
      // isn't a self-serve action the way "create a skill" is.
      if (rows.length === 0) {
        if (origin !== "created" || q) return null;
        return <section key={origin} data-testid="yours-group-empty-hint" className="mb-6">
              <h3 className="text-lg text-gray-900">{label} (0)</h3>
              <p className="text-gray-500 text-sm my-1 mb-2">
                You haven&apos;t created anything yet.
              </p>
              <button type="button" onClick={onCreate} className="bg-none border border-gray-300 rounded-md px-3 py-1.5 text-indigo-600 hover:opacity-70 cursor-pointer text-sm transition-colors">
                Create a skill
              </button>
            </section>;
      }
      return <InstallGroup key={origin} label={label} rows={rows} onOpen={onOpen} client={client} onChanged={refresh} layout={layout} />;
    })}
      {filteredLegacy.length > 0 && <section data-testid="yours-legacy-group" className="mb-6">
          <h3 className="text-lg text-gray-900">Available from existing skills</h3>
          {filteredLegacy.map(legacy => <div key={legacy.item.id} data-testid="yours-legacy-row" className="flex items-center gap-2 py-2 border-b border-gray-200">
              <ItemIcon iconUrl={legacy.item.icon_url} namespace={legacy.item.namespace} displayName={legacy.item.display_name} size={28} />
              <div className="flex-1">
                <div className="font-semibold text-gray-900">{legacy.item.display_name}</div>
              </div>
              <button type="button" data-testid="yours-legacy-open" onClick={() => onOpen(legacy.item)} className="bg-none border-none text-indigo-600 hover:opacity-70 cursor-pointer transition-colors">
                Open
              </button>
            </div>)}
        </section>}
    </div>;
}
function InstallGroup({
  label,
  rows,
  onOpen,
  client,
  onChanged,
  layout
}) {
  return <section data-testid="yours-group" data-group-label={label} data-layout={layout} className="mb-6">
      <h3 className="text-lg text-gray-900">{label} ({rows.length})</h3>
      <div
    // auto-fit + maxWidth + fixed max track width, not 1fr -- see
    // Discover.tsx's matching grids for the full rationale (round 4,
    // 2026-10-03: a group with exactly 1 install, e.g. "Added from
    // Discover (1)", stretched that single card to the full row width
    // under round 3's auto-fit+1fr fix -- minmax(240px,320px) caps
    // each card's own width regardless of how many siblings it has).
    className={layout === "grid" ? "grid gap-4 max-w-[1000px]" : undefined}
    style={layout === "grid" ? {
      gridTemplateColumns: "repeat(auto-fit, minmax(240px, 320px))"
    } : undefined}>
        {rows.map(install => <InstallRow key={install.install_id} install={install} onOpen={onOpen} client={client} onChanged={onChanged} layout={layout} />)}
      </div>
    </section>;
}
function InstallRow({
  install,
  onOpen,
  client,
  onChanged,
  layout
}) {
  // Defensive: CONTRACTS.md §9 documents `item` as always present on a
  // real Install row, and the backend is expected to guarantee that --
  // but a row this tolerant check can't protect against (a backend
  // regression, a future endpoint change) must never blank the whole
  // screen for every OTHER row too. One bad row shows "unavailable"
  // instead of crashing the list.
  if (!install.item) {
    return <div data-testid="yours-install-row-unavailable" data-install-id={install.install_id} className={layout === "grid" ? "flex items-center gap-2 p-4 rounded-xl border border-gray-200 text-gray-500" : "flex items-center gap-2 py-2 border-b border-gray-200 text-gray-500"}>
        <div className="flex-1">This item is no longer available.</div>
        <button type="button" onClick={() => {
        // No install.item here to key the shared installStore by --
        // this row is already the "the underlying item is gone"
        // state, nothing to override; a NOT_FOUND on this uninstall
        // just means it's already gone, same end state either way.
        client.uninstall(install.install_id).then(onChanged).catch(err => {
          // Always refresh -- a NOT_FOUND means it's already gone
          // (same end state this button wants anyway); any other
          // error just means the row is still there for the user to
          // retry, never a silently-stuck button.
          onChanged();
          // eslint-disable-next-line no-console
          console.error("Couldn't remove this row:", err);
        });
      }} className="bg-none border-none text-indigo-600 hover:opacity-70 cursor-pointer transition-colors">
          Remove
        </button>
      </div>;
  }

  // Install-state-consistency round (2026-09-29): "an action targeting an
  // install that no longer exists must refresh and show correct state,
  // never fail silently." A NOT_FOUND always just calls onChanged() (the
  // real, authoritative re-fetch of Yours' own list -- a row for an
  // install/share that's already gone simply won't be in the fresh
  // result); any OTHER error surfaces here instead of vanishing as an
  // unhandled promise rejection (the real prior bug -- none of these
  // calls had a .catch at all).
  const [actionError, setActionError] = useState(null);
  const runMutation = (promise, onSuccess) => {
    setActionError(null);
    promise.then(() => {
      onSuccess?.();
      onChanged();
    }).catch(err => {
      const code = err?.code;
      if (code === "NOT_FOUND") {
        onChanged();
        return;
      }
      setActionError(err instanceof Error ? err.message : "Something went wrong.");
    });
  };

  // "Delete permanently"/"Retire" both destroy state a click can't undo --
  // confirmed before firing, same dialog whether triggered from the kebab
  // or the "Installed ▾" menu below (item 1, M5 UI-polish review).
  // "uninstall"/"disable" added (user-flow QA round 2, 2026-10-03): these
  // used to runMutation() straight from onUninstall/onToggleEnabled below
  // with zero confirmation, unlike delete/retire/unshare's existing
  // confirm-then-run pattern -- same shared dialog, just two more kinds.
  const [confirmAction, setConfirmAction] = useState(null);
  const askDelete = () => setConfirmAction({
    kind: "delete",
    run: () => runMutation(client.deleteDraft(install.item.id), () => removeInstallTracking(install.item.id))
  });
  const askRetire = () => setConfirmAction({
    kind: "retire",
    run: () => runMutation(client.deprecateItem(install.item.id))
  });
  // Real gap, now fixed: POST /ecosystem/shares/{share_id}/unshare needs
  // the SHARE's own id (policy_service.unshare(share_id, ...)) -- a
  // recipient's own install had no way to look that up before
  // ItemSummary/Install gained `share_id` (the recipient's own relevant
  // EcosystemShare.id, resolved server-side in items_service._item_to_
  // summary()). "unshare" is only ever offered by compute_allowed_actions()
  // for the RECIPIENT'S own install.scope == "shared", and share_id is only
  // ever non-null in exactly that case -- no separate guard needed here.
  // unshare() only ever removes the EcosystemShare row (confirmed directly,
  // policy_service.py) -- the recipient's own install/copy is untouched,
  // so this never patches installStore's install_id/enabled.
  const askUnshare = () => setConfirmAction({
    kind: "unshare",
    run: () => {
      if (install.item.share_id) runMutation(client.unshare(install.item.share_id));
    }
  });
  const askUninstall = () => setConfirmAction({
    kind: "uninstall",
    run: () => runMutation(client.uninstall(install.install_id), () => setInstallState(install.item.id, {
      install_id: null
    }))
  });
  // Disabling (not enabling -- that direction stays immediate, it's the
  // safe/reversible one) now confirms first too.
  const askDisable = () => setConfirmAction({
    kind: "disable",
    run: () => runMutation(client.setEnabled(install.install_id, false), () => setInstallState(install.item.id, {
      install_id: install.install_id,
      enabled: false
    }))
  });

  // "Installed ▾" carries the primary, common actions (matches Detail.tsx's
  // own InstalledMenu, reused here for visual consistency between the two
  // screens); the kebab keeps only what InstalledMenu doesn't cover
  // (report/unshare -- deprecate/delete_draft moved to the shared confirm-
  // then-run handlers above, still reachable from either menu).
  // User-flow QA round 8 (2026-10-03, real user question: "report...
  // what it will do?"): this used to fire client.reportItem(id, "reported
  // from Yours") immediately -- no confirmation, a hardcoded reason the
  // caller never actually typed, not even a .catch(). Now opens
  // ReportDialog (a real reason textarea + success/error feedback),
  // matching the confirm-before-firing pattern every other kebab action
  // here already follows.
  const [reporting, setReporting] = useState(false);
  const kebabActions = buildKebabActions(install.item.allowed_actions, {
    report: () => setReporting(true),
    deprecate: askRetire,
    delete_draft: askDelete,
    unshare: askUnshare
  });
  const required = install.scope === "required";
  const canDeprecate = install.item.allowed_actions.includes("deprecate");
  const isGrid = layout === "grid";
  // Item 1 (M5 UI-polish round 2): list view collapses its badges/
  // surface-chip columns below ~1100px (Yours.css's own matching
  // @media rule) -- rather than that information just vanishing, it
  // folds into the kebab menu as read-only lines. Only list mode needs
  // this (grid mode's card shape doesn't have this column collapse).
  const narrow = useMediaQuery(LIST_NARROW_QUERY);
  const foldInfoIntoKebab = !isGrid && narrow;
  const {
    label: statusLabel
  } = statusChip(install.item, install.enabled);
  // Per-surface toggles round (2026-09-29): the "Surfaces: ..." line that
  // used to live here is gone along with the toggle chips themselves --
  // normal users no longer manage per-surface enablement at all (see
  // Item 3's own admin-only "Advanced" override on the Detail page for
  // where that now lives), so there's nothing surface-shaped left for a
  // normal user's kebab to fold in here either.
  const infoLines = foldInfoIntoKebab ? [`${TRUST_LABEL[install.item.trust_tier]} • ${statusLabel}`] : undefined;
  const menus = <>
      <InstalledMenu enabled={install.enabled} required={required}
    // Plugins phase: name resolution across the OTHER item type's own
    // Yours list isn't available here (this list is scoped to one
    // itemType at a time, and the managing plugin's own install lives
    // under item_type "plugin" -- a different tab) -- falls back to
    // the generic "a plugin" phrasing, same disclosed gap as Detail.tsx.
    managedByPlugin={Boolean(install.managed_by_plugin_install_id)} onToggleEnabled={next => {
      if (next) {
        runMutation(client.setEnabled(install.install_id, next), () => setInstallState(install.item.id, {
          install_id: install.install_id,
          enabled: next
        }));
      } else {
        askDisable();
      }
    }}
    // BUG-U04 fix: deep-links straight to the Versions tab instead of
    // landing on Overview and making the user click Versions themselves.
    onViewVersions={() => onOpen(install.item, "versions")} onUninstall={askUninstall} canDeleteDraft={install.item.allowed_actions.includes("delete_draft")} hasOtherInstalls={install.item.has_other_installs} canDeprecate={canDeprecate} onDeletePermanently={askDelete} onRetire={askRetire} />
      {(kebabActions.length > 0 || infoLines && infoLines.length > 0) && <KebabMenu actions={kebabActions} infoLines={infoLines} />}
      {/* Install-state-consistency round (2026-09-29): a real, surfaced
          error instead of the previous unhandled-promise-rejection
          silent failure -- nested inside this same flex cell (never a
          new top-level sibling of the row) so it can't shift Yours.css's
          named grid-column layout in list mode. */}
      {actionError && <span data-testid="yours-row-action-error" role="alert" className="text-xs text-red-600">
          {actionError}
        </span>}
    </>;
  return <div data-testid="yours-install-row" data-install-id={install.install_id} data-layout={layout} className={isGrid ? "flex flex-col gap-2 p-4 rounded-xl border border-gray-200 bg-white shadow-sm transition-colors hover:bg-gray-50" : "grid items-center gap-x-3 px-3 py-2.5 border-b border-gray-200 min-w-0 overflow-hidden grid-cols-[32px_minmax(0,1fr)_112px_92px_104px] max-[1100px]:grid-cols-[32px_minmax(0,1fr)_92px_104px]"}>
      {isGrid ?
    // UI alignment spec (M5 UI-parity review, 2026-09-28): grid-layout
    // structure now matches Card.tsx's own Discover card exactly --
    // header (icon + truncated single-line name with a tooltip,
    // real bug found live: this used to wrap onto a second line
    // instead), a badges row directly under the name that never
    // wraps, the existing 2-line description clamp unchanged, then a
    // footer pinned to the card's bottom edge via marginTop: "auto"
    // (surfaces left, Installed ▾ + kebab right) -- another real bug
    // found live, the footer used to sit right after the description
    // with no pinning, so a short description left the footer
    // floating above the card's bottom edge while a long one pushed
    // it down, misaligning footers across a row of cards. List mode
    // (the `else` branch) is UNCHANGED -- its own single-line-row
    // shape already matches the spec's separate list-view
    // requirements and has its own, different column-alignment
    // concerns not touched here.
    <>
          <div className="flex items-start gap-2">
            <ItemIcon iconUrl={install.item.icon_url} namespace={install.item.namespace} displayName={install.item.display_name} size={28} />
            <div className="flex-1 min-w-0">
              <button type="button" onClick={() => onOpen(install.item)} title={install.item.display_name} className="block w-full bg-none border-none p-0 cursor-pointer font-semibold text-gray-900 text-left overflow-hidden text-ellipsis whitespace-nowrap">
                {install.item.display_name}
              </button>
            </div>
          </div>
          <div className="flex items-center gap-1.5 flex-nowrap overflow-hidden">
            {required && <RequiredLock />}
            <TrustBadge tier={install.item.trust_tier} />
            <StatusChip item={install.item} enabled={install.enabled} />
          </div>
          <div data-testid="yours-row-description" className="text-sm text-gray-500 overflow-hidden text-ellipsis" style={{
        display: "-webkit-box",
        WebkitLineClamp: 2,
        WebkitBoxOrient: "vertical"
      }}>
            {install.item.description}
          </div>
          {/* Per-surface toggles round (2026-09-29): the surface-chips
              wrapper that used to occupy the left side of this footer
              (flex: 1 1 auto / minWidth: 0, so it could shrink/clip
              rather than force the footer wider than the card) is gone --
              menus is now the row's only child, right-aligned via
              justifyContent: "flex-end" (space-between has nothing left
              to space). Footer bottom-pinning (marginTop: "auto") is
              unchanged. */}
          <div className="flex items-center justify-end gap-2 mt-auto">
            <div className="flex items-center gap-1.5">{menus}</div>
          </div>
        </> :
    // Item 1 (M5 UI-polish round 2, 2026-09-28, real screenshot at
    // 1920px): rebuilt as a real CSS grid (Yours.css) with fixed,
    // named columns -- [icon 32px] [name + one-line description,
    // flexible] [badges, fixed] [status] [actions, fixed,
    // right-aligned]. Every row shares the exact same column widths,
    // so the actions column lines up exactly across rows regardless
    // of any other column's content -- the previous version was a
    // flex column (name+badges on one line, description on a
    // second, surfaces on a third), which had no shared column grid
    // at all and made "line up the actions column" impossible.
    // Below ~1100px (LIST_NARROW_QUERY, matching Yours.css's own
    // breakpoint), the badges column collapses out of the grid and
    // its info folds into the kebab menu instead (infoLines above)
    // rather than wrapping.
    //
    // Per-surface toggles round (2026-09-29): the surfaces column
    // (and its narrow-breakpoint fold into the kebab) is gone
    // entirely -- normal users no longer see or manage per-surface
    // enablement on this row at all (Yours.css's grid-template-
    // columns dropped from 6 tracks to 5 to match).
    <>
          <ItemIcon iconUrl={install.item.icon_url} namespace={install.item.namespace} displayName={install.item.display_name} size={32} />
          <div className="flex flex-col gap-0.5 min-w-0 overflow-hidden">
            <button type="button" onClick={() => onOpen(install.item)} title={install.item.display_name} className="bg-none border-none p-0 cursor-pointer font-semibold text-gray-900 text-left overflow-hidden text-ellipsis whitespace-nowrap min-w-0">
              {install.item.display_name}
            </button>
            <div data-testid="yours-row-description" title={install.item.description} className="text-sm text-gray-500 overflow-hidden text-ellipsis whitespace-nowrap min-w-0">
              {install.item.description}
            </div>
          </div>
          {!narrow && <div className="flex items-center gap-1.5 min-w-0 overflow-hidden flex-nowrap">
              {required && <RequiredLock />}
              <TrustBadge tier={install.item.trust_tier} />
            </div>}
          <div>
            <StatusChip item={install.item} enabled={install.enabled} />
          </div>
          <div className="flex items-center justify-end gap-1.5 flex-shrink-0">{menus}</div>
        </>}
      <ConfirmDialog open={confirmAction !== null} title={confirmAction?.kind === "delete" ? "Delete this skill permanently?" : confirmAction?.kind === "unshare" ? "Stop sharing this skill?" : confirmAction?.kind === "uninstall" ? "Uninstall this skill?" : confirmAction?.kind === "disable" ? "Disable this skill?" : "Retire this skill?"} message={confirmAction?.kind === "delete" ? `"${install.item.display_name}" and all of its versions and stored files will be permanently deleted. This can't be undone.` : confirmAction?.kind === "unshare" ? `"${install.item.display_name}" was shared with you -- unsharing removes it from the sharer's own share list. Your own copy is unaffected.` : confirmAction?.kind === "uninstall" ? `"${install.item.display_name}" will be removed from your installed skills. You can add it again later from Discover.` : confirmAction?.kind === "disable" ? `"${install.item.display_name}" will stop working everywhere it's enabled (chat, Agent Studio, etc.) until you re-enable it.` : `"${install.item.display_name}" will stop appearing as an active skill. Existing installs keep working until each is uninstalled.`} confirmLabel={confirmAction?.kind === "delete" ? "Delete permanently" : confirmAction?.kind === "unshare" ? "Unshare" : confirmAction?.kind === "uninstall" ? "Uninstall" : confirmAction?.kind === "disable" ? "Disable" : "Retire"} danger={confirmAction?.kind === "delete" || confirmAction?.kind === "uninstall" || confirmAction?.kind === "disable"} onConfirm={() => {
      confirmAction?.run();
      setConfirmAction(null);
    }} onCancel={() => setConfirmAction(null)} />
      <ReportDialog open={reporting} itemName={install.item.display_name} onSubmit={reason => client.reportItem(install.item.id, reason)} onCancel={() => setReporting(false)} />
    </div>;
}