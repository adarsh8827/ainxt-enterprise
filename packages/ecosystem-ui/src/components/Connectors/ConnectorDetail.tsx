// SPDX-License-Identifier: MIT
// Connector detail page (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6).
// Reference-layout parity pass (Connectors+Plugins UI redesign,
// 2026-09-30): Connect/Disconnect as a real primary button (was an
// unstyled <button>), "Copy link", Tools as a chip grid (classification
// still conveyed via the same color-coded dot ToolClassificationBadge
// already uses, just compacted into the chip rather than the full text
// badge, kept in each chip's title for anyone hovering/reading via
// assistive tech), a stacked label/value side panel (was a bare <dl>),
// and a lightweight "Related" section (same-category items, client-side --
// see this file's own earlier note: no dedicated "related" endpoint
// exists server-side, so this reuses the ordinary listItems() query
// rather than adding a new backend query just for this section).
import { useEffect, useState } from "react";
import { ArrowTopRightOnSquareIcon, LinkIcon } from "@heroicons/react/24/outline";
import type { ConnectorTool, ItemDetail, ItemSummary } from "../../types";
import { TrustBadge, VerifiedMark } from "../Badges";
import { ItemIcon } from "../ItemIcon";
import { useEcosystemClient } from "../../context/HostContext";
import { publisherLabel } from "../../publisherLabel";
import { resolveConnectionStatus, setConnectionState, useConnectionOverrideVersion } from "../../connectionStore";
import { ToolClassificationBadge } from "./ToolClassificationBadge";

function CopyLinkButton() {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      data-testid="connector-copy-link"
      onClick={() => {
        navigator.clipboard?.writeText(window.location.href).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      style={{
        display: "inline-flex", alignItems: "center", gap: "4px", background: "none", border: "none",
        cursor: "pointer", color: "var(--eco-color-textSecondary)", fontSize: "var(--eco-font-sizeSm)", padding: 0,
      }}
    >
      <LinkIcon width={14} height={14} aria-hidden="true" />
      {copied ? "Copied" : "Copy link"}
    </button>
  );
}

function SidePanelRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: "var(--eco-space-md)" }}>
      <div style={{ fontSize: "var(--eco-font-sizeXs)", color: "var(--eco-color-textMuted)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: "2px" }}>
        {label}
      </div>
      <div style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)" }}>{children}</div>
    </div>
  );
}

function RelatedConnectors({ item }: { item: ItemDetail }) {
  const client = useEcosystemClient();
  const [related, setRelated] = useState<ItemSummary[] | null>(null);

  useEffect(() => {
    let alive = true;
    client.listItems({ item_type: item.item_type, category: [item.category], limit: 6 })
      .then((res) => {
        if (!alive) return;
        setRelated(res.items.filter((i) => i.id !== item.id).slice(0, 4));
      })
      .catch(() => { if (alive) setRelated([]); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id, item.category, item.item_type]);

  if (!related || related.length === 0) return null;
  return (
    <div data-testid="connector-related" style={{ marginTop: "var(--eco-space-xl)" }}>
      <h3 style={{ fontSize: "var(--eco-font-sizeMd)", color: "var(--eco-color-textPrimary)" }}>Related</h3>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--eco-space-sm)" }}>
        {related.map((r) => (
          <div key={r.id} data-testid="connector-related-row" style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-sm)" }}>
            <ItemIcon iconUrl={r.icon_url} namespace={r.namespace} displayName={r.display_name} size={28} />
            <span style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)" }}>{r.display_name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ConnectorDetail({ item }: { item: ItemDetail }) {
  const client = useEcosystemClient();
  useConnectionOverrideVersion();
  const [status, setStatus] = useState<ReturnType<typeof resolveConnectionStatus> | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    client.listConnections().then((conns) => {
      if (!alive) return;
      setStatus(resolveConnectionStatus(item.namespace, conns.find((c) => c.connector_ref === item.namespace)));
    });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.namespace]);

  // Always route through resolveConnectionStatus() rather than falling
  // back to the raw `status` state directly -- the connectionStore
  // override must take priority on every render (a mutation elsewhere on
  // this page, e.g. handleConnect below, updates the store and re-renders
  // via useConnectionOverrideVersion(), but never touches this component's
  // own `status` state). Real bug found live while writing this
  // component's own test: `status ?? resolveConnectionStatus(...)` used
  // the stale fetched value once `status` was non-null, silently ignoring
  // every later override.
  const [connectError, setConnectError] = useState<string | null>(null);
  const resolved = resolveConnectionStatus(item.namespace, status ?? undefined);
  const tools = (item.manifest?.tools as ConnectorTool[] | undefined) ?? [];

  const handleConnect = () => {
    setBusy(true);
    setConnectError(null);
    const call = resolved.status === "needs_reauth" || resolved.status === "expired"
      ? client.reconnect(item.namespace) : client.connect(item.namespace);
    call
      .then((result) => {
        if (result.authorize_url) {
          window.location.assign(result.authorize_url);
          return;
        }
        setConnectionState(item.namespace, {
          connector_ref: item.namespace, item_id: item.id, status: result.status,
          last_connected_at: new Date().toISOString(), expires_at: null,
        });
      })
      // Real bug found live (2026-09-30): connect() used to always resolve
      // {"status": "connected"} for every native connector (a separate,
      // now-fixed backend bug), so this call never actually rejected in
      // practice -- there was no .catch() here at all. Once connect()
      // started correctly rejecting for real cases (no OAuth client
      // configured, a PAT connector needing manual setup, etc.), every one
      // of those became an uncaught promise rejection that silently broke
      // this button with no feedback shown to the user.
      .catch((err: unknown) => setConnectError(err instanceof Error ? err.message : "Couldn't connect."))
      .finally(() => setBusy(false));
  };

  const handleDisconnect = () => {
    setBusy(true);
    setConnectError(null);
    client.disconnect(item.namespace)
      .then(() => setConnectionState(item.namespace, {
        connector_ref: item.namespace, item_id: item.id, status: "not_connected",
        last_connected_at: null, expires_at: null,
      }))
      .catch((err: unknown) => setConnectError(err instanceof Error ? err.message : "Couldn't disconnect."))
      .finally(() => setBusy(false));
  };

  const primaryButtonStyle: React.CSSProperties = {
    display: "inline-flex", alignItems: "center", gap: "6px", padding: "10px 18px",
    borderRadius: "var(--eco-radius-md)", border: "none", cursor: busy ? "default" : "pointer",
    fontWeight: 600, fontSize: "var(--eco-font-sizeSm)",
    background: "var(--eco-color-accentSkill)", color: "var(--eco-color-accentSkillText)",
  };

  return (
    <div data-testid="connector-detail">
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "var(--eco-space-sm)" }}>
        <CopyLinkButton />
      </div>
      <div style={{ display: "flex", gap: "var(--eco-space-xl)", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 480px", minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: "var(--eco-space-md)", marginBottom: "var(--eco-space-md)" }}>
            <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} size={56} />
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <h2 style={{ margin: 0, fontSize: "var(--eco-font-sizeXl)", color: "var(--eco-color-textPrimary)" }}>{item.display_name}</h2>
                <VerifiedMark tier={item.trust_tier} />
              </div>
              <p style={{ margin: "4px 0 0", color: "var(--eco-color-textSecondary)", fontSize: "var(--eco-font-sizeSm)" }}>{item.description}</p>
              <div style={{ marginTop: "6px" }}><TrustBadge tier={item.trust_tier} /></div>
            </div>
            {resolved.status === "connected" ? (
              <button type="button" data-testid="connector-disconnect" disabled={busy} onClick={handleDisconnect} style={{ ...primaryButtonStyle, background: "var(--eco-color-surface)", color: "var(--eco-color-textPrimary)" }}>
                Disconnect
              </button>
            ) : (
              <button type="button" data-testid="connector-connect" disabled={busy} onClick={handleConnect} title={connectError ?? undefined} style={primaryButtonStyle}>
                {busy ? "Connecting…" : connectError ? "Retry" : resolved.status === "needs_reauth" || resolved.status === "expired" ? "Reconnect" : "Connect"}
              </button>
            )}
          </div>
          {connectError && (
            <p data-testid="connector-connect-error" style={{ margin: "0 0 var(--eco-space-md)", color: "var(--eco-color-danger)", fontSize: "var(--eco-font-sizeSm)" }}>
              {connectError}
            </p>
          )}

          <div
            data-testid="connector-trust-note"
            style={{
              padding: "var(--eco-space-sm)", borderRadius: "var(--eco-radius-md)",
              background: "var(--eco-color-warningBg)", color: "var(--eco-color-warning)",
              fontSize: "var(--eco-font-sizeSm)", margin: "var(--eco-space-md) 0",
            }}
          >
            Only connect services you trust — connected tools can read or change data in that service, and the tools it exposes can change over time.
          </div>

          <h3 style={{ fontSize: "var(--eco-font-sizeMd)", color: "var(--eco-color-textPrimary)" }}>Tools</h3>
          {tools.length === 0 ? (
            <p style={{ color: "var(--eco-color-textMuted)", fontSize: "var(--eco-font-sizeSm)" }}>No tools listed for this connector yet.</p>
          ) : (
            // Chip-grid layout (reference parity) -- each chip still carries
            // its OWN real ToolClassificationBadge (not a compressed color
            // dot + a separate generic legend), so a real, per-tool
            // read/write/destructive signal is never lost for the sake of
            // density. data-testid stays "connector-tool-row" -- this
            // module's own pre-existing test asserts on exactly that name.
            <div data-testid="connector-tools-list" style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
              {tools.map((tool) => (
                <span
                  key={tool.name}
                  data-testid="connector-tool-row"
                  title={tool.description}
                  style={{
                    display: "inline-flex", alignItems: "center", gap: "8px", padding: "6px 8px 6px 12px",
                    borderRadius: "var(--eco-radius-full)", border: "1px solid var(--eco-color-border)",
                    background: "var(--eco-color-surface)", fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textPrimary)",
                  }}
                >
                  {tool.name}
                  <ToolClassificationBadge classification={tool.classification} />
                </span>
              ))}
            </div>
          )}

          <RelatedConnectors item={item} />
        </div>

        <aside data-testid="connector-side-panel" style={{ width: 240, flexShrink: 0 }}>
          <SidePanelRow label="Made by">{publisherLabel(item.namespace) || item.publisher.slug}</SidePanelRow>
          <SidePanelRow label="Category">{item.category}</SidePanelRow>
          <SidePanelRow label="Sign-in">Required</SidePanelRow>
          {item.source.url && (
            <SidePanelRow label="Connector URL">
              <span style={{ display: "inline-flex", alignItems: "center", gap: "4px", wordBreak: "break-all", fontFamily: "var(--eco-font-mono, monospace)", fontSize: "var(--eco-font-sizeXs)" }}>
                {item.source.url}
                <ArrowTopRightOnSquareIcon width={12} height={12} aria-hidden="true" style={{ flexShrink: 0 }} />
              </span>
            </SidePanelRow>
          )}
        </aside>
      </div>
    </div>
  );
}
