// SPDX-License-Identifier: MIT
// Task F-7: Detail page -- Back, blocked banner, header badges, meta
// line with no install-count, tabs, AddDialog, RiskSidePanel. Copy Link
// was removed (not required) -- Back + the browser's own address bar
// cover that need.
import { useEffect, useState } from "react";
import { ArrowLeftIcon } from "@heroicons/react/24/outline";
import type { ItemDetail } from "../types";
import { isNotYetAddedCatalogItem } from "../catalogState";
import { attachInstallJob, beginInstall, failInstall, useInstallStatus } from "../installTracking";
import { applyInstallOverride, removeInstallTracking, setInstallState, useInstallOverrideVersion } from "../installStore";
import { useEcosystemClient, useHost } from "../context/HostContext";
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
import { useConfig } from "../hooks/useEcosystemConfig";
import { catalogPath } from "../routing";
import { PluginContentsSummary } from "./Plugins/PluginContentsSummary";
import { PluginRiskSummary } from "./Plugins/PluginRiskSummary";
import { PluginPartsList } from "./Plugins/PluginPartsList";
import type { PluginParts } from "../types";

type Tab = "overview" | "contents" | "plugin-skills" | "plugin-commands" | "plugin-agents" | "versions" | "verification" | "license" | "edit";
const BASE_TABS: Array<{ key: Tab; label: string }> = [
  { key: "overview", label: "Overview" }, { key: "contents", label: "Contents" },
  { key: "versions", label: "Versions" }, { key: "verification", label: "Verification" },
  { key: "license", label: "License" },
];
const EMPTY_PLUGIN_PARTS: PluginParts = { skills: [], commands: [], agents: [], connectors: [], mcp_servers: [], hooks: [] };

export function Detail({ idOrNamespace, typeSlug, onBack, onTryInChat }: { idOrNamespace: string; typeSlug: string; onBack: () => void; onTryInChat?: () => void }) {
  const client = useEcosystemClient();
  const { router } = useHost();
  const config = useConfig();
  const [rawItem, setItem] = useState<ItemDetail | null>(null);
  const [currentVersionId, setCurrentVersionId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [togglingEnabled, setTogglingEnabled] = useState(false);
  const [uninstallError, setUninstallError] = useState<string | null>(null);
  // "Delete permanently"/"Retire" (item 1, M5 UI-polish review) -- must
  // be declared here, before the early returns below, not further down
  // where handleDeletePermanently/handleRetire are defined: a real bug
  // found live ("Rendered more hooks than during the previous render")
  // from declaring it after those returns, since the hook then only ran
  // on renders that got past both of them.
  const [confirmAction, setConfirmAction] = useState<{ kind: "delete" | "retire" } | null>(null);
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
  const { phase: installPhase, error: installError } = useInstallStatus(rawItem?.id ?? "", client, () => setRefreshKey((k) => k + 1));
  const installing = installPhase === "installing";
  // Install-state-consistency round (2026-09-29): subscribes to the
  // shared installStore -- see Card.tsx's own useInstallOverrideVersion()
  // call for the full rationale (a change made elsewhere, same tab or
  // another, corrects this page immediately).
  useInstallOverrideVersion();

  useEffect(() => {
    let cancelled = false;
    setError(null);
    client.getItem(idOrNamespace)
      .then((i) => {
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
          install_id: i.install_id, enabled: i.enabled,
          install_scope: i.install_scope, install_surfaces: i.install_surfaces,
          allowed_actions: i.allowed_actions,
        });
      })
      .catch((e) => { if (!cancelled) setError(e); });
    return () => { cancelled = true; };
  }, [client, idOrNamespace, refreshKey]);

  // Install-state-consistency round (2026-09-29): the cross-tab half --
  // same-tab changes are already covered by installStore's own
  // subscription (useInstallOverrideVersion above); a change made in a
  // DIFFERENT tab needs the real ecosystem.changed SSE stream to know to
  // re-fetch at all.
  useEffect(() => {
    return client.streamChanges?.(() => setRefreshKey((k) => k + 1));
  }, [client]);

  // ItemDetail's own `latest_version` (CONTRACTS.md §9) is a version
  // STRING ("1.0.0"), not the UUID `install()` actually needs -- resolve
  // the current version's real id from the versions list rather than
  // fabricating one.
  useEffect(() => {
    if (!rawItem) return;
    let cancelled = false;
    client.getVersions(rawItem.id).then((versions) => {
      if (cancelled) return;
      setCurrentVersionId(versions.find((v) => v.is_current)?.id ?? null);
    });
    return () => { cancelled = true; };
  }, [client, rawItem?.id]);

  if (error) return <div data-testid="detail-error" role="alert">This item isn't available.</div>;
  if (rawItem === null) return <div data-testid="detail-loading">Loading…</div>;
  // Install-state-consistency round (2026-09-29): merges the freshest
  // known override (a mutation made elsewhere, same tab or another) onto
  // this page's own fetched item -- see Card.tsx's own applyInstallOverride
  // call for the full rationale.
  const item = applyInstallOverride(rawItem);

  const blocked = item.status === "yanked" || item.latest_verdict === "fail";
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
  const pluginParts = isPlugin ? ((item.manifest as { parts?: PluginParts }).parts ?? EMPTY_PLUGIN_PARTS) : EMPTY_PLUGIN_PARTS;
  let TABS: Array<{ key: Tab; label: string }> = canEdit
    ? [...BASE_TABS.slice(0, 2), { key: "edit", label: "Edit" }, ...BASE_TABS.slice(2)]
    : BASE_TABS;
  if (isPlugin) {
    const contentsIndex = TABS.findIndex((t) => t.key === "contents");
    TABS = [
      ...TABS.slice(0, contentsIndex + 1),
      { key: "plugin-skills", label: `Skills (${pluginParts.skills.length})` },
      { key: "plugin-commands", label: `Commands (${pluginParts.commands.length})` },
      { key: "plugin-agents", label: `Agents (${pluginParts.agents.length})` },
      ...TABS.slice(contentsIndex + 1),
    ];
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
    client.install(item.id, { version_id: currentVersionId ?? undefined, surfaces: config.surfaces.map((s) => s.key), scope: "private", origin: "added" }, idempotencyKey)
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
      .then((job) => attachInstallJob(item.id, job.job_id))
      .catch((e) => failInstall(item.id, e instanceof Error ? e.message : "Failed to add this item."));
  };

  const handleAddClick = () => {
    if (hasScopeChoice || item.latest_verdict === "warn") { setShowAddDialog(true); return; }
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
    client.uninstall(item.install_id)
      .then(() => setRefreshKey((k) => k + 1))
      .catch((e: unknown) => {
        // Install-state-consistency round (2026-09-29): "an action
        // targeting an install that no longer exists must refresh and
        // show correct state, never fail silently." NOT_FOUND (already
        // uninstalled elsewhere, between this page's last fetch and this
        // click) still refreshes -- the re-fetch below naturally shows
        // "Add" again, correcting the stale "Installed" state that
        // caused this click in the first place, rather than leaving it
        // stuck showing an error over an already-wrong badge.
        const code = (e as { code?: string } | undefined)?.code;
        if (code === "NOT_FOUND") { setRefreshKey((k) => k + 1); return; }
        setUninstallError(e instanceof Error ? e.message : "Couldn't uninstall this item.");
      });
  };

  const handleToggleEnabled = (next: boolean) => {
    if (!item.install_id) return;
    setTogglingEnabled(true);
    setUninstallError(null);
    client.setEnabled(item.install_id, next)
      .then(() => setRefreshKey((k) => k + 1))
      .catch((e: unknown) => {
        // Same fix as handleUninstall above -- this had no .catch at all
        // before (a real silent-failure bug: setEnabled() failing left
        // the toggle showing whatever it optimistically assumed,
        // forever). NOT_FOUND still refreshes to the correct state.
        const code = (e as { code?: string } | undefined)?.code;
        if (code === "NOT_FOUND") { setRefreshKey((k) => k + 1); return; }
        setUninstallError(e instanceof Error ? e.message : "Couldn't update this item.");
      })
      .finally(() => setTogglingEnabled(false));
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
    client.deleteDraft(item.id)
      .then(() => { removeInstallTracking(item.id); onBack(); })
      .catch((e: unknown) => setUninstallError(e instanceof Error ? e.message : "Couldn't delete this item."));
  };
  const handleRetire = () => {
    client.deprecateItem(item.id)
      .then(() => setRefreshKey((k) => k + 1))
      .catch((e: unknown) => setUninstallError(e instanceof Error ? e.message : "Couldn't retire this item."));
  };

  return (
    <div data-testid="detail-screen">
      <button type="button" data-testid="detail-back" onClick={onBack} style={{ display: "inline-flex", alignItems: "center", gap: "6px", background: "none", border: "none", cursor: "pointer", color: "var(--eco-color-textSecondary)", marginBottom: "var(--eco-space-md)" }}>
        <ArrowLeftIcon width={16} height={16} aria-hidden="true" /> Back
      </button>

      {blocked && (
        <div data-testid="detail-blocked-banner" role="alert" style={{ background: "var(--eco-color-dangerBg)", color: "var(--eco-color-danger)", padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-md)", marginBottom: "var(--eco-space-md)" }}>
          {item.status === "yanked" ? "This item has been disabled by an administrator." : "This item failed verification and can't be added."}
        </div>
      )}

      {installError && (
        <div data-testid="detail-add-error" role="alert" style={{ background: "var(--eco-color-dangerBg)", color: "var(--eco-color-danger)", padding: "var(--eco-space-sm)", borderRadius: "var(--eco-radius-md)", marginBottom: "var(--eco-space-md)", fontSize: "var(--eco-font-sizeSm)" }}>
          {installError}
        </div>
      )}

      {uninstallError && (
        <div data-testid="detail-uninstall-error" role="alert" style={{ background: "var(--eco-color-dangerBg)", color: "var(--eco-color-danger)", padding: "var(--eco-space-sm)", borderRadius: "var(--eco-radius-md)", marginBottom: "var(--eco-space-md)", fontSize: "var(--eco-font-sizeSm)" }}>
          {uninstallError}
        </div>
      )}

      {/* flexWrap here (real bug found live: the side panel got clipped
          at the right edge instead of shrinking) -- a fixed 220px column
          plus the flex:1 main column can still overflow this row's own
          container at narrower widths; wrapping drops the panel below
          the main content instead of clipping it, rather than chasing an
          exact breakpoint with no CSS file to express one in. */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--eco-space-lg)" }}>
        <div style={{ flex: "1 1 480px", minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: "var(--eco-space-md)" }}>
            <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} size={56} />
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                <h2 style={{ margin: 0, fontSize: "var(--eco-font-sizeXl)", color: "var(--eco-color-textPrimary)" }}>{item.display_name}</h2>
                {item.is_new && <NewBadge />}
              </div>
              {/* Namespace/license/version moved to RiskSidePanel's "Item
                  details" list (UI-polish round) -- no duplication
                  between the header and the side panel. */}
              <div style={{ display: "flex", gap: "6px", marginTop: "6px" }}>
                <TrustBadge tier={item.trust_tier} />
                {/* Same fix as Card.tsx -- never "Verifying" for a
                    catalog item nobody has added yet (no gate run exists
                    for that state at all). */}
                {notYetAdded ? <CatalogChecksPassedBadge /> : <VerdictBadge verdict={item.latest_verdict} />}
                <CompatibilityBadge compatibility={item.compatibility} />
                <NeedsProductBadges tags={item.tags} />
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-sm)" }}>
              {item.install_id ? (
                <InstalledMenu
                  enabled={Boolean(item.enabled)}
                  required={item.install_scope === "required"}
                  managedByPlugin={Boolean(item.managed_by_plugin_install_id)}
                  disabled={togglingEnabled}
                  onManageInYours={handleManageInYours}
                  onToggleEnabled={handleToggleEnabled}
                  onViewVersions={() => setTab("versions")}
                  onUninstall={handleUninstall}
                  canDeleteDraft={item.allowed_actions.includes("delete_draft")}
                  hasOtherInstalls={item.has_other_installs}
                  canDeprecate={item.allowed_actions.includes("deprecate")}
                  onDeletePermanently={() => setConfirmAction({ kind: "delete" })}
                  onRetire={() => setConfirmAction({ kind: "retire" })}
                />
              ) : canInstall ? (
                <button
                  type="button"
                  data-testid="detail-add-button"
                  disabled={(!currentVersionId && !notYetAdded) || installing}
                  onClick={handleAddClick}
                  style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}
                >
                  {installing ? "Adding…" : "Add"}
                </button>
              ) : null}
            </div>
          </div>

          <div role="tablist" style={{ display: "flex", gap: "var(--eco-space-md)", borderBottom: "1px solid var(--eco-color-border)", margin: "var(--eco-space-md) 0" }}>
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                data-testid={`detail-tab-trigger-${t.key}`}
                onClick={() => setTab(t.key)}
                style={{
                  background: "none", border: "none", cursor: "pointer", padding: "8px 0",
                  color: tab === t.key ? "var(--eco-color-accentSkill)" : "var(--eco-color-textSecondary)",
                  borderBottom: tab === t.key ? "2px solid var(--eco-color-accentSkill)" : "2px solid transparent",
                  fontWeight: tab === t.key ? 600 : 400,
                }}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === "overview" && <Overview item={item} onTryInChat={onTryInChat} />}
          {tab === "contents" && (isPlugin ? <PluginContentsSummary item={item} /> : <Contents item={item} />)}
          {tab === "plugin-skills" && <PluginPartsList parts={pluginParts.skills} routeSlug="skills" emptyLabel="No skills bundled." />}
          {tab === "plugin-commands" && <PluginPartsList parts={pluginParts.commands} emptyLabel="No commands bundled." />}
          {tab === "plugin-agents" && <PluginPartsList parts={pluginParts.agents} emptyLabel="No agents bundled." />}
          {tab === "edit" && canEdit && <EditContent item={item} onSaved={() => setRefreshKey((k) => k + 1)} />}
          {tab === "versions" && <Versions itemId={item.id} installId={item.install_id} canRollback={item.allowed_actions.includes("rollback")} />}
          {tab === "verification" && <Verification itemId={item.id} hasScripts={Object.keys((item.manifest as { files?: Record<string, string> }).files ?? {}).length > 0} />}
          {tab === "license" && <License item={item} />}
        </div>

        <div style={{ flex: "0 1 240px", minWidth: "200px" }}>
          {isPlugin && (
            <div style={{ marginBottom: "var(--eco-space-md)" }}>
              <h4 style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)" }}>Connectors &amp; tools</h4>
              <PluginRiskSummary parts={pluginParts} />
            </div>
          )}
          <RiskSidePanel item={item} />
        </div>
      </div>

      {/* Same fix as doQuickInstall above -- this used to also require
          currentVersionId, so for a not-yet-added catalog item, clicking
          Add with a real scope choice to make (admin/provisioner) set
          showAddDialog but the dialog itself silently never rendered. */}
      {showAddDialog && (currentVersionId || notYetAdded) && (
        <AddDialog
          item={item}
          versionId={currentVersionId ?? undefined}
          defaultSurfaces={config.surfaces.map((s) => s.key)}
          onClose={() => setShowAddDialog(false)}
          onInstalled={() => setRefreshKey((k) => k + 1)}
        />
      )}

      <ConfirmDialog
        open={confirmAction !== null}
        title={confirmAction?.kind === "delete" ? "Delete this skill permanently?" : "Retire this skill?"}
        message={
          confirmAction?.kind === "delete"
            ? `"${item.display_name}" and all of its versions and stored files will be permanently deleted. This can't be undone.`
            : `"${item.display_name}" will stop appearing as an active skill. Existing installs keep working until each is uninstalled.`
        }
        confirmLabel={confirmAction?.kind === "delete" ? "Delete permanently" : "Retire"}
        danger={confirmAction?.kind === "delete"}
        onConfirm={() => {
          if (confirmAction?.kind === "delete") handleDeletePermanently();
          else if (confirmAction?.kind === "retire") handleRetire();
          setConfirmAction(null);
        }}
        onCancel={() => setConfirmAction(null)}
      />
    </div>
  );
}
