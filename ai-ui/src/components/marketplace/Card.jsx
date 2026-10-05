// SPDX-License-Identifier: MIT
// Task F-5: the catalog card. Renders only from server-computed fields --
// no install_count anywhere (CONTRACTS.md §7's own closed-off schema).
import { useState } from "react";
import { CheckIcon, PlusIcon, ExclamationTriangleIcon } from "@heroicons/react/24/outline";
import { isNotYetAddedCatalogItem } from "./lib/catalogState";
import { attachInstallJob, beginInstall, failInstall, useInstallStatus } from "./lib/installTracking";
import { applyInstallOverride, setInstallState, useInstallOverrideVersion } from "./lib/installStore";
import { ItemIcon } from "./ItemIcon";
import { ConfirmDialog } from "./ConfirmDialog";
import { Spinner } from "./Spinner";
import { VerdictIcon, VerifiedMark } from "./Badges";
import { useEcosystemClient } from "./lib/context/HostContext";
import { useConfig } from "./lib/hooks/useEcosystemConfig";
import { useOptionalToast } from "./lib/useOptionalToast";
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
  const toast = useOptionalToast();
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
      // Card density pass (2026-10-05): a small circular check, Claude-
      // style, replacing the text pill -- the state text itself moves to
      // an sr-only span (same copy, same toHaveTextContent assertions in
      // Card.test.jsx keep passing unchanged) so screen readers still get
      // the full "Added" announcement even though sighted users just see
      // an icon now.
      return <span data-testid="card-installed-badge" title="Added" className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-green-50 text-green-600 flex-shrink-0">
          <CheckIcon width={15} height={15} aria-hidden="true" />
          <span className="sr-only">Added</span>
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
        toast.success(`"${item.display_name}" uninstalled.`);
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
        const message = err instanceof Error ? err.message : "Couldn't uninstall this item.";
        setUninstallError(message);
        toast.error(message);
      }).finally(() => setUninstalling(false));
    };
    // Card density pass (2026-10-05): one small circular icon button
    // instead of a text+icon inline link -- check (installed, click to
    // uninstall) / spinner (removing) / warning triangle (retry an error),
    // same three states as before, just icon-led. sr-only text preserves
    // every existing toHaveTextContent assertion in Card.test.jsx.
    return <>
        <button type="button" data-testid="card-uninstall" disabled={uninstalling} onClick={uninstallError ? e => {
        e.stopPropagation();
        doUninstall();
      } : handleUninstallClick} title={uninstallError ? "Retry" : "Added — click to uninstall"} aria-busy={uninstalling || undefined} className={["inline-flex items-center justify-center w-7 h-7 rounded-full border-none transition-colors flex-shrink-0", uninstallError ? "bg-red-50 text-red-600 hover:bg-red-100" : "bg-green-50 text-green-600 hover:bg-red-50 hover:text-red-600", uninstalling ? "cursor-default" : "cursor-pointer"].join(" ")}>
          {uninstallError ? <>
              <ExclamationTriangleIcon width={15} height={15} aria-hidden="true" />
              <span className="sr-only">Retry</span>
            </> : uninstalling ? <>
              <Spinner size={14} />
              <span className="sr-only">Removing…</span>
            </> : <>
              <CheckIcon width={15} height={15} aria-hidden="true" />
              <span className="sr-only">Added</span>
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
    ).then(job => {
      attachInstallJob(item.id, job.job_id);
      toast.success(`"${item.display_name}" added.`);
    }).catch(err => {
      const message = err instanceof Error ? err.message : "Couldn't add this item.";
      failInstall(item.id, message);
      toast.error(message);
    });
  };
  // Card density pass (2026-10-05): a small circular "+" instead of a
  // boxed brand-gradient button with a text label -- same three states
  // (idle/busy/error), sr-only text preserves every existing
  // toHaveTextContent assertion in Card.test.jsx.
  return <button type="button" data-testid="card-quick-add" disabled={installing} onClick={handleAdd} title={error ?? "Add"} aria-busy={installing || undefined} className={["inline-flex items-center justify-center w-7 h-7 rounded-full border-none transition-colors flex-shrink-0", error ? "bg-red-50 text-red-600 hover:bg-red-100" : "text-white brand-grad hover:opacity-80", installing ? "cursor-default" : "cursor-pointer"].join(" ")}>
      {/* Busy spinner instead of the static Plus icon while installing
          (user-flow QA round 3, 2026-10-03) -- this control was already
          correctly disabled during the request, but had no VISUAL busy
          signal beyond the "Adding…" text swap. */}
      {installing ? <Spinner size={14} /> : error ? <ExclamationTriangleIcon width={15} height={15} aria-hidden="true" /> : <PlusIcon width={15} height={15} aria-hidden="true" />}
      <span className="sr-only">{installing ? "Adding…" : error ? "Retry" : "Add"}</span>
    </button>;
}
export function Card({
  item: rawItem,
  onOpen,
  onInstalled,
  layout = "grid"
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
  const isList = layout === "list";
  return (
    // A real <button data-testid="card-quick-add"> now lives inside this
    // card (a nested <button> is invalid HTML) -- the card itself is a
    // div with role="button" instead, same click/keyboard behavior.
    //
    // Card density pass (2026-10-05, explicit product ask: "very minimal,
    // important information... makes card uglier... keep it in detail
    // page"): the old secondary badges row (trust/verdict/new/
    // compatibility/needs-product, up to 5 capsule pills) and the "by
    // <maker>" byline are both gone -- Detail.tsx already renders every
    // one of them unchanged, one click away. What's left on the card is
    // exactly: icon, name (+ a small verified-mark icon when earned),
    // ONE line of description, a verdict icon ONLY when something's
    // actually worth flagging (silence means "checks passed" -- see
    // VerdictIcon's own comment in Badges.jsx), and the install-state
    // control. hover:shadow-md replaces the old hover:bg-gray-50 fill for
    // a slightly richer, premium hover without adding any visual weight
    // to the resting state.
    //
    // Discover list-view pass (2026-10-05, explicit product ask: "why we
    // dont have list/grid toggle icons views in discover page"): the name/
    // description/action-button content is layout-agnostic (same markup
    // either way) -- only the outer shell changes, same split Yours.tsx's
    // own InstallRow already draws between its two layouts. List mode
    // drops the card's border/radius/shadow for a flat, divider-separated
    // row (border-b, no rounded corners) and shrinks the icon from 40px to
    // 32px, matching InstallRow's own list-row icon size exactly.
    <div role="button" tabIndex={0} data-testid="item-card" data-item-id={item.id} data-layout={layout} onClick={() => onOpen(item)} onKeyDown={e => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onOpen(item);
      }
    }} className={[isList ? "flex items-center gap-3 px-3 py-2.5 border-b border-gray-200 hover:bg-gray-50 transition-colors" : "flex items-start gap-3 p-4 rounded-xl border border-gray-200 bg-white hover:shadow-md transition-shadow", "text-left w-full cursor-pointer", blocked ? "opacity-70" : ""].join(" ")}>
      <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} size={isList ? 32 : 40} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span title={item.display_name} className="block font-semibold text-sm text-gray-900 overflow-hidden text-ellipsis whitespace-nowrap">
            {item.display_name}
          </span>
          <VerifiedMark tier={item.trust_tier} />
          {/* Real bug found live (docs/ecosystem/design/LLD/gate.md's
              catalog-checking round): a not-yet-added catalog item has no
              gate run at all -- a "pending" fallback (backend default
              when latest_verdict has no real version to read from) must
              never read as "Verifying...", implying an install already
              in flight for an item nobody has touched. */}
          {!notYetAdded && <VerdictIcon verdict={item.latest_verdict} />}
        </div>
        <p className="mt-0.5 mb-0 text-sm text-gray-500 overflow-hidden text-ellipsis whitespace-nowrap">
          {item.description}
        </p>
      </div>
      <div className="flex-shrink-0 self-center">
        <QuickAddButton item={item} onInstalled={onInstalled} />
      </div>
    </div>
  );
}