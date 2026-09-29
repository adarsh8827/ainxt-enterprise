// SPDX-License-Identifier: MIT
// Task F-5: the catalog card. Renders only from server-computed fields --
// no install_count anywhere (CONTRACTS.md §7's own closed-off schema).
import { useState } from "react";
import { CheckIcon, PlusIcon, XMarkIcon } from "@heroicons/react/24/outline";
import type { ItemSummary } from "../types";
import { isNotYetAddedCatalogItem } from "../catalogState";
import { attachInstallJob, beginInstall, failInstall, useInstallStatus } from "../installTracking";
import { applyInstallOverride, setInstallState, useInstallOverrideVersion } from "../installStore";
import { ItemIcon } from "./ItemIcon";
import { CatalogChecksPassedBadge, CompatibilityBadge, NeedsProductBadges, NewBadge, TrustBadge, VerdictBadge } from "./Badges";
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
  // Item 2 (2026-09-29 live-test round): install status is now tracked in
  // installTracking.ts's own module-level store, not local component
  // state -- surviving Discover -> Yours -> Discover (a full unmount/
  // remount of this whole card, CatalogScreen.tsx's own conditional
  // render) instead of resetting on remount and offering a fresh "Add"
  // (or worse, a false "Retry") for an install that's still genuinely in
  // flight server-side. onResolved (here, onInstalled) fires once a real
  // server GET (client.getJob(), polled by useInstallStatus itself) says
  // this install's job is no longer "verifying" -- never merely because
  // the original POST promise happened to resolve in THIS mounted
  // instance.
  const { phase, error } = useInstallStatus(item.id, client, onInstalled);
  const installing = phase === "installing";
  const [uninstalling, setUninstalling] = useState(false);
  const [uninstallError, setUninstallError] = useState<string | null>(null);

  if (item.install_id) {
    // Install-state-consistency round (2026-09-29): real bug -- this used
    // to be a read-only badge, offering no way to uninstall from Discover
    // at all (the user's own explicit test: "uninstall from Discover
    // works"). Locked to a plain badge (same as before) only when the
    // server itself says uninstall isn't offered (e.g. a required
    // install) -- matches InstalledMenu.tsx's own "Required (can't
    // remove)" convention rather than silently hiding a control the
    // server would reject anyway.
    if (!item.allowed_actions.includes("uninstall")) {
      return (
        <span
          data-testid="card-installed-badge"
          style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-success)" }}
        >
          <CheckIcon width={14} height={14} aria-hidden="true" /> Added
        </span>
      );
    }
    const handleUninstall = (e: React.MouseEvent) => {
      e.stopPropagation();
      const installId = item.install_id!;
      setUninstalling(true);
      setUninstallError(null);
      client.uninstall(installId)
        .then(() => {
          setInstallState(item.id, { install_id: null, enabled: null, install_scope: null, install_surfaces: null });
          onInstalled?.();
        })
        .catch((err: unknown) => {
          // Fix requirement: an action targeting an install that no
          // longer exists (already removed on another screen/tab between
          // this card's last fetch and this click) must refresh and show
          // the correct state, never fail silently or leave a stuck
          // spinner. client.getItem() is the real, authoritative re-check.
          const code = (err as { code?: string })?.code;
          if (code === "NOT_FOUND") {
            client.getItem(item.id).then((fresh) => {
              setInstallState(item.id, {
                install_id: fresh.install_id, enabled: fresh.enabled,
                install_scope: fresh.install_scope, install_surfaces: fresh.install_surfaces,
              });
              onInstalled?.();
            });
            return;
          }
          setUninstallError(err instanceof Error ? err.message : "Couldn't uninstall this item.");
        })
        .finally(() => setUninstalling(false));
    };
    return (
      <button
        type="button"
        data-testid="card-uninstall"
        disabled={uninstalling}
        onClick={handleUninstall}
        title={uninstallError ?? "Uninstall"}
        style={{
          display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "var(--eco-font-sizeXs)",
          color: uninstallError ? "var(--eco-color-danger)" : "var(--eco-color-success)",
          background: "none", border: "none", cursor: uninstalling ? "default" : "pointer", padding: 0,
        }}
      >
        {uninstallError ? "Retry" : uninstalling ? "Removing…" : (
          <>
            <CheckIcon width={14} height={14} aria-hidden="true" /> Added
            <XMarkIcon width={12} height={12} aria-hidden="true" />
          </>
        )}
      </button>
    );
  }
  if (!item.allowed_actions.includes("install")) return null;

  const handleAdd = (e: React.MouseEvent) => {
    e.stopPropagation(); // never also trigger the card's own onOpen
    // Marked "installing" the instant the click happens, in the shared
    // tracking store (not local state) -- a remount in the brief window
    // before the POST below even resolves must still read "installing,"
    // never a fresh "Add" (item 2's own repro).
    beginInstall(item.id);
    // Real bug found live (docs/ecosystem/design/LLD/gate.md's catalog-
    // checking round): a not-yet-added catalog item has no version to
    // look up yet at all -- getVersions() returns an empty list, so this
    // used to always throw "No version to install." for exactly the item
    // this button's whole job is to add. materialize_from_catalog() (the
    // load-tested backend piece from feature/ecosystem-external-sources,
    // already live in the shared testing environment) creates the real
    // version/gate run server-side at install time instead -- skip the
    // version lookup entirely and let the server handle it.
    const allSurfaces = config.surfaces.map((s) => s.key);
    const idempotencyKey = `card-add-${item.id}-${Date.now()}`;
    const installFor = (versionId: string | undefined) =>
      client.install(item.id, { version_id: versionId, surfaces: allSurfaces, scope: "private", origin: "added" }, idempotencyKey);

    (isNotYetAddedCatalogItem(item)
      ? installFor(undefined)
      : client.getVersions(item.id).then((versions) => {
          const versionId = versions.find((v) => v.is_current)?.id ?? versions[0]?.id;
          if (!versionId) throw new Error("No version to install.");
          return installFor(versionId);
        })
    )
      // Attaches the real job id install_item() just returned -- does NOT
      // itself clear "installing" or call onInstalled. useInstallStatus's
      // own poll (a fresh client.getJob() GET, the actual server-driven
      // signal) is what resolves this, even if THIS component has since
      // unmounted -- the tracking store it writes into lives outside this
      // closure.
      // Attaches the real job id install_item() just returned -- does NOT
      // itself clear "installing" or call onInstalled. useInstallStatus's
      // own poll (a fresh client.getJob() GET, the actual server-driven
      // signal) is what resolves this, even if THIS component has since
      // unmounted -- the tracking store it writes into lives outside this
      // closure. Deliberately does NOT push job.install_id into
      // installStore.ts optimistically -- a job can still be genuinely
      // "verifying" with an install row that exists but isn't the real,
      // final truth yet (Detail.test.tsx's own "survives an unmount +
      // remount mid-install" test covers exactly this); onInstalled
      // (fired only once useInstallStatus's poll confirms resolution)
      // triggers Discover/Yours/Detail's own real re-fetch, which is what
      // actually broadcasts the confirmed state into installStore.ts.
      .then((job) => attachInstallJob(item.id, job.job_id))
      .catch((err: unknown) => failInstall(item.id, err instanceof Error ? err.message : "Couldn't add this item."));
  };

  return (
    <button
      type="button"
      data-testid="card-quick-add"
      disabled={installing}
      onClick={handleAdd}
      title={error ?? undefined}
      style={{
        // Item 4 (2026-09-28, real screenshot at 1920px): this used to be
        // a tiny ad-hoc XS-font pill of its own. The user's ask is that
        // this and InstalledMenu's trigger both use the app's STANDARD
        // control height instead -- same padding/box-sizing/border-width
        // as InstalledMenu's own trigger (detail/InstalledMenu.tsx),
        // which itself matches the toolbar's own controls (AddMenu's
        // "+ Add", search, filter/sort). Border is transparent (rather
        // than "none") so the 1px border-box contribution is present
        // either way -- a 0-vs-1px border would itself shift height by
        // 2px even with identical padding.
        boxSizing: "border-box",
        display: "inline-flex", alignItems: "center", gap: "4px",
        padding: "8px 12px", borderRadius: "var(--eco-radius-md)",
        border: "1px solid transparent", cursor: "pointer",
        background: error ? "var(--eco-color-dangerBg)" : "var(--eco-color-accentSkill)",
        color: error ? "var(--eco-color-danger)" : "var(--eco-color-accentSkillText)",
      }}
    >
      <PlusIcon width={14} height={14} aria-hidden="true" /> {installing ? "Adding…" : error ? "Retry" : "Add"}
    </button>
  );
}

export function Card({ item: rawItem, onOpen, onInstalled }: CardProps) {
  // Install-state-consistency round (2026-09-29): subscribes to the
  // shared installStore so a mutation made elsewhere (Yours.tsx's
  // uninstall, Detail.tsx's install/uninstall, another browser tab via
  // client.streamChanges()) re-renders this card with the corrected
  // install_id/enabled immediately, even while THIS card stays mounted
  // (not just on Discover's own next remount/refetch).
  useInstallOverrideVersion();
  const item = applyInstallOverride(rawItem);
  const blocked = item.latest_verdict === "fail";
  const notYetAdded = isNotYetAddedCatalogItem(item);
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
        {/* Real bug found live (docs/ecosystem/design/LLD/gate.md's
            catalog-checking round): a not-yet-added catalog item has no
            gate run at all -- VerdictBadge's own "pending" fallback
            (backend default when latest_verdict has no real version to
            read from) rendered as "Verifying...", implying an install was
            already in flight for an item nobody had touched. */}
        {notYetAdded ? <CatalogChecksPassedBadge /> : <VerdictBadge verdict={item.latest_verdict} />}
        {item.is_new && <NewBadge />}
        <CompatibilityBadge compatibility={item.compatibility} />
        <NeedsProductBadges tags={item.tags} />
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
