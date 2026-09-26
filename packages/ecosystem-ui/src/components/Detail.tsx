// SPDX-License-Identifier: MIT
// Task F-7: Detail page -- Back, Copy Link, blocked banner, header badges,
// meta line with no install-count, tabs, AddDialog, RiskSidePanel.
import { useEffect, useState } from "react";
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

type Tab = "overview" | "contents" | "versions" | "verification" | "license";
const TABS: Array<{ key: Tab; label: string }> = [
  { key: "overview", label: "Overview" }, { key: "contents", label: "Contents" },
  { key: "versions", label: "Versions" }, { key: "verification", label: "Verification" },
  { key: "license", label: "License" },
];

export function Detail({ idOrNamespace, typeSlug, onBack }: { idOrNamespace: string; typeSlug: string; onBack: () => void }) {
  const client = useEcosystemClient();
  const basePath = useHost().router.basePath ?? "";
  const [item, setItem] = useState<ItemDetail | null>(null);
  const [currentVersionId, setCurrentVersionId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [copyFeedback, setCopyFeedback] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

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

  const handleCopyLink = () => {
    const origin = typeof window !== "undefined" ? window.location.origin : "";
    const url = `${origin}${basePath}/${typeSlug}/${item.namespace}`;
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(url).then(() => {
        setCopyFeedback(true);
        setTimeout(() => setCopyFeedback(false), 1500);
      });
    }
  };

  return (
    <div data-testid="detail-screen">
      <button type="button" data-testid="detail-back" onClick={onBack} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--eco-color-textSecondary)", marginBottom: "var(--eco-space-md)" }}>
        {"←"} Back
      </button>

      {blocked && (
        <div data-testid="detail-blocked-banner" role="alert" style={{ background: "var(--eco-color-dangerBg)", color: "var(--eco-color-danger)", padding: "var(--eco-space-md)", borderRadius: "var(--eco-radius-md)", marginBottom: "var(--eco-space-md)" }}>
          {item.status === "yanked" ? "This item has been disabled by an administrator." : "This item failed verification and can't be added."}
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
            <div style={{ display: "flex", gap: "var(--eco-space-sm)" }}>
              <button type="button" data-testid="detail-copy-link" onClick={handleCopyLink} style={{ padding: "8px 12px", borderRadius: "var(--eco-radius-md)", border: "1px solid var(--eco-color-border)", background: "var(--eco-color-bg)", cursor: "pointer" }}>
                {copyFeedback ? "Copied!" : "Copy link"}
              </button>
              {canInstall && (
                <button
                  type="button"
                  data-testid="detail-add-button"
                  disabled={!currentVersionId}
                  onClick={() => setShowAddDialog(true)}
                  style={{ padding: "8px 16px", borderRadius: "var(--eco-radius-md)", border: "none", background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)", cursor: "pointer" }}
                >
                  Add
                </button>
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
          {tab === "versions" && <Versions itemId={item.id} installId={null} canRollback={item.allowed_actions.includes("rollback")} />}
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
