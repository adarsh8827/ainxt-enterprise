// SPDX-License-Identifier: MIT
// Task F-6: 6 groups -- 5 client-side-grouped by Install.origin
// (CONTRACTS.md §9), plus a 6th, read-only "Available from existing
// skills" group rendered directly from legacy_items (never a synthesized
// Install row). Kebab menu contents are exactly allowed_actions -- no
// client-side inference of what a caller can do (F-6's own test rule).
import { useCallback, useEffect, useState } from "react";
import type { Install, ItemSummary, LegacyItem } from "../types";
import { useEcosystemClient, useI18n } from "../context/HostContext";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { ItemIcon } from "./ItemIcon";
import { TrustBadge, TRUST_LABEL } from "./Badges";
import { RequiredLock } from "./RequiredLock";
import { KebabMenu, buildKebabActions } from "./KebabMenu";
import { InstalledMenu } from "./detail/InstalledMenu";
import { EmptyState } from "./EmptyState";
import { ConfirmDialog } from "./ConfirmDialog";
import { YoursSkeleton } from "./Skeleton";
import { getYoursCache, setYoursCache, yoursCacheKey } from "../catalogCache";
import "./Yours.css";

// Item (d), part 1/2 (2026-09-29 live-test round): same "keep data in
// memory on tab switch" fix as Discover.tsx, see catalogCache.ts's own
// header comment for the full rationale. `GET /ecosystem/installs` has no
// ETag support today (unlike `GET /ecosystem/items`, confirmed directly
// against routers/ecosystem_router.py -- only list_items() computes one) --
// disclosed, out-of-scope-for-this-round gap; this screen's background
// refresh is a plain refetch, same request as before, just never nulling
// already-cached data while it's in flight.
const FOCUS_REFRESH_DEBOUNCE_MS = 1500;

/** Matches Yours.css's own `@media (max-width: 1100px)` collapse --
 * kept as one shared constant so the JS fold-into-kebab logic below and
 * the CSS column collapse can never drift out of sync with each other. */
const LIST_NARROW_QUERY = "(max-width: 1100px)";

/** Active/Disabled/Verifying/Blocked -- composed from install.enabled +
 * item.status/latest_verdict, since no single field carries this today.
 * Priority: a caller-disabled install always shows as Disabled even if
 * the underlying item would otherwise read as Active (their own choice
 * should read back to them first); Blocked (retired/failed) and
 * Verifying (still gating) only matter for an ENABLED install. */
function statusChip(item: ItemSummary, enabled: boolean): { label: string; tone: "success" | "muted" | "warning" | "danger" } {
  if (!enabled) return { label: "Disabled", tone: "muted" };
  if (item.status === "yanked" || item.status === "deprecated" || item.latest_verdict === "fail") {
    return { label: "Blocked", tone: "danger" };
  }
  if (item.latest_verdict === "pending") return { label: "Verifying", tone: "warning" };
  return { label: "Active", tone: "success" };
}

function StatusChip({ item, enabled }: { item: ItemSummary; enabled: boolean }) {
  const { label, tone } = statusChip(item, enabled);
  const colorVar = { success: "--eco-color-success", muted: "--eco-color-textMuted", warning: "--eco-color-warning", danger: "--eco-color-danger" }[tone];
  return (
    <span
      data-testid="yours-status-chip"
      data-status={label}
      style={{
        fontSize: "var(--eco-font-sizeXs)", padding: "2px 8px", borderRadius: "var(--eco-radius-full)",
        color: `var(${colorVar})`, border: `1px solid var(${colorVar})`,
      }}
    >
      {label}
    </span>
  );
}

const GROUP_ORDER: Array<{ origin: Install["origin"]; label: string }> = [
  { origin: "created", label: "Created by me" },
  { origin: "shared", label: "Shared with me" },
  { origin: "provisioned", label: "Org provisioned" },
  { origin: "required", label: "Required" },
  { origin: "added", label: "Added from Discover" },
];

export function Yours({ itemType, onOpen, onCreate, onDiscover, query = "", layout = "grid" }: {
  itemType: string;
  onOpen: (item: ItemSummary) => void;
  onCreate: () => void;
  onDiscover: () => void;
  /** CatalogScreen's Toolbar search box -- matches the reference mock's own
   * yoursView() (`S.q` filters both Discover and Yours by name+description). */
  query?: string;
  /** Item 2, M5 UI-polish review: CatalogScreen's own localStorage-backed
   * preference (a UI choice only, never data) -- default grid. Group
   * section headings (Created by me/Shared with me/etc.) stay the same
   * in both layouts; only how each group's own rows render changes. */
  layout?: "grid" | "list";
}) {
  const client = useEcosystemClient();
  const strings = useI18n();
  const [installs, setInstalls] = useState<Install[] | null>(null);
  const [legacyItems, setLegacyItems] = useState<LegacyItem[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const cacheKey = yoursCacheKey(itemType);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    let pollTimeout: ReturnType<typeof setTimeout> | null = null;
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

    client.getInstalls(itemType)
      .then((res) => {
        if (cancelled) return;
        setInstalls(res.installs);
        setLegacyItems(res.legacy_items);
        setYoursCache(cacheKey, { installs: res.installs, legacyItems: res.legacy_items });
        // Same "still verifying" poll as Discover.tsx -- an install whose
        // item is still mid-gate (async path, worker not done yet) must
        // eventually pick up its resolved status without a manual reload.
        const stillVerifying = res.installs.some((i) => i.item && i.item.latest_verdict === "pending");
        if (stillVerifying) {
          pollTimeout = setTimeout(() => { if (!cancelled) setRefreshKey((k) => k + 1); }, 2000);
        }
      })
      .catch((e) => { if (!cancelled) setError(e); });
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
    let debounce: ReturnType<typeof setTimeout> | null = null;
    const onFocus = () => {
      if (debounce) return;
      debounce = setTimeout(() => { debounce = null; refresh(); }, FOCUS_REFRESH_DEBOUNCE_MS);
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      if (debounce) clearTimeout(debounce);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [refresh]);

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
    return (
      <div data-testid="yours-loading" role="status" aria-label={strings.loading}>
        <YoursSkeleton layout={layout} />
      </div>
    );
  }

  if (installs.length === 0 && legacyItems.length === 0) {
    return <EmptyState message={strings.empty_yours} onDiscover={onDiscover} onCreate={onCreate} />;
  }

  // A row with no `item` (see the defensive check in InstallRow below) has
  // no name/description to match against -- it always stays visible rather
  // than silently disappearing behind a search that can't see it.
  const q = query.trim().toLowerCase();
  const matchesQuery = (name: string, description: string) => !q || `${name} ${description}`.toLowerCase().includes(q);
  const filteredInstalls = installs.filter((i) => !i.item || matchesQuery(i.item.display_name, i.item.description));
  const filteredLegacy = legacyItems.filter((l) => matchesQuery(l.item.display_name, l.item.description));

  if (q && filteredInstalls.length === 0 && filteredLegacy.length === 0) {
    return <p data-testid="yours-no-matches" style={{ color: "var(--eco-color-textMuted)" }}>None of your {itemType}s match &ldquo;{query}&rdquo;.</p>;
  }

  return (
    <div data-testid="yours-screen">
      {GROUP_ORDER.map(({ origin, label }) => {
        const rows = filteredInstalls.filter((i) => i.origin === origin);
        // "Created by me" is the one group with a friendly, actionable
        // empty hint -- every other empty group just renders nothing
        // (unchanged behavior), since "share/provision/require something"
        // isn't a self-serve action the way "create a skill" is.
        if (rows.length === 0) {
          if (origin !== "created" || q) return null;
          return (
            <section key={origin} data-testid="yours-group-empty-hint" style={{ marginBottom: "var(--eco-space-lg)" }}>
              <h3 style={{ fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)" }}>{label} (0)</h3>
              <p style={{ color: "var(--eco-color-textSecondary)", fontSize: "var(--eco-font-sizeSm)", margin: "4px 0 8px" }}>
                You haven&apos;t created anything yet.
              </p>
              <button
                type="button"
                onClick={onCreate}
                style={{ background: "none", border: "1px solid var(--eco-color-border)", borderRadius: "var(--eco-radius-md)", padding: "6px 12px", color: "var(--eco-color-accentSkill)", cursor: "pointer", fontSize: "var(--eco-font-sizeSm)" }}
              >
                Create a skill
              </button>
            </section>
          );
        }
        return (
          <InstallGroup key={origin} label={label} rows={rows} onOpen={onOpen} client={client} onChanged={refresh} layout={layout} />
        );
      })}
      {filteredLegacy.length > 0 && (
        <section data-testid="yours-legacy-group" style={{ marginBottom: "var(--eco-space-lg)" }}>
          <h3 style={{ fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)" }}>Available from existing skills</h3>
          {filteredLegacy.map((legacy) => (
            <div
              key={legacy.item.id}
              data-testid="yours-legacy-row"
              style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-sm)", padding: "var(--eco-space-sm) 0", borderBottom: "1px solid var(--eco-color-border)" }}
            >
              <ItemIcon iconUrl={legacy.item.icon_url} namespace={legacy.item.namespace} displayName={legacy.item.display_name} size={28} />
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, color: "var(--eco-color-textPrimary)" }}>{legacy.item.display_name}</div>
              </div>
              <button
                type="button"
                data-testid="yours-legacy-open"
                onClick={() => onOpen(legacy.item)}
                style={{ background: "none", border: "none", color: "var(--eco-color-accentSkill)", cursor: "pointer" }}
              >
                Open
              </button>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

function InstallGroup({ label, rows, onOpen, client, onChanged, layout }: {
  label: string; rows: Install[]; onOpen: (item: ItemSummary) => void;
  client: ReturnType<typeof useEcosystemClient>; onChanged: () => void; layout: "grid" | "list";
}) {
  return (
    <section data-testid="yours-group" data-group-label={label} data-layout={layout} style={{ marginBottom: "var(--eco-space-lg)" }}>
      <h3 style={{ fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)" }}>{label} ({rows.length})</h3>
      <div
        style={
          layout === "grid"
            ? { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "var(--eco-space-md)" }
            : undefined
        }
      >
        {rows.map((install) => (
          <InstallRow key={install.install_id} install={install} onOpen={onOpen} client={client} onChanged={onChanged} layout={layout} />
        ))}
      </div>
    </section>
  );
}

function InstallRow({ install, onOpen, client, onChanged, layout }: {
  install: Install; onOpen: (item: ItemSummary) => void;
  client: ReturnType<typeof useEcosystemClient>; onChanged: () => void; layout: "grid" | "list";
}) {
  // Defensive: CONTRACTS.md §9 documents `item` as always present on a
  // real Install row, and the backend is expected to guarantee that --
  // but a row this tolerant check can't protect against (a backend
  // regression, a future endpoint change) must never blank the whole
  // screen for every OTHER row too. One bad row shows "unavailable"
  // instead of crashing the list.
  if (!install.item) {
    return (
      <div
        data-testid="yours-install-row-unavailable"
        data-install-id={install.install_id}
        style={
          layout === "grid"
            ? { display: "flex", alignItems: "center", gap: "var(--eco-space-sm)", padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-lg)", border: "1px solid var(--eco-color-border)", color: "var(--eco-color-textSecondary)" }
            : { display: "flex", alignItems: "center", gap: "var(--eco-space-sm)", padding: "var(--eco-space-sm) 0", borderBottom: "1px solid var(--eco-color-border)", color: "var(--eco-color-textSecondary)" }
        }
      >
        <div style={{ flex: 1 }}>This item is no longer available.</div>
        <button
          type="button"
          onClick={() => client.uninstall(install.install_id).then(onChanged)}
          style={{ background: "none", border: "none", color: "var(--eco-color-accentSkill)", cursor: "pointer" }}
        >
          Remove
        </button>
      </div>
    );
  }

  // "Delete permanently"/"Retire" both destroy state a click can't undo --
  // confirmed before firing, same dialog whether triggered from the kebab
  // or the "Installed ▾" menu below (item 1, M5 UI-polish review).
  const [confirmAction, setConfirmAction] = useState<
    { kind: "delete" | "retire" | "unshare"; run: () => void } | null
  >(null);
  const askDelete = () => setConfirmAction({ kind: "delete", run: () => client.deleteDraft(install.item.id).then(onChanged) });
  const askRetire = () => setConfirmAction({ kind: "retire", run: () => client.deprecateItem(install.item.id).then(onChanged) });
  // Real gap, now fixed: POST /ecosystem/shares/{share_id}/unshare needs
  // the SHARE's own id (policy_service.unshare(share_id, ...)) -- a
  // recipient's own install had no way to look that up before
  // ItemSummary/Install gained `share_id` (the recipient's own relevant
  // EcosystemShare.id, resolved server-side in items_service._item_to_
  // summary()). "unshare" is only ever offered by compute_allowed_actions()
  // for the RECIPIENT'S own install.scope == "shared", and share_id is only
  // ever non-null in exactly that case -- no separate guard needed here.
  const askUnshare = () => setConfirmAction({
    kind: "unshare",
    run: () => { if (install.item.share_id) client.unshare(install.item.share_id).then(onChanged); },
  });

  // "Installed ▾" carries the primary, common actions (matches Detail.tsx's
  // own InstalledMenu, reused here for visual consistency between the two
  // screens); the kebab keeps only what InstalledMenu doesn't cover
  // (report/unshare -- deprecate/delete_draft moved to the shared confirm-
  // then-run handlers above, still reachable from either menu).
  const kebabActions = buildKebabActions(install.item.allowed_actions, {
    report: () => client.reportItem(install.item.id, "reported from Yours"),
    deprecate: askRetire,
    delete_draft: askDelete,
    unshare: askUnshare,
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
  const { label: statusLabel } = statusChip(install.item, install.enabled);
  // Per-surface toggles round (2026-09-29): the "Surfaces: ..." line that
  // used to live here is gone along with the toggle chips themselves --
  // normal users no longer manage per-surface enablement at all (see
  // Item 3's own admin-only "Advanced" override on the Detail page for
  // where that now lives), so there's nothing surface-shaped left for a
  // normal user's kebab to fold in here either.
  const infoLines = foldInfoIntoKebab
    ? [`${TRUST_LABEL[install.item.trust_tier]} • ${statusLabel}`]
    : undefined;
  const menus = (
    <>
      <InstalledMenu
        enabled={install.enabled}
        required={required}
        onToggleEnabled={(next) => client.setEnabled(install.install_id, next).then(onChanged)}
        // No tab deep-link exists yet -- opens Detail on its default tab;
        // the user clicks "Versions" themselves once there (disclosed
        // simplification, not a full deep-link).
        onViewVersions={() => onOpen(install.item)}
        onUninstall={() => client.uninstall(install.install_id).then(onChanged)}
        canDeleteDraft={install.item.allowed_actions.includes("delete_draft")}
        hasOtherInstalls={install.item.has_other_installs}
        canDeprecate={canDeprecate}
        onDeletePermanently={askDelete}
        onRetire={askRetire}
      />
      {(kebabActions.length > 0 || (infoLines && infoLines.length > 0)) && (
        <KebabMenu actions={kebabActions} infoLines={infoLines} />
      )}
    </>
  );
  return (
    <div
      data-testid="yours-install-row"
      data-install-id={install.install_id}
      data-layout={layout}
      className={isGrid ? undefined : "eco-yours-row-list"}
      style={
        isGrid
          ? { display: "flex", flexDirection: "column", gap: "var(--eco-space-sm)", padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-lg)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)" }
          : undefined
      }
    >
      {isGrid ? (
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
          <div style={{ display: "flex", alignItems: "flex-start", gap: "var(--eco-space-sm)" }}>
            <ItemIcon iconUrl={install.item.icon_url} namespace={install.item.namespace} displayName={install.item.display_name} size={28} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <button
                type="button"
                onClick={() => onOpen(install.item)}
                title={install.item.display_name}
                style={{
                  display: "block", width: "100%", background: "none", border: "none", padding: 0,
                  cursor: "pointer", fontWeight: 600, color: "var(--eco-color-textPrimary)", textAlign: "left",
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}
              >
                {install.item.display_name}
              </button>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "nowrap", overflow: "hidden" }}>
            {required && <RequiredLock />}
            <TrustBadge tier={install.item.trust_tier} />
            <StatusChip item={install.item} enabled={install.enabled} />
          </div>
          <div
            data-testid="yours-row-description"
            style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)", overflow: "hidden", textOverflow: "ellipsis", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}
          >
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
          <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: "8px", marginTop: "auto" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>{menus}</div>
          </div>
        </>
      ) : (
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
          <div className="eco-yours-row-list-name">
            <button
              type="button"
              onClick={() => onOpen(install.item)}
              title={install.item.display_name}
              className="eco-yours-row-list-name-text"
              style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontWeight: 600, color: "var(--eco-color-textPrimary)", textAlign: "left" }}
            >
              {install.item.display_name}
            </button>
            <div
              data-testid="yours-row-description"
              title={install.item.description}
              className="eco-yours-row-list-description"
              style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}
            >
              {install.item.description}
            </div>
          </div>
          {!narrow && (
            <div className="eco-yours-row-list-badges">
              {required && <RequiredLock />}
              <TrustBadge tier={install.item.trust_tier} />
            </div>
          )}
          <div>
            <StatusChip item={install.item} enabled={install.enabled} />
          </div>
          <div className="eco-yours-row-list-actions">{menus}</div>
        </>
      )}
      <ConfirmDialog
        open={confirmAction !== null}
        title={
          confirmAction?.kind === "delete" ? "Delete this skill permanently?"
            : confirmAction?.kind === "unshare" ? "Stop sharing this skill?"
              : "Retire this skill?"
        }
        message={
          confirmAction?.kind === "delete"
            ? `"${install.item.display_name}" and all of its versions and stored files will be permanently deleted. This can't be undone.`
            : confirmAction?.kind === "unshare"
              ? `"${install.item.display_name}" was shared with you -- unsharing removes it from the sharer's own share list. Your own copy is unaffected.`
              : `"${install.item.display_name}" will stop appearing as an active skill. Existing installs keep working until each is uninstalled.`
        }
        confirmLabel={confirmAction?.kind === "delete" ? "Delete permanently" : confirmAction?.kind === "unshare" ? "Unshare" : "Retire"}
        danger={confirmAction?.kind === "delete"}
        onConfirm={() => { confirmAction?.run(); setConfirmAction(null); }}
        onCancel={() => setConfirmAction(null)}
      />
    </div>
  );
}
