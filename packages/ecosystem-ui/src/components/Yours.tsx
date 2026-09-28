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
import { SurfaceToggles } from "./SurfaceToggles";
import { KebabMenu, buildKebabActions } from "./KebabMenu";
import { InstalledMenu } from "./detail/InstalledMenu";
import { EmptyState } from "./EmptyState";
import { ConfirmDialog } from "./ConfirmDialog";
import "./Yours.css";

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

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    client.getInstalls(itemType)
      .then((res) => {
        if (cancelled) return;
        setInstalls(res.installs);
        setLegacyItems(res.legacy_items);
      })
      .catch((e) => { if (!cancelled) setError(e); });
    return () => { cancelled = true; };
  }, [client, itemType, refreshKey]);

  if (error) return <div data-testid="yours-error" role="alert">Couldn't load your items. Please try again.</div>;
  if (installs === null) return <div data-testid="yours-loading">{strings.verifying}</div>;

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
  // Local, optimistically-updated copy of the install's surfaces (task 4:
  // the checkboxes need to flip immediately on click, before the real
  // PATCH round-trips) -- must be declared before the early return below
  // so this hook always runs in the same order (rules of hooks), even
  // though it's meaningless for the `!install.item` branch.
  const [surfaces, setSurfaces] = useState(install.surfaces);
  useEffect(() => setSurfaces(install.surfaces), [install.surfaces]);

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
    { kind: "delete" | "retire"; run: () => void } | null
  >(null);
  const askDelete = () => setConfirmAction({ kind: "delete", run: () => client.deleteDraft(install.item.id).then(onChanged) });
  const askRetire = () => setConfirmAction({ kind: "retire", run: () => client.deprecateItem(install.item.id).then(onChanged) });

  // "Installed ▾" carries the primary, common actions (matches Detail.tsx's
  // own InstalledMenu, reused here for visual consistency between the two
  // screens); the kebab keeps only what InstalledMenu doesn't cover
  // (report -- deprecate/delete_draft moved to the shared confirm-then-
  // run handlers above, still reachable from either menu).
  //
  // "unshare" is deliberately NOT wired here -- real, pre-existing gap
  // found while implementing this (2026-09-28, not introduced by this
  // change): POST /ecosystem/shares/{share_id}/unshare needs the SHARE's
  // own id (policy_service.unshare(share_id, ...)), but a recipient's
  // own ItemSummary/Install never exposes that id anywhere -- only the
  // sharer's side (services/ecosystem/policy_service.share()) knows it.
  // compute_allowed_actions() offers "unshare" to the RECIPIENT (their
  // own install.scope == "shared"), which the current API has no way to
  // action from the client. Flagging this rather than wiring a call that
  // would 404 -- needs its own backend fix (e.g. resolving share_id from
  // install_id server-side) before a real "Unshare" button can work.
  const kebabActions = buildKebabActions(install.item.allowed_actions, {
    report: () => client.reportItem(install.item.id, "reported from Yours"),
    deprecate: askRetire,
    delete_draft: askDelete,
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
  const infoLines = foldInfoIntoKebab
    ? [
        `${TRUST_LABEL[install.item.trust_tier]} • ${statusLabel}`,
        surfaces.length > 0 ? `Surfaces: ${surfaces.join(", ")}` : "Surfaces: none",
      ]
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
  const surfaceToggles = (
    <SurfaceToggles
      enabledSurfaces={surfaces}
      disabled={required}
      onChange={(next) => {
        const previous = surfaces;
        setSurfaces(next); // optimistic -- flips the chip immediately
        client.setSurfaces(install.install_id, next).catch(() => setSurfaces(previous)); // roll back on error
      }}
    />
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
          {/* Real bug found live: this row had no minWidth:0/flexShrink
              constraints, so a card with several surface chips AND a
              longer name/description let the chips row push past the
              card's width instead of clipping -- flex items default to a
              min-width of their own content, not 0. `flex: 1 1 auto` +
              `minWidth: 0` lets the surfaceToggles wrapper actually
              shrink and clip (its own overflow: hidden); `flexShrink: 0`
              on the menus side keeps "Installed ▾"/kebab from ever being
              squeezed. */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", marginTop: "auto" }}>
            <div style={{ flex: "1 1 auto", minWidth: 0, overflow: "hidden" }}>{surfaceToggles}</div>
            <div style={{ display: "flex", alignItems: "center", gap: "6px", flexShrink: 0 }}>{menus}</div>
          </div>
        </>
      ) : (
        // Item 1 (M5 UI-polish round 2, 2026-09-28, real screenshot at
        // 1920px): rebuilt as a real CSS grid (Yours.css) with fixed,
        // named columns -- [icon 32px] [name + one-line description,
        // flexible] [badges, fixed] [surfaces, fixed] [status] [actions,
        // fixed, right-aligned]. Every row shares the exact same column
        // widths, so the actions column lines up exactly across rows
        // regardless of any other column's content -- the previous
        // version was a flex column (name+badges on one line, description
        // on a second, surfaces on a third), which had no shared column
        // grid at all and made "line up the actions column" impossible.
        // Below ~1100px (LIST_NARROW_QUERY, matching Yours.css's own
        // breakpoint), the badges/surfaces columns collapse out of the
        // grid and their info folds into the kebab menu instead
        // (infoLines above) rather than wrapping.
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
          {!narrow && <div className="eco-yours-row-list-surfaces">{surfaceToggles}</div>}
          <div>
            <StatusChip item={install.item} enabled={install.enabled} />
          </div>
          <div className="eco-yours-row-list-actions">{menus}</div>
        </>
      )}
      <ConfirmDialog
        open={confirmAction !== null}
        title={confirmAction?.kind === "delete" ? "Delete this skill permanently?" : "Retire this skill?"}
        message={
          confirmAction?.kind === "delete"
            ? `"${install.item.display_name}" and all of its versions and stored files will be permanently deleted. This can't be undone.`
            : `"${install.item.display_name}" will stop appearing as an active skill. Existing installs keep working until each is uninstalled.`
        }
        confirmLabel={confirmAction?.kind === "delete" ? "Delete permanently" : "Retire"}
        danger={confirmAction?.kind === "delete"}
        onConfirm={() => { confirmAction?.run(); setConfirmAction(null); }}
        onCancel={() => setConfirmAction(null)}
      />
    </div>
  );
}
