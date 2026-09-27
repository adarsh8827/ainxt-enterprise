// SPDX-License-Identifier: MIT
// Task F-7: Detail page -- Back, blocked banner, header badges, meta
// line with no install-count, tabs, AddDialog, RiskSidePanel. Copy Link
// was removed (not required) -- Back + the browser's own address bar
// cover that need.
import { useEffect, useState } from "react";
import { ArrowLeftIcon } from "@heroicons/react/24/outline";
import type { CreateWritePayload, ItemDetail } from "../types";
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
import { KebabMenu, buildKebabActions } from "./KebabMenu";
import { ToggleSwitch } from "./ToggleSwitch";
import { useConfig } from "../hooks/useEcosystemConfig";
import { detailPath } from "../routing";

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
  const [copying, setCopying] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [togglingEnabled, setTogglingEnabled] = useState(false);

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
  // Read-only items (built-in, or owned by someone else) offer a private
  // fork instead of an edit affordance -- item A3's own "Copy to my
  // skills" rule. Never offered on a blocked item: forking a failed/
  // disabled item's content isn't a repair action, it's just confusing.
  const canCopy = !canEdit && !blocked;
  const TABS: Array<{ key: Tab; label: string }> = canEdit
    ? [...BASE_TABS.slice(0, 2), { key: "edit", label: "Edit" }, ...BASE_TABS.slice(2)]
    : BASE_TABS;

  // Real scope choice (marketplace:share/marketplace:provision) is the
  // only case that still needs AddDialog's form -- for everyone else,
  // Add installs immediately with no dialog at all, matching the
  // reference screenshots' own "Add is one button" pattern. A 'warn'
  // verdict still needs an acknowledgement first either way.
  const hasScopeChoice = config.caller_permissions.can_share || config.caller_permissions.can_provision;

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

  // One-click, same name, no form (the user's own explicit ask) -- the
  // only reason this couldn't already work like "Add" is that copying
  // creates a brand-new item under a namespace, and every other create
  // path in this package still requires a human-typed one. caller_
  // default_namespace_prefix (CONTRACTS.md's new field) closes that gap.
  const handleCopyClick = () => {
    setCopying(true);
    setCopyError(null);
    const nameSegment = item.namespace.split("/")[1] ?? item.namespace;
    const namespace = `${config.caller_default_namespace_prefix}/${nameSegment}`;
    const manifest = item.manifest as { instructions?: string; files?: Record<string, string> };
    const payload: CreateWritePayload = {
      create_via: "write", item_type: item.item_type, namespace,
      display_name: item.display_name, description: item.description, category: item.category,
      license: item.license,
      content: {
        instructions: manifest.instructions ?? "",
        files: Object.entries(manifest.files ?? {}).map(([name, content]) => ({ name, content })),
      },
      surfaces: ["chat"],
    };
    client.createItem(payload, `copy-${item.id}-${Date.now()}`)
      .then((result) => router.navigate(detailPath(typeSlug, result.item_id)))
      .catch((e: unknown) => {
        const code = (e as { code?: string })?.code;
        setCopyError(code === "CONFLICT" ? "You already have a copy of this." : e instanceof Error ? e.message : "Couldn't copy this item.");
      })
      .finally(() => setCopying(false));
  };

  const kebabActions = item.install_id
    ? buildKebabActions(item.allowed_actions, {
        enable: () => { setTogglingEnabled(true); client.setEnabled(item.install_id!, true).then(() => setRefreshKey((k) => k + 1)).finally(() => setTogglingEnabled(false)); },
        disable: () => { setTogglingEnabled(true); client.setEnabled(item.install_id!, false).then(() => setRefreshKey((k) => k + 1)).finally(() => setTogglingEnabled(false)); },
        uninstall: () => client.uninstall(item.install_id!).then(() => setRefreshKey((k) => k + 1)),
        report: () => client.reportItem(item.id, "reported from Detail"),
        deprecate: () => client.deprecateItem(item.id).then(() => setRefreshKey((k) => k + 1)),
        delete_draft: () => client.deleteDraft(item.id).then(onBack),
      })
    : [];

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

      {copyError && (
        <div data-testid="detail-copy-error" role="alert" style={{ background: "var(--eco-color-dangerBg)", color: "var(--eco-color-danger)", padding: "var(--eco-space-sm)", borderRadius: "var(--eco-radius-md)", marginBottom: "var(--eco-space-md)", fontSize: "var(--eco-font-sizeSm)" }}>
          {copyError}
        </div>
      )}

      <div style={{ display: "flex", gap: "var(--eco-space-lg)" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
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
              {canCopy && (
                <button
                  type="button"
                  data-testid="detail-copy-to-my-skills"
                  disabled={copying}
                  onClick={handleCopyClick}
                  style={{ padding: "8px 12px", borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", cursor: "pointer" }}
                >
                  {copying ? "Copying…" : "Copy to my skills"}
                </button>
              )}
              {canInstall && (
                <button
                  type="button"
                  data-testid="detail-add-button"
                  disabled={!currentVersionId || installing}
                  onClick={handleAddClick}
                  style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}
                >
                  {installing ? "Adding…" : "Add"}
                </button>
              )}
              {item.install_id && (
                <>
                  <ToggleSwitch
                    checked={Boolean(item.enabled)}
                    disabled={togglingEnabled}
                    label={item.enabled ? "Disable" : "Enable"}
                    onChange={(next) => {
                      setTogglingEnabled(true);
                      client.setEnabled(item.install_id!, next).then(() => setRefreshKey((k) => k + 1)).finally(() => setTogglingEnabled(false));
                    }}
                  />
                  <KebabMenu actions={kebabActions} />
                </>
              )}
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
          {tab === "verification" && <Verification itemId={item.id} />}
          {tab === "license" && <License item={item} />}
        </div>

        <div style={{ width: "220px", flexShrink: 0 }}>
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
