// SPDX-License-Identifier: MIT
// Connector detail page (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6):
// Connect button, long description, Tools list (read/write/destructive
// tagged), side panel, trust note. No "related connectors" query exists
// server-side yet -- that section is intentionally omitted rather than
// faked with unrelated items.
import { useEffect, useState } from "react";
import type { ConnectorTool, ItemDetail } from "../../types";
import { TrustBadge } from "../Badges";
import { ItemIcon } from "../ItemIcon";
import { useEcosystemClient } from "../../context/HostContext";
import { resolveConnectionStatus, setConnectionState, useConnectionOverrideVersion } from "../../connectionStore";
import { ToolClassificationBadge } from "./ToolClassificationBadge";

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
  const resolved = resolveConnectionStatus(item.namespace, status ?? undefined);
  const tools = (item.manifest?.tools as ConnectorTool[] | undefined) ?? [];

  const handleConnect = () => {
    setBusy(true);
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
      .finally(() => setBusy(false));
  };

  const handleDisconnect = () => {
    setBusy(true);
    client.disconnect(item.namespace)
      .then(() => setConnectionState(item.namespace, {
        connector_ref: item.namespace, item_id: item.id, status: "not_connected",
        last_connected_at: null, expires_at: null,
      }))
      .finally(() => setBusy(false));
  };

  return (
    <div data-testid="connector-detail" style={{ display: "flex", gap: "var(--eco-space-xl)" }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--eco-space-md)", marginBottom: "var(--eco-space-md)" }}>
          <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} size={56} />
          <div>
            <h2 style={{ margin: 0, fontSize: "var(--eco-font-sizeLg)", color: "var(--eco-color-textPrimary)" }}>{item.display_name}</h2>
            <TrustBadge tier={item.trust_tier} />
          </div>
          {resolved.status === "connected" ? (
            <button type="button" data-testid="connector-disconnect" disabled={busy} onClick={handleDisconnect} style={{ marginLeft: "auto" }}>
              Disconnect
            </button>
          ) : (
            <button type="button" data-testid="connector-connect" disabled={busy} onClick={handleConnect} style={{ marginLeft: "auto" }}>
              {resolved.status === "needs_reauth" || resolved.status === "expired" ? "Reconnect" : "Connect"}
            </button>
          )}
        </div>

        <p style={{ color: "var(--eco-color-textSecondary)" }}>{item.description}</p>

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
        <ul data-testid="connector-tools-list" style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {tools.map((tool) => (
            <li key={tool.name} data-testid="connector-tool-row" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "var(--eco-space-sm) 0", borderBottom: "1px solid var(--eco-color-border)" }}>
              <div>
                <div style={{ fontWeight: 600, color: "var(--eco-color-textPrimary)" }}>{tool.name}</div>
                <div style={{ fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>{tool.description}</div>
              </div>
              <ToolClassificationBadge classification={tool.classification} />
            </li>
          ))}
          {tools.length === 0 && (
            <li style={{ color: "var(--eco-color-textMuted)", fontSize: "var(--eco-font-sizeSm)" }}>No tools listed for this connector yet.</li>
          )}
        </ul>
      </div>

      <aside data-testid="connector-side-panel" style={{ width: 240, flexShrink: 0, fontSize: "var(--eco-font-sizeSm)", color: "var(--eco-color-textSecondary)" }}>
        <dl>
          <dt>Made by</dt><dd>{item.publisher.slug}</dd>
          <dt>Category</dt><dd>{item.category}</dd>
          <dt>Sign-in required</dt><dd>Yes</dd>
          {item.source.url && (<><dt>Connector URL</dt><dd>{item.source.url}</dd></>)}
        </dl>
      </aside>
    </div>
  );
}
