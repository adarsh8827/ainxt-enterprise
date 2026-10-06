// SPDX-License-Identifier: MIT
// Task F-7: Detail page -- Back, blocked banner, header badges, meta
// line with no install-count, tabs, AddDialog, RiskSidePanel. Copy Link
// was removed (not required) -- Back + the browser's own address bar
// cover that need.
import { useEffect, useState } from "react";
import { ArrowLeftIcon } from "@heroicons/react/24/outline";
import { isNotYetAddedCatalogItem } from "./lib/catalogState";
import { attachInstallJob, beginInstall, failInstall, useInstallStatus } from "./lib/installTracking";
import { applyInstallOverride, removeInstallTracking, setInstallState, useInstallOverrideVersion } from "./lib/installStore";
import { useEcosystemClient, useHost } from "./lib/context/HostContext";
import { ItemIcon } from "./ItemIcon";
import { TrustBadge, VerdictBadge, NewBadge, CompatibilityBadge, NeedsProductBadges, CatalogChecksPassedBadge } from "./Badges";
import { Overview } from "./detail/Overview";
import { Contents } from "./detail/Contents";
import { Versions } from "./detail/Versions";
import { Verification } from "./detail/Verification";
import { License } from "./detail/License";
import { AddDialog } from "./detail/AddDialog";
import { RiskSidePanel } from "./detail/RiskSidePanel";
import { EditContent } from "./detail/EditContent";
import { InstalledMenu } from "./detail/InstalledMenu";
import { ConfirmDialog } from "./ConfirmDialog";
import { Button } from "./Button";
import { useConfig } from "./lib/hooks/useEcosystemConfig";
import { useOptionalToast } from "./lib/useOptionalToast";
import { LoadingState } from "./LoadingState";
import { catalogPath } from "./lib/routing";
import { PluginContentsSummary } from "./Plugins/PluginContentsSummary";
import { PluginRiskSummary } from "./Plugins/PluginRiskSummary";
import { PluginPartsList } from "./Plugins/PluginPartsList";
import { ConnectorDetail } from "./Connectors/ConnectorDetail";
const BASE_TABS = [{
  key: "overview",
  label: "Overview"
}, {
  key: "contents",
  label: "Contents"
}, {
  key: "versions",
  label: "Versions"
}, {
  key: "verification",
  label: "Verification"
}, {
  key: "license",
  label: "License"
}];
const EMPTY_PLUGIN_PARTS = {
  skills: [],
  commands: [],
  agents: [],
  connectors: [],
  mcp_servers: [],
  hooks: []
};
export function Detail({
  idOrNamespace,
  typeSlug,
  initialTab,
  onBack
}) {
  const client = useEcosystemClient();
  const {
    router
  } = useHost();
  const config = useConfig();
  const toast = useOptionalToast();
  const [rawItem, setItem] = useState(null);
  const [currentVersionId, setCurrentVersionId] = useState(null);
  const [error, setError] = useState(null);
  // BUG-U04 fix: Yours' "Versions & rollback" menu item used to always
  // open this page on "overview" (the hardcoded default below), forcing an
  // extra click onto the Versions tab every time. `initialTab` is a
  // one-time deep-link seed from the route (see lib/routing.js) -- once
  // mounted, tab switches are still local state only, same as before.
  const [tab, setTab] = useState(BASE_TABS.some(t => t.key === initialTab) ? initialTab : "overview");
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [togglingEnabled, setTogglingEnabled] = useState(false);
  const [uninstallError, setUninstallError] = useState(null);
  // "Delete permanently"/"Retire" (item 1, M5 UI-polish review) -- must
  // be declared here, before the early returns below, not further down
  // where handleDeletePermanently/handleRetire are defined: a real bug
  // found live ("Rendered more hooks than during the previous render")
  // from declaring it after those returns, since the hook then only ran
  // on renders that got past both of them.
  // "uninstall"/"disable" added (user-flow QA round 2, 2026-10-03): these
  // used to fire handleUninstall/handleToggleEnabled(false) directly with
  // zero confirmation, unlike delete/retire's existing confirm-then-run
  // pattern below -- same shared ConfirmDialog, just two more kinds.
  const [confirmAction, setConfirmAction] = useState(null);
  // User-flow QA round 5 (2026-10-03): the Edit tab had a working Save but
  // no Cancel and no leave-guard at all -- switching tabs or clicking Back
  // mid-edit silently discarded edits with zero warning. EditContent now
  // reports its own dirty state up here via onDirtyChange so tab-switch/Back
  // can route through the same "leave-edit" ConfirmDialog kind below instead
  // of just calling setTab/onBack directly.
  const [editDirty, setEditDirty] = useState(false);
  // Item 2 (2026-09-29 live-test round): install status lives in
  // installTracking.ts's own module-level store, not local state -- see
  // Card.tsx's own QuickAddButton for the full rationale (surviving an
  // unmount/remount of this whole page, e.g. Back to the catalog list and
  // in again, without losing track of a still-in-flight install or
  // falsely offering "Retry"). Keyed by item?.id, not idOrNamespace
  // (item.id is the SAME real id Card.tsx tracks this item under) --
  // falls back to "" before item has loaded, since this hook must be
  // called unconditionally, in the same position every render, ahead of
  // the early returns just below (same rule as confirmAction above).
  const {
    phase: installPhase,
    error: installError
  } = useInstallStatus(rawItem?.id ?? "", client, () => setRefreshKey(k => k + 1));
  const installing = installPhase === "installing";
  // Install-state-consistency round (2026-09-29): subscribes to the
  // shared installStore -- see Card.tsx's own useInstallOverrideVersion()
  // call for the full rationale (a change made elsewhere, same tab or
  // another, corrects this page immediately).
  useInstallOverrideVersion();
  useEffect(() => {
    let cancelled = false;
    setError(null);
    client.getItem(idOrNamespace).then(i => {
      if (cancelled) return;
      setItem(i);
      // Every real fetch here is ground truth -- broadcasting it to the
      // shared store on every successful load/reload (not just after a
      // specific install/uninstall click) means AddDialog's own Add,
      // doQuickInstall, handleUninstall, and handleToggleEnabled below
      // all correct every OTHER mounted screen/tab the instant this
      // page's own refreshKey-triggered re-fetch resolves, with no
      // separate per-action patch needed here.
      setInstallState(i.id, {
        install_id: i.install_id,
        enabled: i.enabled,
        install_scope: i.install_scope,
        install_surfaces: i.install_surfaces,
        allowed_actions: i.allowed_actions
      });
    }).catch(e => {
      if (!cancelled) setError(e);
    });
    return () => {
      cancelled = true;
    };
  }, [client, idOrNamespace, refreshKey]);

  // Install-state-consistency round (2026-09-29): the cross-tab half --
  // same-tab changes are already covered by installStore's own
  // subscription (useInstallOverrideVersion above); a change made in a
  // DIFFERENT tab needs the real ecosystem.changed SSE stream to know to
  // re-fetch at all.
  useEffect(() => {
    return client.streamChanges?.(() => setRefreshKey(k => k + 1));
  }, [client]);

  // ItemDetail's own `latest_version` (CONTRACTS.md §9) is a version
  // STRING ("1.0.0"), not the UUID `install()` actually needs -- resolve
  // the current version's real id from the versions list rather than
  // fabricating one.
  useEffect(() => {
    if (!rawItem) return;
    let cancelled = false;
    client.getVersions(rawItem.id).then(versions => {
      if (cancelled) return;
      setCurrentVersionId(versions.find(v => v.is_current)?.id ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [client, rawItem?.id]);
  if (error) return <div data-testid="detail-error" role="alert">This item isn't available.</div>;
  if (rawItem === null) return <div data-testid="detail-loading"><LoadingState /></div>;
  // Install-state-consistency round (2026-09-29): merges the freshest
  // known override (a mutation made elsewhere, same tab or another) onto
  // this page's own fetched item -- see Card.tsx's own applyInstallOverride
  // call for the full rationale.
  const item = applyInstallOverride(rawItem);
  // Real confusion found live (2026-10-06, user report): this used to be
  // driven purely by item.latest_verdict (the NEWEST version's own
  // verdict) -- an installed caller pinned to an OLDER, still-good
  // version saw the exact same scary "failed verification" banner as
  // someone whose actual running install had failed, with zero way to
  // tell the two apart. Once installed, installed_verdict (this specific
  // install's own pinned version) is what actually matters; latest_verdict
  // only still applies to the not-yet-installed "can't be added" case
  // (Discover), where there's no install of its own to have a verdict yet.
  const blocked = item.status === "yanked" || (item.install_id ? item.installed_verdict === "fail" : item.latest_verdict === "fail");
  // The other half of the same fix: a newer version existing and having
  // failed is real, worth-surfacing information -- just not the same
  // "something is broken" severity, since the caller's own install is
  // fine and keeps working exactly as before.
  const newerVersionFailed = Boolean(item.install_id) && item.installed_verdict !== "fail" && item.latest_verdict === "fail" && item.latest_version !== item.installed_version;

  // Real gap found and fixed (Connectors+Plugins UI redesign, 2026-09-30):
  // ConnectorDetail.tsx (Connect/Disconnect, Tools, side panel) already
  // existed, fully built and tested, but was never actually wired in here
  // -- every connector/mcp_server item rendered through the generic
  // install-state tabs below instead (Overview/Contents/Versions/
  // Verification/License), which don't apply to a connection-state item
  // at all (no install_id, no version-based gate flow the same way).
  // Same item_type condition Discover.tsx/CategorySection.tsx already use
  // to pick ConnectorCard over the plain Card.
  if (item.item_type === "connector" || item.item_type === "mcp_server") {
    return <div data-testid="detail-screen">
        <button type="button" data-testid="detail-back" onClick={onBack} className="inline-flex items-center gap-1.5 bg-none border-none cursor-pointer text-gray-500 hover:text-gray-700 mb-4 transition-colors">
          <ArrowLeftIcon width={16} height={16} aria-hidden="true" /> Back
        </button>
        {blocked && <div data-testid="detail-blocked-banner" role="alert" className="bg-red-50 text-red-700 p-4 rounded-md mb-4">
            {item.status === "yanked" ? "This item has been disabled by an administrator." : "This item failed verification and can't be added."}
          </div>}
        <ConnectorDetail item={item} />
      </div>;
  }
  const canInstall = item.allowed_actions.includes("install");
  // Real bug found live (docs/ecosystem/design/LLD/gate.md's catalog-
  // checking round): a not-yet-added catalog item has no version/gate
  // run yet at all -- currentVersionId (resolved below from getVersions(),
  // which returns an empty list for this state) stays null forever, so
  // the Add button below was permanently `disabled`. This item's whole
  // point is that it CAN be added -- materialize_from_catalog() (the
  // load-tested backend piece from feature/ecosystem-external-sources,
  // already live in the shared testing environment) creates the real
  // version/gate run server-side once install actually happens.
  const notYetAdded = isNotYetAddedCatalogItem(item);
  const canEdit = item.allowed_actions.includes("edit_content");
  // Plugins phase (docs/ecosystem/PLUGINS_PHASE_PLAN.md §4): manifest.parts
  // only exists for item_type "plugin" -- every other type's manifest keeps
  // its own existing shape (skill: instructions/files, connector/mcp_server:
  // tools/oauth/url), so this is a no-op read for them (EMPTY_PLUGIN_PARTS).
  const isPlugin = item.item_type === "plugin";
  const pluginParts = isPlugin ? item.manifest.parts ?? EMPTY_PLUGIN_PARTS : EMPTY_PLUGIN_PARTS;
  let TABS = canEdit ? [...BASE_TABS.slice(0, 2), {
    key: "edit",
    label: "Edit"
  }, ...BASE_TABS.slice(2)] : BASE_TABS;
  if (isPlugin) {
    const contentsIndex = TABS.findIndex(t => t.key === "contents");
    TABS = [...TABS.slice(0, contentsIndex + 1), {
      key: "plugin-skills",
      label: `Skills (${pluginParts.skills.length})`
    }, {
      key: "plugin-commands",
      label: `Commands (${pluginParts.commands.length})`
    }, {
      key: "plugin-agents",
      label: `Agents (${pluginParts.agents.length})`
    }, ...TABS.slice(contentsIndex + 1)];
  }

  // Real scope choice (marketplace:provision -- every scope beyond
  // private is admin-only now, product decision) is the only case that
  // still needs AddDialog's form -- for everyone else, Add installs
  // immediately with no dialog at all, matching the reference
  // screenshots' own "Add is one button" pattern. A 'warn' verdict still
  // needs an acknowledgement first either way.
  const hasScopeChoice = config.caller_permissions.can_provision || config.caller_permissions.can_share;
  const doQuickInstall = () => {
    // A not-yet-added catalog item has no currentVersionId to send --
    // that's expected for this state (see notYetAdded's own comment
    // above), not a reason to bail out. Any OTHER item genuinely needs a
    // real version id first, so still bail if one hasn't resolved yet.
    if (!currentVersionId && !notYetAdded) return;
    // Marked "installing" immediately, in the shared tracking store --
    // see Card.tsx's own handleAdd for why (survives an unmount before
    // the POST below even resolves).
    beginInstall(item.id);
    const idempotencyKey = `install-${item.id}-${Date.now()}`;
    // Real bug found live: hardcoded ["chat"] regardless of what other
    // surfaces the caller's own product profile allows -- default to
    // every surface config.surfaces lists.
    client.install(item.id, {
      version_id: currentVersionId ?? undefined,
      surfaces: config.surfaces.map(s => s.key),
      scope: "private",
      origin: "added"
    }, idempotencyKey)
    // Attaches the real job id -- useInstallStatus's own poll (a fresh
    // client.getJob() GET) is what actually clears "installing" and
    // triggers the refetch (onResolved above), even if this component
    // has since unmounted. Deliberately does NOT push job.install_id
    // into installStore.ts optimistically here -- see Card.tsx's own
    // handleAdd for why (a job can still be genuinely "verifying" with
    // an install row that exists but isn't the confirmed final truth
    // yet). The refetch this effect's own onResolved triggers (below,
    // via setRefreshKey) is what broadcasts the confirmed state, once
    // the fetch effect further up re-runs.
    .then(job => {
      attachInstallJob(item.id, job.job_id);
      toast.success(`"${item.display_name}" added.`);
    }).catch(e => {
      const message = e instanceof Error ? e.message : "Failed to add this item.";
      failInstall(item.id, message);
      toast.error(message);
    });
  };
  const handleAddClick = () => {
    if (hasScopeChoice || item.latest_verdict === "warn") {
      setShowAddDialog(true);
      return;
    }
    doQuickInstall();
  };

  // Item 2 (M5 UI-polish round): "Copy to my skills" removed entirely --
  // the header's single action slot is now Add / "Installed ▾" / Blocked,
  // matching this project's own reference mock. handleUninstall surfaces
  // a real server error (e.g. a required install, or a race where scope
  // changed to required after this page loaded) instead of failing
  // silently -- the InstalledMenu's own UI lock already covers the common
  // case, this is defense in depth for the request itself.
  const handleUninstall = () => {
    if (!item.install_id) return;
    setUninstallError(null);
    client.uninstall(item.install_id).then(() => {
      setRefreshKey(k => k + 1);
      toast.success(`"${item.display_name}" uninstalled.`);
    }).catch(e => {
      // Install-state-consistency round (2026-09-29): "an action
      // targeting an install that no longer exists must refresh and
      // show correct state, never fail silently." NOT_FOUND (already
      // uninstalled elsewhere, between this page's last fetch and this
      // click) still refreshes -- the re-fetch below naturally shows
      // "Add" again, correcting the stale "Installed" state that
      // caused this click in the first place, rather than leaving it
      // stuck showing an error over an already-wrong badge.
      const code = e?.code;
      if (code === "NOT_FOUND") {
        setRefreshKey(k => k + 1);
        return;
      }
      const message = e instanceof Error ? e.message : "Couldn't uninstall this item.";
      setUninstallError(message);
      toast.error(message);
    });
  };
  const handleToggleEnabled = next => {
    if (!item.install_id) return;
    setTogglingEnabled(true);
    setUninstallError(null);
    client.setEnabled(item.install_id, next).then(() => {
      setRefreshKey(k => k + 1);
      toast.success(`"${item.display_name}" ${next ? "enabled" : "disabled"}.`);
    }).catch(e => {
      // Same fix as handleUninstall above -- this had no .catch at all
      // before (a real silent-failure bug: setEnabled() failing left
      // the toggle showing whatever it optimistically assumed,
      // forever). NOT_FOUND still refreshes to the correct state.
      const code = e?.code;
      if (code === "NOT_FOUND") {
        setRefreshKey(k => k + 1);
        return;
      }
      const message = e instanceof Error ? e.message : "Couldn't update this item.";
      setUninstallError(message);
      toast.error(message);
    }).finally(() => setTogglingEnabled(false));
  };

  // The catalog route's Yours/Discover toggle is local UI state, not part
  // of the URL (routing.ts's own host-agnostic design) -- CatalogScreen
  // defaults to "yours" whenever the caller has ANY install of this type
  // (res.has_any), which is always true here, since the very item being
  // managed IS one. No new routing state needed for "Manage in Yours" to
  // land in the right place in practice.
  const handleManageInYours = () => router.navigate(catalogPath(typeSlug));

  // "Delete permanently"/"Retire" (item 1, M5 UI-polish review) -- same
  // confirm-then-run pattern as Yours.tsx's InstallRow; a hard delete
  // from Detail navigates Back afterward since there's no longer
  // anything here to show. (confirmAction state itself is declared above,
  // before the early returns -- see the comment there.)
  const handleDeletePermanently = () => {
    const name = item.display_name;
    client.deleteDraft(item.id).then(() => {
      removeInstallTracking(item.id);
      onBack();
      toast.success(`"${name}" deleted.`);
    }).catch(e => {
      const message = e instanceof Error ? e.message : "Couldn't delete this item.";
      setUninstallError(message);
      toast.error(message);
    });
  };
  const handleRetire = () => {
    client.deprecateItem(item.id).then(() => {
      setRefreshKey(k => k + 1);
      toast.success(`"${item.display_name}" retired.`);
    }).catch(e => {
      const message = e instanceof Error ? e.message : "Couldn't retire this item.";
      setUninstallError(message);
      toast.error(message);
    });
  };
  // User-flow QA round 8 (2026-10-03, real user question: "rollback option
  // what doing just showing version tab?"): same confirm-then-run pattern
  // as uninstall/disable/retire above -- this was a real, working server
  // call (installs_service.rollback) with zero UI-visible feedback either
  // way. setRefreshKey bumps Versions.jsx's own refreshKey prop too, which
  // is what actually makes the "current" badge move to the row just
  // rolled back to.
  const handleRollback = versionId => {
    if (!item.install_id) return;
    client.rollbackInstall(item.install_id, versionId).then(() => {
      setRefreshKey(k => k + 1);
      toast.success("Rolled back to that version.");
    }).catch(e => {
      const code = e?.code;
      if (code === "NOT_FOUND") {
        setRefreshKey(k => k + 1);
        return;
      }
      const message = e instanceof Error ? e.message : "Couldn't roll back to that version.";
      setUninstallError(message);
      toast.error(message);
    });
  };
  // User-flow QA round 8 (2026-10-03, audit finding): same real
  // update_to_version mechanism as rollback, moving forward instead of
  // back -- previously had no UI button anywhere, despite the server
  // already saying "update" was allowed whenever a newer version exists.
  const handleUpdate = versionId => {
    if (!item.install_id) return;
    client.updateInstall(item.install_id, versionId).then(() => {
      setRefreshKey(k => k + 1);
      toast.success("Updated to that version.");
    }).catch(e => {
      const code = e?.code;
      if (code === "NOT_FOUND") {
        setRefreshKey(k => k + 1);
        return;
      }
      const message = e instanceof Error ? e.message : "Couldn't update to that version.";
      setUninstallError(message);
      toast.error(message);
    });
  };
  const requestTabChange = next => {
    if (tab === "edit" && editDirty && next !== "edit") setConfirmAction({
      kind: "leave-edit",
      target: next
    });else setTab(next);
  };
  const requestBack = () => {
    if (tab === "edit" && editDirty) setConfirmAction({
      kind: "leave-edit",
      target: "back"
    });else onBack();
  };
  return <div data-testid="detail-screen">
      <button type="button" data-testid="detail-back" onClick={requestBack} className="inline-flex items-center gap-1.5 bg-none border-none cursor-pointer text-gray-500 hover:text-gray-700 mb-4 transition-colors">
        <ArrowLeftIcon width={16} height={16} aria-hidden="true" /> Back
      </button>

      {blocked && <div data-testid="detail-blocked-banner" role="alert" className="bg-red-50 text-red-700 p-4 rounded-md mb-4">
          <p className="m-0">
            {item.status === "yanked" ? "This item has been disabled by an administrator." : item.install_id ? `Your installed version (${item.installed_version ?? "current"}) failed verification. It may no longer work everywhere it's enabled.` : "This item failed verification and can't be added."}
          </p>
          {item.install_id && item.status !== "yanked" && <button type="button" onClick={() => setTab("verification")} className="bg-none border-none text-red-700 underline cursor-pointer p-0 mt-1 text-sm hover:opacity-70">
              See why, in Verification
            </button>}
        </div>}

      {/* Real confusion found live (2026-10-06, user report): "what about
          old version, even it will confuse" -- when only a NEWER version
          than the one actually installed has failed, the caller's own
          install is unaffected and keeps working exactly as before. This
          is worth knowing, but showing the same red "something is broken"
          banner above for it would be actively misleading. */}
      {newerVersionFailed && <div data-testid="detail-newer-version-failed-banner" role="status" className="bg-amber-50 text-amber-700 border border-amber-200 p-4 rounded-md mb-4">
          <p className="m-0">
            A newer version ({item.latest_version}) of this item failed verification. Your installed version ({item.installed_version}) is unaffected and keeps working as-is.
          </p>
        </div>}

      {installError && <div data-testid="detail-add-error" role="alert" className="bg-red-50 text-red-700 p-2 rounded-md mb-4 text-sm">
          {installError}
        </div>}

      {uninstallError && <div data-testid="detail-uninstall-error" role="alert" className="bg-red-50 text-red-700 p-2 rounded-md mb-4 text-sm">
          {uninstallError}
        </div>}

      {/* flexWrap here (real bug found live: the side panel got clipped
          at the right edge instead of shrinking) -- a fixed 220px column
          plus the flex:1 main column can still overflow this row's own
          container at narrower widths; wrapping drops the panel below
          the main content instead of clipping it, rather than chasing an
          exact breakpoint with no CSS file to express one in. */}
      {/* Right-section alignment pass (2026-10-05, explicit product ask:
          "skill details page right section need better design, alignment"):
          the header (icon/title/badges/action button) and the tabs used to
          live INSIDE the same flex-[1_1_480px] column as the tab content,
          with RiskSidePanel as a flex sibling of that whole column -- so
          the side panel's top edge lined up with the ICON/TITLE row, not
          with the tab content it's actually describing, and there was no
          shared row for the two columns to align against at all. Header
          now spans the full width on its own; tabs render directly under
          it, also full width; only the tab CONTENT and the side panel
          form the two-column row below that, so both columns now start at
          the same y as the tab bar, directly under the full-width header,
          matching the common dashboard pattern (full-width header -> tabs
          -> two-column body) instead of floating next to the title. */}
      <div className="flex items-start gap-4">
        <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} size={56} />
        <div className="flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="m-0 text-xl text-gray-900">{item.display_name}</h2>
            {item.is_new && <NewBadge />}
          </div>
          {/* Namespace/license/version moved to RiskSidePanel's "Item
              details" list (UI-polish round) -- no duplication
              between the header and the side panel. */}
          <div className="flex gap-1.5 mt-1.5">
            <TrustBadge tier={item.trust_tier} />
            {/* Same fix as Card.tsx -- never "Verifying" for a
                catalog item nobody has added yet (no gate run exists
                for that state at all). */}
            {notYetAdded ? <CatalogChecksPassedBadge /> : <VerdictBadge verdict={item.install_id ? (item.installed_verdict ?? item.latest_verdict) : item.latest_verdict} />}
            <CompatibilityBadge compatibility={item.compatibility} />
            <NeedsProductBadges tags={item.tags} />
          </div>
        </div>
        <div className="flex items-center gap-2">
          {item.install_id ? <InstalledMenu enabled={Boolean(item.enabled)} required={item.install_scope === "required"} managedByPlugin={Boolean(item.managed_by_plugin_install_id)} disabled={togglingEnabled} onManageInYours={handleManageInYours}
        // Enabling (turning back on) stays immediate -- it's the
        // safe/reversible direction. Disabling and uninstalling
        // now both confirm first (user-flow QA round 2).
        onToggleEnabled={next => {
          if (next) {
            handleToggleEnabled(true);
          } else {
            setConfirmAction({
              kind: "disable"
            });
          }
        }} onViewVersions={() => setTab("versions")} onUninstall={() => setConfirmAction({
          kind: "uninstall"
        })} canDeleteDraft={item.allowed_actions.includes("delete_draft")} hasOtherInstalls={item.has_other_installs} canDeprecate={item.allowed_actions.includes("deprecate")} onDeletePermanently={() => setConfirmAction({
          kind: "delete"
        })} onRetire={() => setConfirmAction({
          kind: "retire"
        })} />
        // Premium-polish pass (2026-10-05, explicit product ask: "Add
        // button... Installed button on detailed page is too big"):
        // this header slot swaps between InstalledMenu (resized to the
        // app's real px-3 py-1.5 text-sm control in the theme-alignment
        // round) and this Button, which still defaulted to Button.jsx's
        // own px-4 py-2 -- visibly bigger than its own sibling state in
        // the exact same slot. className override matches Versions.jsx's
        // own established pattern for sizing one Button call site down
        // from the shared default.
        : canInstall ? <Button data-testid="detail-add-button" className="px-3 py-1.5 text-sm" disabled={!currentVersionId && !notYetAdded} loading={installing} onClick={handleAddClick}>
              {installing ? "Adding…" : "Add"}
            </Button> : null}
        </div>
      </div>

      {/* Premium-polish pass (2026-10-05, explicit product ask: "detail
          page has so much tabs... need better design"): a plugin item
          can carry up to 8 tabs (Overview/Contents/Skills(N)/
          Commands(N)/Agents(N)/Versions/Verification/License) in this
          same bar -- overflow-x-auto lets it scroll horizontally
          instead of wrapping/clipping once they no longer fit, and the
          active tab now gets a filled pill instead of relying on the
          underline alone, which reads better at that tab count. */}
      {/* overflow-x-auto paired explicitly with overflow-y-hidden --
          CSS's own overflow-computation rule otherwise auto-promotes a
          `visible` y-axis to `auto` the moment x is `auto` (CSS
          Overflow §3), which showed up live as a spurious 1px vertical
          scrollbar on this row even though nothing here actually
          overflows vertically. */}
      <div role="tablist" className="flex gap-1 border-b border-gray-200 my-4 overflow-x-auto overflow-y-hidden">
        {TABS.map(t => <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} data-testid={`detail-tab-trigger-${t.key}`} onClick={() => requestTabChange(t.key)} className={["bg-none border-none cursor-pointer px-3 py-1.5 -mb-px rounded-t-md text-sm font-medium transition-colors whitespace-nowrap", tab === t.key ? "bg-indigo-50 text-indigo-700" : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"].join(" ")}>
            {t.label}
          </button>)}
      </div>

      <div className="flex flex-wrap gap-6">
        <div className="flex-[1_1_480px] min-w-0">

          {tab === "overview" && <Overview item={item} />}
          {tab === "contents" && (isPlugin ? <PluginContentsSummary item={item} /> : <Contents item={item} />)}
          {tab === "plugin-skills" && <PluginPartsList parts={pluginParts.skills} routeSlug="skills" emptyLabel="No skills bundled." />}
          {tab === "plugin-commands" && <PluginPartsList parts={pluginParts.commands} emptyLabel="No commands bundled." />}
          {tab === "plugin-agents" && <PluginPartsList parts={pluginParts.agents} emptyLabel="No agents bundled." />}
          {tab === "edit" && canEdit && <EditContent item={item} onSaved={() => setRefreshKey(k => k + 1)} onDirtyChange={setEditDirty} />}
          {tab === "versions" && <Versions itemId={item.id} installId={item.install_id} canRollback={item.allowed_actions.includes("rollback")} canUpdate={item.allowed_actions.includes("update")} refreshKey={refreshKey} onRollback={versionId => setConfirmAction({
            kind: "rollback",
            versionId
          })} onUpdate={versionId => setConfirmAction({
            kind: "update",
            versionId
          })} />}
          {tab === "verification" && <Verification itemId={item.id} hasScripts={Object.keys(item.manifest.files ?? {}).length > 0} />}
          {tab === "license" && <License item={item} />}
        </div>

        <div className="flex-[0_1_240px] min-w-[200px]">
          {isPlugin && <div className="mb-4">
              <h4 className="text-sm text-gray-900">Connectors &amp; tools</h4>
              <PluginRiskSummary parts={pluginParts} />
            </div>}
          <RiskSidePanel item={item} />
        </div>
      </div>

      {/* Same fix as doQuickInstall above -- this used to also require
          currentVersionId, so for a not-yet-added catalog item, clicking
          Add with a real scope choice to make (admin/provisioner) set
          showAddDialog but the dialog itself silently never rendered. */}
      {showAddDialog && (currentVersionId || notYetAdded) && <AddDialog item={item} versionId={currentVersionId ?? undefined} defaultSurfaces={config.surfaces.map(s => s.key)} onClose={() => setShowAddDialog(false)} onInstalled={() => setRefreshKey(k => k + 1)} />}

      <ConfirmDialog open={confirmAction !== null} title={confirmAction?.kind === "delete" ? "Delete this skill permanently?" : confirmAction?.kind === "retire" ? "Retire this skill?" : confirmAction?.kind === "uninstall" ? "Uninstall this skill?" : confirmAction?.kind === "disable" ? "Disable this skill?" : confirmAction?.kind === "rollback" ? "Roll back to this version?" : confirmAction?.kind === "update" ? "Update to this version?" : "Leave without saving?"} message={confirmAction?.kind === "delete" ? `"${item.display_name}" and all of its versions and stored files will be permanently deleted. This can't be undone.` : confirmAction?.kind === "retire" ? `"${item.display_name}" will stop appearing as an active skill. Existing installs keep working until each is uninstalled.` : confirmAction?.kind === "uninstall" ? `"${item.display_name}" will be removed from your installed skills. You can add it again later from Discover.` : confirmAction?.kind === "disable" ? `"${item.display_name}" will stop working everywhere it's enabled (chat, Agent Studio, etc.) until you re-enable it.` : confirmAction?.kind === "rollback" ? `Your install of "${item.display_name}" will immediately start using this older version instead. You can roll forward again anytime from this same tab.` : confirmAction?.kind === "update" ? `Your install of "${item.display_name}" will immediately start using this newer version instead.` : "Your edits haven't been saved. Leaving now will discard them."} confirmLabel={confirmAction?.kind === "delete" ? "Delete permanently" : confirmAction?.kind === "retire" ? "Retire" : confirmAction?.kind === "uninstall" ? "Uninstall" : confirmAction?.kind === "disable" ? "Disable" : confirmAction?.kind === "rollback" ? "Roll back" : confirmAction?.kind === "update" ? "Update" : "Leave"} danger={confirmAction?.kind === "delete" || confirmAction?.kind === "uninstall" || confirmAction?.kind === "disable" || confirmAction?.kind === "leave-edit"} onConfirm={() => {
      if (confirmAction?.kind === "delete") handleDeletePermanently();else if (confirmAction?.kind === "retire") handleRetire();else if (confirmAction?.kind === "uninstall") handleUninstall();else if (confirmAction?.kind === "disable") handleToggleEnabled(false);else if (confirmAction?.kind === "rollback") handleRollback(confirmAction.versionId);else if (confirmAction?.kind === "update") handleUpdate(confirmAction.versionId);else if (confirmAction?.kind === "leave-edit") {
        setEditDirty(false);
        if (confirmAction.target === "back") onBack();else setTab(confirmAction.target);
      }
      setConfirmAction(null);
    }} onCancel={() => setConfirmAction(null)} />
    </div>;
}