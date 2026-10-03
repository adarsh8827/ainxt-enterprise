// SPDX-License-Identifier: MIT
// Task F-5: the catalog card. Renders only from server-computed fields --
// no install_count anywhere (CONTRACTS.md §7's own closed-off schema).
import { useState } from "react";
import { CheckIcon, PlusIcon, XMarkIcon } from "@heroicons/react/24/outline";
import { isNotYetAddedCatalogItem } from "./lib/catalogState";
import { attachInstallJob, beginInstall, failInstall, useInstallStatus } from "./lib/installTracking";
import { applyInstallOverride, setInstallState, useInstallOverrideVersion } from "./lib/installStore";
import { ItemIcon } from "./ItemIcon";
import { ConfirmDialog } from "./ConfirmDialog";
import { Spinner } from "./Spinner";
import { CatalogChecksPassedBadge, CompatibilityBadge, NeedsProductBadges, NewBadge, TrustBadge, VerdictBadge, VerifiedMark } from "./Badges";
import { publisherLabel } from "./lib/publisherLabel";
import { useEcosystemClient } from "./lib/context/HostContext";
import { useConfig } from "./lib/hooks/useEcosystemConfig";
/** Real bug found live: Discover cards had no state indicator at all --
 * every card looked identical to Yours' rows, whether installed or not.
 * A quick "+ Add" button (mirrors Detail.tsx's own one-click doQuickInstall
 * -- private scope, chat surface, no dialog) when `install_id` is null;
 * "Added" once it's set. `allowed_actions.includes("install")` is the
 * server's own signal for whether Add is even offered at all (a blocked
 * or already-installed item has it removed -- items_service.compute_
 * allowed_actions()), so this button never has to re-derive that itself. */
function QuickAddButton({
  item,
  onInstalled
}) {
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
  const {
    phase,
    error
  } = useInstallStatus(item.id, client, onInstalled);
  const installing = phase === "installing";
  const [uninstalling, setUninstalling] = useState(false);
  const [uninstallError, setUninstallError] = useState(null);
  // Confirm before removing (user-flow QA round 2, 2026-10-03): this used
  // to call client.uninstall() straight from the click, no confirmation --
  // the one-click "Added ✕" was the easiest of all three uninstall entry
  // points in this package to fat-finger. Same ConfirmDialog/wording as
  // Detail.tsx's and Yours.tsx's own uninstall confirms.
  const [confirmUninstall, setConfirmUninstall] = useState(false);
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
      return <span data-testid="card-installed-badge" className="inline-flex items-center gap-1 text-xs text-green-700">
          <CheckIcon width={14} height={14} aria-hidden="true" /> Added
        </span>;
    }
    const handleUninstallClick = e => {
      e.stopPropagation(); // never also trigger the card's own onOpen
      setConfirmUninstall(true);
    };
    const doUninstall = () => {
      setConfirmUninstall(false);
      const installId = item.install_id;
      setUninstalling(true);
      setUninstallError(null);
      client.uninstall(installId).then(() => {
        setInstallState(item.id, {
          install_id: null,
          enabled: null,
          install_scope: null,
          install_surfaces: null
        });
        onInstalled?.();
      }).catch(err => {
        // Fix requirement: an action targeting an install that no
        // longer exists (already removed on another screen/tab between
        // this card's last fetch and this click) must refresh and show
        // the correct state, never fail silently or leave a stuck
        // spinner. client.getItem() is the real, authoritative re-check.
        const code = err?.code;
        if (code === "NOT_FOUND") {
          client.getItem(item.id).then(fresh => {
            setInstallState(item.id, {
              install_id: fresh.install_id,
              enabled: fresh.enabled,
              install_scope: fresh.install_scope,
              install_surfaces: fresh.install_surfaces,
              allowed_actions: fresh.allowed_actions
            });
            onInstalled?.();
          });
          return;
        }
        setUninstallError(err instanceof Error ? err.message : "Couldn't uninstall this item.");
      }).finally(() => setUninstalling(false));
    };
    return <>
        <button type="button" data-testid="card-uninstall" disabled={uninstalling} onClick={uninstallError ? e => {
        e.stopPropagation();
        doUninstall();
      } : handleUninstallClick} title={uninstallError ?? "Uninstall"} className={["inline-flex items-center gap-1 text-xs bg-none border-none p-0 transition-colors", uninstallError ? "text-red-600 hover:opacity-70" : "text-green-700 hover:opacity-70", uninstalling ? "cursor-default" : "cursor-pointer"].join(" ")}>
          {uninstallError ? "Retry" : uninstalling ? "Removing…" : <>
              <CheckIcon width={14} height={14} aria-hidden="true" /> Added
              <XMarkIcon width={12} height={12} aria-hidden="true" />
            </>}
        </button>
        <ConfirmDialog open={confirmUninstall} title="Uninstall this skill?" message={`"${item.display_name}" will be removed from your installed skills. You can add it again later from Discover.`} confirmLabel="Uninstall" danger onConfirm={doUninstall} onCancel={() => setConfirmUninstall(false)} />
      </>;
  }
  if (!item.allowed_actions.includes("install")) return null;
  const handleAdd = e => {
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
    const allSurfaces = config.surfaces.map(s => s.key);
    const idempotencyKey = `card-add-${item.id}-${Date.now()}`;
    const installFor = versionId => client.install(item.id, {
      version_id: versionId,
      surfaces: allSurfaces,
      scope: "private",
      origin: "added"
    }, idempotencyKey);
    (isNotYetAddedCatalogItem(item) ? installFor(undefined) : client.getVersions(item.id).then(versions => {
      const versionId = versions.find(v => v.is_current)?.id ?? versions[0]?.id;
      if (!versionId) throw new Error("No version to install.");
      return installFor(versionId);
    })

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
    ).then(job => attachInstallJob(item.id, job.job_id)).catch(err => failInstall(item.id, err instanceof Error ? err.message : "Couldn't add this item."));
  };
  return <button type="button" data-testid="card-quick-add" disabled={installing} onClick={handleAdd} title={error ?? undefined} aria-busy={installing || undefined} className={["inline-flex items-center gap-1 px-3 py-2 rounded text-xs font-medium border border-transparent transition-colors", error ? "bg-red-50 text-red-600 hover:opacity-70" : "text-white brand-grad hover:opacity-70", installing ? "cursor-default" : "cursor-pointer"].join(" ")}>
      {/* Busy spinner instead of the static Plus icon while installing
          (user-flow QA round 3, 2026-10-03) -- this control was already
          correctly disabled during the request, but had no VISUAL busy
          signal beyond the "Adding…" text swap. */}
      {installing ? <Spinner size={14} /> : <PlusIcon width={14} height={14} aria-hidden="true" />} {installing ? "Adding…" : error ? "Retry" : "Add"}
    </button>;
}
export function Card({
  item: rawItem,
  onOpen,
  onInstalled
}) {
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
    <div role="button" tabIndex={0} data-testid="item-card" data-item-id={item.id} onClick={() => onOpen(item)} onKeyDown={e => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onOpen(item);
      }
    }} className={["flex flex-col gap-2 p-4 rounded-xl border border-gray-200 bg-white shadow-sm text-left w-full cursor-pointer transition-colors hover:bg-gray-50", blocked ? "opacity-70" : ""].join(" ")}>
      {/* Reference-layout parity (Connectors+Plugins UI redesign,
          2026-09-30): icon LEFT, a text column to its right (name +
          verified mark on one line, description, "by <maker>"), and the
          quick-add control pinned top-right of the whole row -- matching
          the reference design's card anatomy exactly, replacing the old
          icon-name-only header + bottom-pinned footer button shape. The
          functional badges row (trust/verdict/compatibility/needs-product)
          this project already relies on has no equivalent in the
          reference design at all -- kept, but moved below the "by maker"
          line as a secondary, condensed row rather than dropped, so
          nothing users already depend on (e.g. a blocked/pending gate
          verdict) silently disappears. */}
      <div className="flex items-start gap-2">
        <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span title={item.display_name} className="block font-semibold text-sm text-gray-900 overflow-hidden text-ellipsis whitespace-nowrap">
              {item.display_name}
            </span>
            <VerifiedMark tier={item.trust_tier} />
          </div>
          <p className="mt-0.5 mb-0 text-sm text-gray-500 overflow-hidden text-ellipsis" style={{
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical"
          }}>
            {item.description}
          </p>
          <span className="block mt-1 text-xs text-gray-400">
            by {publisherLabel(item.namespace)}
          </span>
        </div>
        <div className="flex-shrink-0">
          <QuickAddButton item={item} onInstalled={onInstalled} />
        </div>
      </div>
      {/* Secondary, condensed badges row -- see comment above. */}
      <div className="flex items-center gap-1.5 flex-nowrap overflow-hidden">
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
    </div>
  );
}