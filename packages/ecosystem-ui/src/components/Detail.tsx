// SPDX-License-Identifier: MIT
// Task F-7: Detail page -- Back, blocked banner, header badges, meta
// line with no install-count, tabs, AddDialog, RiskSidePanel. Copy Link
// was removed (not required) -- Back + the browser's own address bar
// cover that need.
import { useEffect, useState } from "react";
import { ArrowLeftIcon } from "@heroicons/react/24/outline";
import type { ItemDetail } from "../types";
import { useEcosystemClient, useHost } from "../context/HostContext";
import { ItemIcon } from "./ItemIcon";
import { TrustBadge, VerdictBadge, NewBadge } from "./Badges";
import { Overview } from "./detail/Overview";
import { Contents } from "./detail/Contents";
import { Versions } from "./detail/Versions";
import { Verification } from "./detail/Verification";
import { License } from "./detail/License";
import { AddDialog } from "./detail/AddDialog";
import { RiskSidePanel } from "./detail/RiskSidePanel";
import { EditContent } from "./detail/EditContent";
import { InstalledMenu } from "./detail/InstalledMenu";
import { useConfig } from "../hooks/useEcosystemConfig";
import { catalogPath } from "../routing";

type Tab = "overview" | "contents" | "versions" | "verification" | "license" | "edit";
const BASE_TABS: Array<{ key: Tab; label: string }> = [
  { key: "overview", label: "Overview" }, { key: "contents", label: "Contents" },
  { key: "versions", label: "Versions" }, { key: "verification", label: "Verification" },
  { key: "license", label: "License" },
];

export function Detail({ idOrNamespace, typeSlug, onBack }: { idOrNamespace: string; typeSlug: string; onBack: () => void }) {
  const client = useEcosystemClient();
  const { router } = useHost();
  const config = useConfig();
  const [item, setItem] = useState<ItemDetail | null>(null);
  const [currentVersionId, setCurrentVersionId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [installing, setInstalling] = useState(false);
  const [installError, setInstallError] = useState<string | null>(null);
  const [togglingEnabled, setTogglingEnabled] = useState(false);
  const [uninstallError, setUninstallError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    client.getItem(idOrNamespace)
      .then((i) => { if (!cancelled) setItem(i); })
      .catch((e) => { if (!cancelled) setError(e); });
    return () => { cancelled = true; };
  }, [client, idOrNamespace, refreshKey]);

  // ItemDetail's own `latest_version` (CONTRACTS.md §9) is a version
  // STRING ("1.0.0"), not the UUID `install()` actually needs -- resolve
  // the current version's real id from the versions list rather than
  // fabricating one.
  useEffect(() => {
    if (!item) return;
    let cancelled = false;
    client.getVersions(item.id).then((versions) => {
      if (cancelled) return;
      setCurrentVersionId(versions.find((v) => v.is_current)?.id ?? null);
    });
    return () => { cancelled = true; };
  }, [client, item?.id]);

  if (error) return <div data-testid="detail-error" role="alert">This item isn't available.</div>;
  if (item === null) return <div data-testid="detail-loading">Loading…</div>;

  const blocked = item.status === "yanked" || item.latest_verdict === "fail";
  const canInstall = item.allowed_actions.includes("install");
  const canEdit = item.allowed_actions.includes("edit_content");
  const TABS: Array<{ key: Tab; label: string }> = canEdit
    ? [...BASE_TABS.slice(0, 2), { key: "edit", label: "Edit" }, ...BASE_TABS.slice(2)]
    : BASE_TABS;

  // Real scope choice (marketplace:provision -- every scope beyond
  // private is admin-only now, product decision) is the only case that
  // still needs AddDialog's form -- for everyone else, Add installs
  // immediately with no dialog at all, matching the reference
  // screenshots' own "Add is one button" pattern. A 'warn' verdict still
  // needs an acknowledgement first either way.
  const hasScopeChoice = config.caller_permissions.can_provision || config.caller_permissions.can_share;

  const doQuickInstall = () => {
    if (!currentVersionId) return;
    setInstalling(true);
    setInstallError(null);
    const idempotencyKey = `install-${item.id}-${Date.now()}`;
    client.install(item.id, { version_id: currentVersionId, surfaces: ["chat"], scope: "private", origin: "added" }, idempotencyKey)
      .then(() => setRefreshKey((k) => k + 1))
      .catch((e) => setInstallError(e instanceof Error ? e.message : "Failed to add this item."))
      .finally(() => setInstalling(false));
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
      .catch((e: unknown) => setUninstallError(e instanceof Error ? e.message : "Couldn't uninstall this item."));
  };

  const handleToggleEnabled = (next: boolean) => {
    if (!item.install_id) return;
    setTogglingEnabled(true);
    client.setEnabled(item.install_id, next).then(() => setRefreshKey((k) => k + 1)).finally(() => setTogglingEnabled(false));
  };

  // The catalog route's Yours/Discover toggle is local UI state, not part
  // of the URL (routing.ts's own host-agnostic design) -- CatalogScreen
  // defaults to "yours" whenever the caller has ANY install of this type
  // (res.has_any), which is always true here, since the very item being
  // managed IS one. No new routing state needed for "Manage in Yours" to
  // land in the right place in practice.
  const handleManageInYours = () => router.navigate(catalogPath(typeSlug));

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
                <h2 style={{ margin: 0, color: "var(--eco-color-textPrimary)" }}>{item.display_name}</h2>
                {item.is_new && <NewBadge />}
              </div>
              <div style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textMuted)" }}>
                {item.namespace} {"·"} {item.license} {"·"} v{item.latest_version ?? "—"}
              </div>
              <div style={{ display: "flex", gap: "6px", marginTop: "6px" }}>
                <TrustBadge tier={item.trust_tier} />
                <VerdictBadge verdict={item.latest_verdict} />
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-sm)" }}>
              {item.install_id ? (
                <InstalledMenu
                  enabled={Boolean(item.enabled)}
                  required={item.install_scope === "required"}
                  disabled={togglingEnabled}
                  onManageInYours={handleManageInYours}
                  onToggleEnabled={handleToggleEnabled}
                  onViewVersions={() => setTab("versions")}
                  onUninstall={handleUninstall}
                />
              ) : canInstall ? (
                <button
                  type="button"
                  data-testid="detail-add-button"
                  disabled={!currentVersionId || installing}
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

          {tab === "overview" && <Overview item={item} />}
          {tab === "contents" && <Contents item={item} />}
          {tab === "edit" && canEdit && <EditContent item={item} onSaved={() => setRefreshKey((k) => k + 1)} />}
          {tab === "versions" && <Versions itemId={item.id} installId={item.install_id} canRollback={item.allowed_actions.includes("rollback")} />}
          {tab === "verification" && <Verification itemId={item.id} hasScripts={Object.keys((item.manifest as { files?: Record<string, string> }).files ?? {}).length > 0} />}
          {tab === "license" && <License item={item} />}
        </div>

        <div style={{ flex: "0 1 240px", minWidth: "200px" }}>
          <RiskSidePanel itemType={item.item_type} />
        </div>
      </div>

      {showAddDialog && currentVersionId && (
        <AddDialog
          item={item}
          versionId={currentVersionId}
          defaultSurfaces={["chat"]}
          onClose={() => setShowAddDialog(false)}
          onInstalled={() => setRefreshKey((k) => k + 1)}
        />
      )}

    </div>
  );
}
